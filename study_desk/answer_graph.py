"""Add a small amount of relationship-guided evidence to ordinary retrieval."""

import numpy as np


PASSAGE_BUDGET = 6


def concept_passages(store, embedder, question, graph, indexed):
    """Enter through concept embeddings; never search the full transcript index."""
    query = embedder.encode([question], retrieval_query=True)[0]
    concepts = {c['id']: c for c in graph['concepts'] if not c['merged_into_id']}
    claims = {c['id']: c for c in graph['claims']}
    vectors = list(
        store.db.execute(
            'SELECT id,embedding FROM concept WHERE build_id=%s AND merged_into_id IS NULL',
            (graph['build']['id'],),
        )
    )
    ranked = sorted(vectors, key=lambda c: (-float(np.dot(c['embedding'], query)), c['id']))[:3]
    paths = {}
    for candidate in ranked:
        c = concepts[candidate['id']]
        for claim_id in c['claim_ids']:
            for sid in claims[claim_id]['span_ids']:
                if sid in indexed:
                    paths.setdefault(sid, []).append(c['label'])
    if not paths:
        raise ValueError('No transcript evidence linked to the matched graph concepts.')
    rows = list(store.db.execute('SELECT * FROM evidence_span WHERE id=ANY(%s)', (sorted(paths),)))
    rows.sort(key=lambda r: (-float(np.dot(r['embedding'], query)), r['id']))
    inputs = {i['video_id']: i for i in graph['inputs']}
    return [
        dict(
            passage_id=r['id'],
            video_id=r['video_id'],
            title=inputs[r['video_id']]['title'],
            text=r['text_content'],
            score=float(np.dot(r['embedding'], query)),
            start_s=r['start_s'],
            end_s=r['end_s'],
            url=inputs[r['video_id']]['url'],
            attribution=inputs[r['video_id']].get('attribution'),
            retrieval='graph concept',
            matched_concepts=paths[r['id']],
        )
        for r in rows[:PASSAGE_BUDGET]
    ]


def expand(store, embedder, question, passages, graph, indexed):
    selected = [dict(p) for p in passages[:3]]
    direct_ids = {p['passage_id'] for p in selected}
    claims = {c['id']: c for c in graph['claims']}
    concepts = {c['id']: c for c in graph['concepts'] if not c['merged_into_id']}
    spans = {
        cid: {sid for k in c['claim_ids'] for sid in claims[k]['span_ids']}
        for cid, c in concepts.items()
    }
    anchors = {cid for cid, ids in spans.items() if ids & direct_ids}
    links = []
    for edge in graph['edges']:
        a, b = edge['source_id'], edge['target_id']
        if a not in concepts or b not in concepts:
            continue
        for anchor, neighbor in ((a, b), (b, a)):
            if anchor in anchors:
                for sid in sorted((spans[neighbor] & indexed) - direct_ids):
                    links.append((edge, anchor, neighbor, sid))
    if not links:
        return passages[:PASSAGE_BUDGET], [], graph['build']['id']
    rows = {
        r['id']: r
        for r in store.db.execute(
            'SELECT * FROM evidence_span WHERE id=ANY(%s)', (sorted({link[3] for link in links}),)
        )
    }
    edges = {e['id']: e for e, _, _, _ in links}
    query = embedder.encode([question], retrieval_query=True)[0]
    # Rank the connection itself, not just another passage similar to the question.
    descriptions = [
        f"{concepts[e['source_id']]['label']} {e['predicate']} "
        f"{concepts[e['target_id']]['label']}. {e['rationale']}"
        for e in edges.values()
    ]
    vectors = embedder.encode(descriptions)
    relevance = {eid: float(np.dot(vector, query)) for eid, vector in zip(edges, vectors)}
    ranked = sorted(
        links,
        key=lambda link: (
            -(relevance[link[0]['id']] + float(np.dot(rows[link[3]]['embedding'], query))) / 2,
            link[0]['id'],
            link[3],
        ),
    )
    relations = []
    used_edges = set()
    used_text = {' '.join(p['text'].split()) for p in selected}
    inputs = {i['video_id']: i for i in graph['inputs']}
    for edge, anchor, neighbor, sid in ranked:
        if len(selected) == PASSAGE_BUDGET:
            break
        row = rows[sid]
        text = ' '.join(row['text_content'].split())
        if (
            edge['id'] in used_edges
            or sid in {p['passage_id'] for p in selected}
            or text in used_text
        ):
            continue
        # Reject connections with no positive semantic alignment; no forced expansion.
        if relevance[edge['id']] <= 0 or float(np.dot(row['embedding'], query)) <= 0:
            continue
        item = inputs[row['video_id']]
        source_ids = [
            'S' + str(i + 1) for i, p in enumerate(selected) if p['passage_id'] in spans[anchor]
        ]
        target_id = 'S' + str(len(selected) + 1)
        relation = dict(
            id=edge['id'],
            source=concepts[edge['source_id']]['label'],
            target=concepts[edge['target_id']]['label'],
            relation=edge['predicate'],
            rationale=edge['rationale'],
            anchor=concepts[anchor]['label'],
            neighbor=concepts[neighbor]['label'],
            direct_source_ids=source_ids,
            graph_source_id=target_id,
        )
        selected.append(
            dict(
                passage_id=sid,
                video_id=row['video_id'],
                title=item['title'],
                text=row['text_content'],
                score=float(np.dot(row['embedding'], query)),
                start_s=row['start_s'],
                end_s=row['end_s'],
                url=item['url'],
                attribution=item.get('attribution'),
                retrieval='graph neighbor',
                graph_path=relation,
            )
        )
        relations.append(relation)
        used_edges.add(edge['id'])
        used_text.add(text)
    for passage in passages:
        if len(selected) < PASSAGE_BUDGET and passage['passage_id'] not in {
            p['passage_id'] for p in selected
        }:
            selected.append(dict(passage))
    return selected, relations, graph['build']['id']
