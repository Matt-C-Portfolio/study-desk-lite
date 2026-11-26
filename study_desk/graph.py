"""Select immutable extraction inputs and prepare shared evidence embeddings."""

import hashlib
import json
from pathlib import Path

from . import config
from .graph_contracts import VERSION

MODELS = ('1.5B', '7B', '14B', 'openai')


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def select_inputs(store, model):
    if model not in MODELS:
        raise ValueError('Unknown graph model')
    presets = json.loads((config.ROOT / 'lecture-presets.json').read_text(encoding='utf-8'))
    videos = {v['url']: v for v in store.urls()}
    inputs, missing = [], []
    for preset in presets:
        video = videos.get(preset['url'])
        if not video:
            missing.append(preset['title'])
            continue
        runs = sorted(store.history(video['id']).get(model, []), key=lambda r: r['run_number'])
        run = next((r for r in runs if r.get('status') == 'complete'), None)
        if not run:
            missing.append(preset['title'])
            continue
        folder = Path(run['folder'])
        sources = json.loads((folder / 'source.json').read_text(encoding='utf-8'))
        extracts = [
            json.loads((folder / f'extract-{i+1}.json').read_text(encoding='utf-8'))
            for i in range(len(sources))
        ]
        inputs.append(
            dict(
                video_id=video['id'],
                title=preset['title'],
                url=video['url'],
                attribution=video.get('metadata', {}).get('content_license'),
                model=model,
                run_number=run['run_number'],
                run_digest=run.get('digest'),
                folder=str(folder),
                sources=sources,
                extracts=extracts,
                source_hash=digest(sources),
                extraction_hash=digest(extracts),
            )
        )
    if not inputs:
        raise ValueError('No successful saved runs are available for this system.')
    fingerprint = digest(
        dict(
            version=VERSION,
            model=model,
            inputs=[
                {k: i[k] for k in ('video_id', 'run_number', 'source_hash', 'extraction_hash')}
                for i in inputs
            ],
        )
    )
    return inputs, missing, fingerprint


def split_passage(text, embedder):
    """Exact substrings retaining their original chunk's time range, not guessed timestamps."""
    embedder.tokenizer.no_padding()
    encoded = embedder.tokenizer.encode(text, add_special_tokens=False)
    embedder.tokenizer.enable_padding(pad_id=0, pad_token='[PAD]')
    offsets = encoded.offsets
    start = 0
    for at in range(0, len(offsets), 400):
        end = offsets[at + 400][0] if at + 400 < len(offsets) else len(text)
        if end > start and text[start:end].strip():
            yield start, end, text[start:end]
        start = end


def embed_texts(embedder, texts):
    """Pool normalized BGE windows for long claim queries without truncating text."""
    import numpy as np

    result = []
    for text in texts:
        windows = [s[2] for s in split_passage(text, embedder)]
        if not windows:
            raise ValueError('Cannot embed empty graph text')
        vector = embedder.encode(windows).mean(axis=0)
        result.append((vector / np.linalg.norm(vector)).tolist())
    return result


def prepare_inputs(store, inputs, embedder, report):
    manifest = json.loads(
        (config.ROOT / 'models/bge-base-en-v1.5/manifest.json').read_text(encoding='utf-8')
    )
    info = dict(embedding_model='BAAI/bge-base-en-v1.5', embedding_revision=manifest['revision'])
    claims, spans = [], {}
    for index, item in enumerate(inputs):
        report(index, len(inputs))
        for chunk_index, (source, extracted) in enumerate(zip(item['sources'], item['extracts'])):
            source_key = digest(dict(video=item['video_id'], source=source))
            existing = list(
                store.db.execute(
                    'SELECT * FROM evidence_span WHERE source_hash=%s AND embedding_revision=%s ORDER BY start_char',
                    (source_key, info['embedding_revision']),
                )
            )
            if existing:
                parts = [
                    dict(
                        id=r['id'],
                        video_id=r['video_id'],
                        source_hash=source_key,
                        source_id=r['source_id'],
                        start=r['start_s'],
                        end=r['end_s'],
                        start_char=r['start_char'],
                        end_char=r['end_char'],
                        text=r['text_content'],
                        embedding=r['embedding'],
                        embedding_model=r['embedding_model'],
                        embedding_revision=r['embedding_revision'],
                    )
                    for r in existing
                ]
            else:
                pieces = list(split_passage(source['text'], embedder))
                vectors = embedder.encode([p[2] for p in pieces]).tolist()
                parts = [
                    dict(
                        id=digest([source_key, a, b, info]),
                        video_id=item['video_id'],
                        source_hash=source_key,
                        source_id=source['id'],
                        start=source.get('start'),
                        end=source.get('end'),
                        start_char=a,
                        end_char=b,
                        text=text,
                        embedding=v,
                        **info,
                    )
                    for (a, b, text), v in zip(pieces, vectors)
                ]
            spans.update({p['id']: p for p in parts})
            for ti, topic in enumerate(extracted['topics']):
                texts = [('bullet', bi, text) for bi, text in enumerate(topic.get('bullets', []))]
                if not texts and topic.get('gist'):
                    texts = [('gist', 0, topic['gist'])]
                for kind, bi, text in texts:
                    eid = f'extract-{chunk_index+1}/topic-{ti+1}/{kind}-{bi+1}'
                    claims.append(
                        dict(
                            id=f"V{item['video_id']}:{eid}",
                            extraction_id=eid,
                            video_id=item['video_id'],
                            text=text,
                            span_ids=[p['id'] for p in parts],
                            source=source,
                            original=dict(
                                kind=kind,
                                topic=topic,
                                source_id=source['id'],
                                extract_file=f'extract-{chunk_index+1}.json',
                            ),
                        )
                    )
    report(len(inputs), len(inputs))
    return claims, list(spans.values()), info
