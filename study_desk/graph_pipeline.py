"""Bounded graph stages. Models decide meaning; code retains source records and IDs."""

import json
import time

import numpy as np

from . import graph_contracts as c
from .graph import embed_texts
from .model import ModelOutputError


def validate(value, schema):
    kind = schema.get('type')
    if kind == 'object':
        if not isinstance(value, dict) or set(value) != set(schema['properties']):
            raise ValueError('Unexpected object fields')
        for k, s in schema['properties'].items():
            validate(value[k], s)
    elif kind == 'array':
        if not isinstance(value, list) or len(value) > schema.get('maxItems', 10000):
            raise ValueError('Invalid list')
        for item in value:
            validate(item, schema['items'])
    elif kind == 'integer' and type(value) is not int:
        raise ValueError('Expected integer ID')
    elif kind == 'string':
        if not isinstance(value, str) or len(value) > schema.get('maxLength', 100000):
            raise ValueError('Invalid text')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('Invalid decision')


def nearest(vector, concepts, count=5):
    active = [x for x in concepts if not x.get('merged_into')]
    if not active:
        return []
    scores = np.array([x['embedding'] for x in active]) @ np.asarray(vector)
    order = sorted(range(len(active)), key=lambda i: (-scores[i], active[i]['id']))[:count]
    return [active[i] for i in order]


def brief(concept):
    return {k: concept[k] for k in ('label', 'description')}


def apply_merge(concepts, assignments, left, right):
    by_id = {x['id']: x for x in concepts}

    def root(cid):
        while by_id[cid].get('merged_into'):
            cid = by_id[cid]['merged_into']
        return cid

    left, right = root(left), root(right)
    if left == right:
        return
    survivor, retired = sorted((left, right))
    by_id[retired]['merged_into'] = survivor
    by_id[survivor]['aliases'].add(by_id[retired]['label'])
    by_id[survivor]['aliases'].update(by_id[retired]['aliases'])
    for ids in assignments.values():
        if retired in ids:
            ids.remove(retired)
            ids.add(survivor)
    # Point all retired records directly to the final canonical concept.
    for x in concepts:
        if x.get('merged_into'):
            x['merged_into'] = root(x['id'])


