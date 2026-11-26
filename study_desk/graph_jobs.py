"""One graph-build queue, sharing the app's existing processing lock."""

from contextlib import nullcontext
from datetime import datetime, timezone
import json
import time

from psycopg.types.json import Jsonb

from . import config, graph_store
from .graph import select_inputs, prepare_inputs, digest
from .graph_contracts import VERSION, BATCH_SIZE, MAX_TOKENS, SEED
from .graph_pipeline import GraphPipeline
from .storage import Store


def reserve(store, models, rebuild=False, allow_held=False):
    selected = []
    # Validate every requested system before reserving anything.
    for model in models:
        # Bulk/background reservations respect holds. A direct OpenAI build click may proceed.
        if (
            not allow_held
            and store.db.execute(
                "SELECT 1 FROM graph_build WHERE model=%s AND data->>'status'='held'", (model,)
            ).fetchone()
        ):
            continue
        inputs, missing, fingerprint = select_inputs(store, model)
        if rebuild:
            fingerprint = digest([fingerprint, time.time_ns()])
        selected.append((model, inputs, missing, fingerprint))
    jobs = []
    with store.db.transaction():
        for model, inputs, missing, fingerprint in selected:
            existing = store.db.execute(
                'SELECT id FROM graph_build WHERE model=%s AND fingerprint=%s', (model, fingerprint)
            ).fetchone()
            if existing:
                continue
            data = dict(
                model=model,
                status='queued',
                detail='Queued',
                created_at=datetime.now(timezone.utc).isoformat(),
                stage='Prepare',
                done=0,
                total=1,
                activity=0,
                elapsed=0,
                issues=[],
                missing_lectures=missing,
                settings=dict(
                    version=VERSION,
                    batch_size=BATCH_SIZE,
                    starting_point='extracted_topics',
                    max_output_tokens=MAX_TOKENS,
                    seed=SEED if model != 'openai' else None,
                    embedding='BAAI/bge-base-en-v1.5',
                    api_stages=(
                        {
                            'Consolidate': 'gpt-5.6-terra',
                            'Areas': 'gpt-5.6-terra',
                            'Connect': 'gpt-5.6-luna',
                        }
                        if model == 'openai'
                        else None
                    ),
                ),
            )
            bid = store.db.execute(
                'INSERT INTO graph_build(model,fingerprint,data) VALUES (%s,%s,%s) RETURNING id',
                (model, fingerprint, Jsonb(data)),
            ).fetchone()['id']
            jobs.append((bid, inputs, data))
    return jobs


def build(database, bid, inputs, data):
    from .embeddings import Embedder
    from .study_runtime import load_model
    from .openai_model import OpenAIModel

    store = Store(database)
    start = time.monotonic()
    pipeline = None
    model = None
    saved = store.db.execute('SELECT data FROM graph_build WHERE id=%s', (bid,)).fetchone()
    if not saved or saved['data'].get('status') != 'queued':
        store.close()
        return
    folder = config.DATA_DIR / 'graphs' / f'build-{bid:04d}'
    folder.mkdir(parents=True, exist_ok=True)
    data.update(status='running', folder=str(folder))
    (folder / 'inputs.json').write_text(
        json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    last_save = 0

    def report(stage, done, total, tokens=0, current=None):
        nonlocal last_save
        now = time.monotonic()
        if tokens and now - last_save < 0.5:
            return
        last_save = now
        data.update(
            stage=stage,
            done=done,
            total=total,
            activity=tokens,
            elapsed=round(now - start, 1),
            detail=stage,
        )
        if current:
            data.update(
                issues=current.issues,
                timings=current.timings,
                calls=len(current.calls),
                concepts=sum(not x.get('merged_into') for x in current.concepts),
                assigned_claims=sum(bool(v) for v in current.assignments.values()),
                edges=len(current.edges),
            )
        if model and hasattr(model, 'cost'):
            data['estimated_cost_usd'] = model.cost
        graph_store.state(store, bid, data)

    try:
        report('Prepare', 0, len(inputs))
        embedder = Embedder()
        claims, spans, info = prepare_inputs(
            store, inputs, embedder, lambda d, t: report('Prepare', d, t)
        )
        graph_store.save_inputs(store, bid, inputs, claims, spans)
        data.update(claims=len(claims), passages=len(spans), lectures=len(inputs))
        report('Loading model', 0, 1)
        context = (
            nullcontext(OpenAIModel(folder))
            if data['model'] == 'openai'
            else load_model(data['model'], folder)
        )
        with context as model:
            model.seed = SEED

            def checkpoint(p):
                graph_store.save_graph(
                    store,
                    bid,
                    p.concepts,
                    p.assignments,
                    p.resolutions,
                    p.areas,
                    p.memberships,
                    p.edges,
                )

            pipeline = GraphPipeline(model, embedder, folder, info, report, checkpoint)
            pipeline.run(claims)
        data.update(
            status='complete',
            detail='Graph ready',
            stage='Complete',
            done=1,
            total=1,
            activity=0,
            unassigned_claims=sum(not pipeline.assignments.get(x['id']) for x in claims),
            merges=sum(bool(x.get('merged_into')) for x in pipeline.concepts),
        )
    except Exception as exc:
        data.update(status='error', detail=str(exc)[-1000:], activity=0)
    finally:
        data['elapsed'] = round(time.monotonic() - start, 1)
        if pipeline:
            data.update(
                issues=pipeline.issues, timings=pipeline.timings, call_records=pipeline.calls
            )
        if model and hasattr(model, 'cost'):
            data['estimated_cost_usd'] = model.cost
        graph_store.state(store, bid, data)
        (folder / 'result.json').write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        store.close()


def run_queue(processor, jobs):
    try:
        for bid, inputs, data in jobs:
            build(processor.database, bid, inputs, data)
    finally:
        with processor.lock:
            processor.active = False
