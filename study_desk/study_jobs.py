"""Persist generation status and coordinate the four-pass pipeline."""

from pathlib import Path
from contextlib import nullcontext

from .openai_model import OpenAIModel, MODELS as API_MODELS

import json
import time
from datetime import datetime, timezone

from .storage import Store
from . import config
from .study_pipeline import prepare, run, PASSES, VERSION
from .study_runtime import load_model
from .lecture_contracts import (
    OUTPUT_TOKENS,
    FORMAT_VERSION,
    CONSOLIDATE_VERSION,
    FORMAT_PROMPT_HASH,
)


class PassTimings:
    """Wall time per pass for this attempt; loading time is excluded."""

    def __init__(self):
        self.starts = {}
        self.finished = set()
        self.seconds = {}
        self.cached = {}

    def update(self, index, now, complete=False):
        self.starts.setdefault(index, now)
        if index not in self.finished:
            self.seconds[index] = round(now - self.starts[index], 3)
        if complete:
            self.finished.add(index)
        return self.seconds[index]

    def reuse(self, index):
        self.cached[index] = self.cached.get(index, 0) + 1


def generate(database, video, size, run_number=None):
    store = Store(database)
    state = store.run_record(video['id'], size, run_number)
    started = time.monotonic()
    timings = PassTimings()
    attempt = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    state['timing_attempt'] = attempt
    model = None
    try:
        digest, chunks = prepare(video['transcript_path'])
        folder = (
            config.DATA_DIR
            / 'videos'
            / str(video['id'])
            / 'study'
            / size
            / f"run-{state['run_number']:03d}"
            / digest[:20]
        )
        folder.mkdir(parents=True, exist_ok=True)
        state.update(
            digest=digest,
            folder=str(folder),
            detail='Loading local model…',
            settings=dict(
                seed=state.get('seed'),
                seed_policy="same seed on each model call",
                pipeline=VERSION,
                format_version=FORMAT_VERSION,
                format_prompt_sha256=FORMAT_PROMPT_HASH,
                consolidate_version=CONSOLIDATE_VERSION,
                review_policy='advisory-v1',
                temperature=0.6,
                max_output_tokens=dict(zip(PASSES, OUTPUT_TOKENS)),
                context=32768,
                quantization='Q4_K_M',
            ),
        )
        if size == 'openai':
            state['detail'] = 'Preparing OpenAI requests…'
            state['settings'].update(
                provider='OpenAI',
                models=dict(zip(PASSES, API_MODELS)),
                seed=None,
                seed_policy='Not supported by this API route',
                temperature='API default',
                reasoning_effort='low',
                context=None,
                quantization=None,
            )
        store.save_run(video['id'], size, state)
        last_save = 0

        def report(index, done, total, tokens):
            nonlocal last_save
            if size == 'openai' and model is not None:
                model.stage = index
                state['estimated_cost_usd'] = model.cost
            now = time.monotonic()
            if tokens and now - last_save < 0.3:
                return
            last_save = now
            state['passes'][index] = dict(
                done=done,
                total=total,
                activity=tokens,
                status='complete' if done == total else 'running',
                elapsed=timings.update(index, now, done == total),
                cached_calls=timings.cached.get(index, 0),
            )
            state.update(stage=index, elapsed=round(now - started, 1), detail=PASSES[index])
            store.save_run(video['id'], size, state)

        with (
            nullcontext(OpenAIModel(folder)) if size == 'openai' else load_model(size, folder)
        ) as model:
            model.seed = state.get("seed")
            state['preparation_and_load_seconds'] = round(time.monotonic() - started, 3)
            output = run(model, chunks, folder, report, on_cache=timings.reuse)
        from .licensing import attributed_notes

        output.write_text(
            attributed_notes(output.read_text(encoding='utf-8'), video), encoding='utf-8'
        )
        state.update(
            status='complete',
            detail=(
                'Study notes ready.' if size == 'openai' else 'Study notes ready. Model unloaded.'
            ),
            output=str(output),
            elapsed=round(time.monotonic() - started, 1),
        )
    except Exception as exc:
        for index in timings.starts:
            if index not in timings.finished:
                state['passes'][index].update(
                    elapsed=timings.update(index, time.monotonic()), status='error'
                )
        state.update(
            status='error', detail=str(exc)[-1000:], elapsed=round(time.monotonic() - started, 1)
        )
    finally:
        if size == 'openai' and model is not None:
            state['estimated_cost_usd'] = model.cost
            state['api_calls'] = model.calls
        comparison = Path(state.get('folder', '')) / 'comparison.json'
        if comparison.is_file():
            state['comparison'] = json.loads(comparison.read_text(encoding='utf-8'))
        if state.get('folder'):
            # Keep earlier attempts too, so a resumed/cached run never overwrites a benchmark.
            timing_file = Path(state['folder']) / f'timings-{attempt}.json'
            timing_file.write_text(
                json.dumps(
                    {
                        'attempt': attempt,
                        'model': size,
                        'seed': state.get('seed'),
                        'status': state['status'],
                        'total_seconds': state['elapsed'],
                        'estimated_cost_usd': state.get('estimated_cost_usd'),
                        'api_calls': state.get('api_calls'),
                        'preparation_and_load_seconds': state.get('preparation_and_load_seconds'),
                        'passes': [
                            dict(name=name, **record)
                            for name, record in zip(PASSES, state['passes'])
                        ],
                        'note': 'Wall seconds for this attempt. Cached calls reuse earlier outputs; not a fresh benchmark.',
                    },
                    indent=2,
                ),
                encoding='utf-8',
            )
        store.save_run(video['id'], size, state)
        store.close()
