"""Seven-worker API experiment dispatcher. Existing server runs are adopted, never restarted."""

import hashlib
import json
import msvcrt
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from study_desk.storage import Store
from study_desk.study_jobs import generate

MANIFEST = ROOT / 'data/experiments/openai-repeat-progress.json'
from study_desk.config import DATABASE

WORKERS = 7
TERMINAL = {'complete', 'error', 'failed', 'cancelled'}


def get():
    with urlopen('http://127.0.0.1:8788/api/urls', timeout=20) as response:
        return json.load(response)


def save(state):
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    tmp = MANIFEST.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
    tmp.replace(MANIFEST)


def execute(video, number):
    try:
        generate(DATABASE, video, 'openai', number)
    except Exception as exc:
        store = Store(DATABASE)
        try:
            record = store.run_record(video['id'], 'openai', number)
            record.update(status='error', detail=str(exc)[-1000:])
            store.save_run(video['id'], 'openai', record)
        finally:
            store.close()
    store = Store(DATABASE)
    try:
        record = store.run_record(video['id'], 'openai', number)
        if record.get('folder'):
            (Path(record['folder']) / 'execution.json').write_text(
                json.dumps(record['execution'], indent=2), encoding='utf-8'
            )
    finally:
        store.close()


def reserve(entry, number):
    store = Store(DATABASE)
    try:
        store.db.execute('BEGIN')
        store.db.execute(
            'SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f"{entry['id']}:openai",)
        )
        video = store.video(entry['id'])
        if not video or video['url'] != entry['url']:
            raise RuntimeError('Lecture identity changed')
        path = Path(video['transcript_path'])
        if (
            str(path) != entry['transcript_path']
            or hashlib.sha256(path.read_bytes()).hexdigest() != entry['transcript_sha256']
        ):
            raise RuntimeError('Transcript changed for ' + entry['title'])
        history = store.history(video['id']).get('openai', [])
        if any(r['run_number'] == number for r in history):
            return None
        if max((r['run_number'] for r in history), default=0) + 1 != number:
            raise RuntimeError('Unexpected run numbering')
        record = store.new_run(
            video['id'],
            'openai',
            dict(
                status='running',
                detail='Preparing OpenAI requests…',
                seed=None,
                transcript_path=video['transcript_path'],
                model='openai',
                stage=0,
                execution={
                    'dispatcher': 'openai-repeat-workers',
                    'worker_limit': WORKERS,
                    'mode': 'parallel',
                    'started_at': datetime.now(timezone.utc).isoformat(),
                },
                passes=[dict(done=0, total=1, activity=0, status='pending') for _ in range(4)],
            ),
        )
        store.db.commit()
        return video, record['run_number']
    finally:
        store.close()


def main():
    with (MANIFEST.parent / 'openai-repeat.lock').open('a+b') as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        state = json.loads(MANIFEST.read_text(encoding='utf-8'))
        state.update(
            worker_limit=WORKERS, concurrency_changed_at=datetime.now(timezone.utc).isoformat()
        )
        state['adopted_runs'] = [
            {'lecture_id': v['id'], 'run_number': r['run_number']}
            for v in get()
            for r in v['run_history'].get('openai', [])
            if r['status'] in ['running', 'queued']
        ]
        save(state)
        futures = []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            try:
                while True:
                    videos = get()
                    pending = []
                    finished = 0
                    for entry in state['lectures']:
                        v = next(
                            x for x in videos if x['id'] == entry['id'] and x['url'] == entry['url']
                        )
                        history = {r['run_number']: r for r in v['run_history'].get('openai', [])}
                        entry['runs'] = [
                            {
                                k: r.get(k)
                                for k in [
                                    'run_number',
                                    'status',
                                    'elapsed',
                                    'estimated_cost_usd',
                                    'stage',
                                    'detail',
                                    'execution',
                                ]
                            }
                            for n, r in history.items()
                            if n in entry['target_runs']
                        ]
                        for n in entry['target_runs']:
                            if n not in history:
                                pending.append((entry, n))
                            elif history[n]['status'] in TERMINAL:
                                finished += 1
                    active = [
                        r
                        for v in videos
                        for rs in v['run_history'].values()
                        for r in rs
                        if r['status'] in ['running', 'queued']
                    ]
                    state.update(
                        status='running', finished=finished, total=40, active_count=len(active)
                    )
                    save(state)
                    if finished == 40:
                        state['status'] = 'complete'
                        save(state)
                        return
                    # Keep local GPU/transcript work separate; count adopted API runs against capacity.
                    blocked = any(r['model'] != 'openai' for r in active) or any(
                        v['state'] in ['checking', 'downloading', 'transcribing'] for v in videos
                    )
                    for future in futures:
                        if future.done():
                            future.result()
                    futures = [f for f in futures if not f.done()]
                    slots = 0 if blocked else max(0, WORKERS - len(active))
                    for entry, n in pending[:slots]:
                        job = reserve(entry, n)
                        if job:
                            futures.append(pool.submit(execute, *job))
                            print(
                                f"Lecture {entry['id']}: started OpenAI run {n}, worker limit {WORKERS}",
                                flush=True,
                            )
                    time.sleep(3)
            except Exception as exc:
                state.update(status='blocked', error=str(exc))
                save(state)
                raise


if __name__ == '__main__':
    main()
