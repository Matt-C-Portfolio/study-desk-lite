"""PostgreSQL graph records; source runs are only read, never updated."""

from psycopg.types.json import Jsonb


def state(store, build_id, data):
    store.db.execute('UPDATE graph_build SET data=%s WHERE id=%s', (Jsonb(data), build_id))


def save_inputs(store, build_id, inputs, claims, spans):
    with store.db.transaction(), store.db.cursor() as cur:
        cur.executemany(
            'INSERT INTO graph_input VALUES (%s,%s,%s,%s,%s)',
            [(build_id, i['video_id'], i['model'], i['run_number'], Jsonb(i)) for i in inputs],
        )
        cur.executemany(
            'INSERT INTO evidence_span VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',
            [
                (
                    s['id'],
                    s['video_id'],
                    s['source_hash'],
                    s['source_id'],
                    s['start'],
                    s['end'],
                    s['start_char'],
                    s['end_char'],
                    s['text'],
                    s['embedding'],
                    s['embedding_model'],
                    s['embedding_revision'],
                )
                for s in spans
            ],
        )
        cur.executemany(
            'INSERT INTO graph_claim VALUES (%s,%s,%s,%s,%s,%s)',
            [
                (
                    build_id,
                    c['id'],
                    c['video_id'],
                    c['extraction_id'],
                    c['text'],
                    Jsonb(c['original']),
                )
                for c in claims
            ],
        )
        cur.executemany(
            'INSERT INTO claim_evidence VALUES (%s,%s,%s)',
            [(build_id, c['id'], sid) for c in claims for sid in c['span_ids']],
        )


def save_graph(store, build_id, concepts, assignments, resolutions, areas, memberships, edges):
    with store.db.transaction(), store.db.cursor() as cur:
        cur.executemany(
            '''INSERT INTO concept VALUES (%s,%s,%s,%s,NULL,%s,%s,%s)
            ON CONFLICT(build_id,id) DO UPDATE SET label=excluded.label,description=excluded.description,
            embedding=excluded.embedding,embedding_model=excluded.embedding_model,embedding_revision=excluded.embedding_revision''',
            [
                (
                    build_id,
                    c['id'],
                    c['label'],
                    c['description'],
                    c['embedding'],
                    c['embedding_model'],
                    c['embedding_revision'],
                )
                for c in concepts
            ],
        )
        cur.executemany(
            'UPDATE concept SET merged_into_id=%s WHERE build_id=%s AND id=%s',
            [(c.get('merged_into'), build_id, c['id']) for c in concepts],
        )
        for table in (
            'claim_concept',
            'concept_alias',
            'concept_resolution',
            'concept_subject_area',
            'edge_evidence',
            'concept_edge',
            'subject_area',
        ):
            cur.execute(f'DELETE FROM {table} WHERE build_id=%s', (build_id,))
        cur.executemany(
            'INSERT INTO claim_concept VALUES (%s,%s,%s)',
            [(build_id, claim, cid) for claim, ids in assignments.items() for cid in sorted(ids)],
        )
        cur.executemany(
            'INSERT INTO concept_alias VALUES (%s,%s,%s)',
            [(build_id, c['id'], a) for c in concepts for a in sorted(c.get('aliases', set()))],
        )
        cur.executemany(
            'INSERT INTO concept_resolution VALUES (%s,%s,%s,%s,%s,%s)',
            [
                (
                    build_id,
                    r['left_id'],
                    r['right_id'],
                    r['decision'],
                    r['rationale'],
                    r['response_path'],
                )
                for r in resolutions
            ],
        )
        cur.executemany(
            'INSERT INTO subject_area VALUES (%s,%s,%s,%s)',
            [(build_id, a['id'], a['label'], a['description']) for a in areas],
        )
        cur.executemany(
            'INSERT INTO concept_subject_area VALUES (%s,%s,%s)',
            [(build_id, cid, aid) for cid, aids in memberships.items() for aid in sorted(aids)],
        )
        cur.executemany(
            'INSERT INTO concept_edge VALUES (%s,%s,%s,%s,%s,%s,%s)',
            [
                (
                    build_id,
                    e['id'],
                    e['source_id'],
                    e['target_id'],
                    e['predicate'],
                    e['rationale'],
                    Jsonb(e['claim_ids']),
                )
                for e in edges
            ],
        )
        cur.executemany(
            'INSERT INTO edge_evidence VALUES (%s,%s,%s)',
            [(build_id, e['id'], sid) for e in edges for sid in e['span_ids']],
        )


def read_graph(store, model):
    builds = [
        dict(id=r['id'], **r['data'])
        for r in store.db.execute(
            'SELECT id,data FROM graph_build WHERE model=%s ORDER BY id DESC', (model,)
        )
    ]
    if not builds:
        return dict(
            model=model,
            build=None,
            builds=[],
            inputs=[],
            concepts=[],
            claims=[],
            areas=[],
            edges=[],
            resolutions=[],
        )
    build = builds[0]
    bid = build['id']

    def rows(table, columns='*'):
        return list(store.db.execute(f'SELECT {columns} FROM {table} WHERE build_id=%s', (bid,)))

    concepts = rows('concept', 'id,label,description,merged_into_id')
    claims = rows('graph_claim', 'id,video_id,extraction_id,claim_text,original')
    mapping, cm = rows('claim_concept'), rows('concept_subject_area')
    spans = list(
        store.db.execute(
            '''SELECT DISTINCT s.id,s.video_id,s.source_id,s.start_s,s.end_s,s.start_char,s.end_char,s.text_content
        FROM evidence_span s JOIN claim_evidence ce ON ce.span_id=s.id WHERE ce.build_id=%s ORDER BY s.video_id,s.source_id,s.start_char''',
            (bid,),
        )
    )
    evidence, aliases = rows('claim_evidence'), rows('concept_alias')
    for c in concepts:
        c['claim_ids'] = [m['claim_id'] for m in mapping if m['concept_id'] == c['id']]
        c['area_ids'] = [m['area_id'] for m in cm if m['concept_id'] == c['id']]
        c['aliases'] = [m['alias'] for m in aliases if m['concept_id'] == c['id']]
    for c in claims:
        c['span_ids'] = [m['span_id'] for m in evidence if m['claim_id'] == c['id']]
        c['concept_ids'] = [m['concept_id'] for m in mapping if m['claim_id'] == c['id']]
    inputs = [
        {k: v for k, v in r['snapshot'].items() if k not in ('sources', 'extracts', 'folder')}
        for r in rows('graph_input')
    ]
    return dict(
        model=model,
        build=build,
        builds=builds,
        inputs=inputs,
        concepts=concepts,
        claims=claims,
        spans=spans,
        areas=rows('subject_area'),
        edges=rows('concept_edge'),
        resolutions=rows('concept_resolution'),
    )