class GraphPipeline:
    def __init__(self, model, embedder, folder, info, report, checkpoint):
        self.model, self.embedder, self.folder, self.info = model, embedder, folder, info
        self.report, self.checkpoint = report, checkpoint
        self.issues = []
        self.timings = {}
        self.calls = []
        self.concepts = []
        self.assignments = {}
        self.resolutions = []
        self.areas = []
        self.memberships = {}
        self.edges = []

    def flag(self, stage, detail):
        self.issues.append(dict(stage=stage, detail=detail))

    def call(self, stage, index, total, prompt, payload, schema, bindings=None):
        self.model.stage = {'Consolidate': 1, 'Areas': 2, 'Connect': 3}[stage]
        self.report(stage, index, total, 0, self)
        name = f'{stage.lower()}-{index+1:04d}'
        path = self.folder / f'{name}.json'
        text = c.INTRO + '\n' + prompt + '\nDATA:\n' + json.dumps(payload, ensure_ascii=False)
        (self.folder / f'{name}.prompt.txt').write_text(text, encoding='utf-8')
        start = time.monotonic()
        result = {}
        error = None
        try:
            answer = self.model.complete(
                text,
                on_token=lambda n: self.report(stage, index, total, n, self),
                json_mode=schema,
                max_tokens=c.MAX_TOKENS,
            )
            (self.folder / f'{name}.response.txt').write_text(answer, encoding='utf-8')
            result = json.loads(answer)
            validate(result, schema)
        except (ValueError, ModelOutputError) as exc:
            if isinstance(exc, ModelOutputError):
                (self.folder / f'{name}.response.txt').write_text(exc.output, encoding='utf-8')
            error = str(exc)
            self.flag(stage, f'{name}: {error}')
            result = {}
        elapsed = round(time.monotonic() - start, 3)
        self.timings[stage] = round(self.timings.get(stage, 0) + elapsed, 3)
        self.calls.append(
            dict(
                stage=stage,
                index=index + 1,
                seconds=elapsed,
                error=error,
                request=getattr(self.model, 'request_info', {}),
            )
        )
        path.write_text(
            json.dumps(
                dict(result=result, error=error, seconds=elapsed, bindings=bindings or {}),
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )
        self.report(stage, index + 1, total, 0, self)
        return result, str(self.folder / f'{name}.response.txt')

    def persist(self):
        self.checkpoint(self)

    def seed_topics(self, claims):
        """Use extraction positions, never title equality, to preserve topic provenance."""
        groups = {}
        for claim in claims:
            key = (claim['video_id'], claim['extraction_id'].rsplit('/', 1)[0])
            groups.setdefault(key, []).append(claim)
        start = time.monotonic()
        for i, group in enumerate(groups.values()):
            topic = group[0]['original']['topic']
            label = topic.get('title', '').strip() or 'Untitled topic'
            description = topic.get('gist', '').strip() or group[0]['text']
            text = '\n'.join([label, description, *[x['text'] for x in group]])
            concept = dict(
                id=len(self.concepts) + 1,
                label=label,
                description=description,
                aliases=set(),
                embedding=embed_texts(self.embedder, [text])[0],
                **self.info,
            )
            self.concepts.append(concept)
            for claim in group:
                self.assignments[claim['id']] = {concept['id']}
            self.report('Topics', i + 1, len(groups), 0, self)
        self.timings['Topics'] = round(time.monotonic() - start, 3)
        self.persist()

    def concept_context(self, concept, claims):
        related = [x for x in claims if concept['id'] in self.assignments.get(x['id'], set())]
        first = {}
        for claim in related:
            first.setdefault(claim['video_id'], claim)
        ordered = list(first.values()) + [
            x for x in related if x['id'] not in {c['id'] for c in first.values()}
        ]
        selected = ordered[:3]
        return dict(**brief(concept), claims=[x['text'] for x in selected]), [
            x['id'] for x in selected
        ]

    def candidate_pairs(self, concepts, neighbors):
        pairs = set()
        for concept in concepts:
            others = [x for x in concepts if x['id'] != concept['id']]
            for other in nearest(concept['embedding'], others, neighbors):
                pairs.add(tuple(sorted((concept['id'], other['id']))))
        return sorted(pairs)

    def pair_batch(self, pairs, by_id, claims):
        # Each concept appears only once in the input, even if several pairs reference it.
        ids = list(dict.fromkeys(cid for pair in pairs for cid in pair))
        keys = {cid: f'C{i+1}' for i, cid in enumerate(ids)}
        contexts = {}
        refs = {}
        for cid in ids:
            contexts[keys[cid]], refs[cid] = self.concept_context(by_id[cid], claims)
        slots = {f'P{i+1}': dict(left=keys[a], right=keys[b]) for i, (a, b) in enumerate(pairs)}
        bindings = {
            f'P{i+1}': dict(
                left_id=a, right_id=b, context_claim_ids=list(dict.fromkeys(refs[a] + refs[b]))
            )
            for i, (a, b) in enumerate(pairs)
        }
        return dict(concepts=contexts, pairs=slots), bindings

    def run(self, claims):
        by_claim = {x['id']: x for x in claims}
        self.seed_topics(claims)
        by_id = {x['id']: x for x in self.concepts}
        pairs = self.candidate_pairs(self.concepts, 2)
        batches = [pairs[i : i + c.BATCH_SIZE] for i in range(0, len(pairs), c.BATCH_SIZE)]
        checked = set()
        for i, batch in enumerate(batches):
            current = []
            for a, b in batch:
                a = by_id[a].get('merged_into') or a
                b = by_id[b].get('merged_into') or b
                key = tuple(sorted((a, b)))
                if a != b and key not in checked:
                    current.append(key)
                    checked.add(key)
            if not current:
                self.report('Consolidate', i + 1, len(batches), 0, self)
                continue
            payload, bindings = self.pair_batch(current, by_id, claims)
            result, path = self.call(
                'Consolidate',
                i,
                len(batches),
                c.MERGE_PROMPT,
                payload,
                c.slots_schema(bindings, c.MERGE),
                bindings,
            )
            for slot, row in result.items():
                binding = bindings[slot]
                a, b = binding['left_id'], binding['right_id']
                self.resolutions.append(dict(row, left_id=a, right_id=b, response_path=path))
                if row['decision'] == 'merge':
                    apply_merge(self.concepts, self.assignments, a, b)
            self.persist()

        active = [x for x in self.concepts if not x.get('merged_into')]
        # Represent a merged group using every retained topic vector, not just its first title.
        vectors = {x['id']: list(x['embedding']) for x in self.concepts}
        for concept in active:
            members = [
                vectors[x['id']]
                for x in self.concepts
                if (x.get('merged_into') or x['id']) == concept['id']
            ]
            vector = np.mean(members, axis=0)
            norm = np.linalg.norm(vector)
            if norm:
                concept['embedding'] = (vector / norm).tolist()
        self.persist()
        batches = [active[i : i + c.BATCH_SIZE] for i in range(0, len(active), c.BATCH_SIZE)]
        area_names = {}
        for i, batch in enumerate(batches):
            bindings = {f'C{j+1}': x['id'] for j, x in enumerate(batch)}
            payload = dict(
                concepts={
                    key: self.concept_context(by_id[cid], claims)[0]
                    for key, cid in bindings.items()
                },
                existing_areas=[x['label'] for x in self.areas],
            )
            result, _ = self.call(
                'Areas',
                i,
                len(batches),
                c.AREA_PROMPT,
                payload,
                c.slots_schema(bindings, c.AREA),
                bindings,
            )
            for key, cid in bindings.items():
                self.memberships[cid] = set()
                for label in result.get(key, {}).get('areas', []):
                    label = label.strip()
                    if not label:
                        continue
                    normalized = ' '.join(label.casefold().split())
                    if normalized not in area_names:
                        area = dict(id=len(self.areas) + 1, label=label, description='')
                        self.areas.append(area)
                        area_names[normalized] = area['id']
                    self.memberships[cid].add(area_names[normalized])
                if not self.memberships[cid]:
                    self.flag('Areas', f'No subject area assigned to concept {cid}')
            self.persist()

        pairs = self.candidate_pairs(active, 3)
        batches = [pairs[i : i + c.BATCH_SIZE] for i in range(0, len(pairs), c.BATCH_SIZE)]
        for i, batch in enumerate(batches):
            payload, bindings = self.pair_batch(batch, by_id, claims)
            result, _ = self.call(
                'Connect',
                i,
                len(batches),
                c.EDGE_PROMPT,
                payload,
                c.slots_schema(bindings, c.EDGES),
                bindings,
            )
            for slot, row in result.items():
                if row['direction'] == 'none':
                    continue
                predicate = row['predicate'].strip()
                binding = bindings[slot]
                a, b = binding['left_id'], binding['right_id']
                if not predicate:
                    self.flag('Connect', f'Empty relationship for pair {a}, {b}')
                    continue
                source, target = (a, b) if row['direction'] == 'left_to_right' else (b, a)
                refs = binding['context_claim_ids']
                self.edges.append(
                    dict(
                        id=len(self.edges) + 1,
                        source_id=source,
                        target_id=target,
                        predicate=predicate,
                        rationale=row['rationale'],
                        claim_ids=refs,
                        span_ids=sorted({sid for ref in refs for sid in by_claim[ref]['span_ids']}),
                    )
                )
            self.persist()
        return self
