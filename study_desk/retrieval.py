"""Shared transcript retrieval using local BGE and PostgreSQL; no answer generation.

Index selected saved transcripts: python -m study_desk.retrieval index
Search all indexed videos: python -m study_desk.retrieval search "What is alpha beta pruning?"
"""

import argparse
import json
from pathlib import Path

import numpy as np

from .config import DATABASE
from .storage import Store
from .embeddings import Embedder
from .graph import prepare_inputs
from .study_pipeline import prepare

SCHEMA = '''
CREATE TABLE IF NOT EXISTS rag_transcript (
 video_id BIGINT PRIMARY KEY REFERENCES video_intake(id) ON DELETE CASCADE,
 transcript_digest TEXT NOT NULL, embedding_revision TEXT NOT NULL,
 indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rag_passage (
 video_id BIGINT REFERENCES rag_transcript(video_id) ON DELETE CASCADE,
 span_id TEXT REFERENCES evidence_span(id) ON DELETE CASCADE,
 PRIMARY KEY(video_id,span_id)
);
'''


def index_transcripts(store, embedder, report=print):
    store.db.execute(SCHEMA)
    summary = []
    for video in sorted(store.urls(), key=lambda v: v['id']):
        if not video.get('transcript_path'):
            summary.append(dict(video_id=video['id'], status='no selected transcript'))
            continue
        fingerprint, chunks = prepare(video['transcript_path'])
        item = dict(video_id=video['id'], sources=chunks, extracts=[{'topics': []} for _ in chunks])
        _, spans, info = prepare_inputs(store, [item], embedder, lambda *_: None)
        # Save the complete membership atomically. Existing graph evidence is untouched.
        with store.db.transaction(), store.db.cursor() as cur:
            cur.executemany(
                '''INSERT INTO evidence_span VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING''',
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
            cur.execute(
                '''INSERT INTO rag_transcript(video_id,transcript_digest,embedding_revision)
                VALUES (%s,%s,%s) ON CONFLICT(video_id) DO UPDATE SET
                transcript_digest=excluded.transcript_digest,embedding_revision=excluded.embedding_revision,indexed_at=now()''',
                (video['id'], fingerprint, info['embedding_revision']),
            )
            cur.execute('DELETE FROM rag_passage WHERE video_id=%s', (video['id'],))
            cur.executemany(
                'INSERT INTO rag_passage VALUES (%s,%s)', [(video['id'], s['id']) for s in spans]
            )
        entry = dict(video_id=video['id'], passages=len(spans), status='indexed')
        summary.append(entry)
        report(json.dumps(entry))
    return summary


def validate_index(store):
    revision = json.loads(
        (Path(__file__).resolve().parents[1] / 'models/bge-base-en-v1.5/manifest.json').read_text()
    )['revision']
    # Refuse stale selections rather than quietly mixing different transcripts.
    selected = {v['id']: v for v in store.urls()}
    for record in store.db.execute('SELECT * FROM rag_transcript'):
        video = selected[record['video_id']]
        if (
            not video.get('transcript_path')
            or prepare(video['transcript_path'])[0] != record['transcript_digest']
            or record['embedding_revision'] != revision
        ):
            raise ValueError('Transcript index is stale. Run the index command again.')


def search(store, embedder, question, top_k=5):
    if not question.strip():
        raise ValueError('Question cannot be empty')
    if not 1 <= top_k <= 50:
        raise ValueError('top_k must be between 1 and 50')
    validate_index(store)
    rows = list(
        store.db.execute(
            '''SELECT e.*,v.url,m.data AS metadata FROM rag_passage r
        JOIN evidence_span e ON e.id=r.span_id JOIN video_intake v ON v.id=r.video_id
        LEFT JOIN video_metadata m ON m.video_id=v.id ORDER BY e.video_id,e.source_id,e.start_char'''
        )
    )
    if not rows:
        return []
    query = embedder.encode([question], retrieval_query=True)[0]
    scores = np.asarray([r['embedding'] for r in rows], dtype=np.float32) @ query
    results = []
    for idx in np.argsort(-scores, kind='stable')[:top_k]:
        r = rows[int(idx)]
        metadata = r['metadata'] or {}
        start = r['start_s']
        results.append(
            dict(
                passage_id=r['id'],
                video_id=r['video_id'],
                title=metadata.get('title', r['url']),
                score=float(scores[idx]),
                text=r['text_content'],
                start_s=start,
                end_s=r['end_s'],
                source_id=r['source_id'],
                url=r['url'] + ('&t=' + str(int(start)) if start is not None else ''),
                attribution=metadata.get('content_license'),
                timestamp_scope='original transcript chunk',
            )
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['index', 'search'])
    parser.add_argument('question', nargs='?')
    parser.add_argument('--top-k', type=int, default=5)
    args = parser.parse_args()
    if args.action == 'search' and not args.question:
        parser.error('search requires a question')
    store = Store(DATABASE)
    try:
        store.db.execute(SCHEMA)
        embedder = Embedder()
        if args.action == 'index':
            index_transcripts(store, embedder)
        else:
            print(
                json.dumps(
                    search(store, embedder, args.question, args.top_k), ensure_ascii=False, indent=2
                )
            )
    finally:
        store.close()


if __name__ == '__main__':
    main()
