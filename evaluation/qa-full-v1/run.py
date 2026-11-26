"""Run the frozen full question bank through the app API; never retry terminal attempts."""

import json, time, hashlib, shutil, urllib.request, datetime, html, msvcrt, sys, threading
from types import SimpleNamespace
from pathlib import Path

BASE = 'http://127.0.0.1:8788'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from study_desk import answers, config

OUT = ROOT / 'data/experiments/qa-full-v1'
OUT.mkdir(parents=True, exist_ok=True)
MANIFEST = OUT / 'manifest.json'
lock = (OUT / 'runner.lock').open('a+b')
lock.seek(0)
lock.write(b'0')
lock.flush()
lock.seek(0)
msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path, timeout=30))


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hashes():
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / 'study_desk').rglob('*'))
        if p.is_file() and p.suffix == '.py'
    }


if MANIFEST.exists():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    questions = manifest['questions']
    frozen = {k: v for k, v in manifest['pipeline_hashes'].items() if Path(k).suffix == '.py'}
else:
    bank = json.loads(
        (ROOT / 'evaluation/question-bank-v1/questions.json').read_text(encoding='utf-8')
    )
    questions = bank['questions']
    frozen = hashes()
    assert len(questions) == 120 and len({q['id'] for q in questions}) == 120
    manifest = dict(
        started_at=stamp(),
        status='running',
        questions=questions,
        pipeline_hashes=frozen,
        local_seed=42,
        openai_seed=None,
        api_workers=7,
        attempts=[],
        notes='Frozen full evaluation: 120 questions, four models, four modes. Up to six passages in retrieval modes; 3000 output tokens. Local seed 42; API unseeded. Local execution sequential; OpenAI up to seven concurrent workers. Parallel timings include shared CPU contention. No automatic retries of failures. Answer key is never supplied to models. API costs are estimates; local hardware/electricity not measured.',
    )
    for model in ['1.5B', '7B', '14B', 'openai']:
        g = get('/api/graph/' + model)
        save(OUT / ('graph-' + model + '-snapshot.json'), g)
        for q in questions:
            for mode in ['plain', 'rag', 'graph_only', 'graph']:
                manifest['attempts'].append(
                    dict(
                        question_id=q['id'],
                        category=q['category'],
                        model=model,
                        mode=mode,
                        status='pending',
                    )
                )
    save(MANIFEST, manifest)


def report():
    from comparison_snapshot import publish

    try:
        publish(ROOT, manifest)
    except (OSError, ValueError) as exc:
        print('Comparison snapshot deferred:', str(exc), flush=True)
    totals = {}
    for model in ['1.5B', '7B', '14B', 'openai']:
        rows = [a for a in manifest['attempts'] if a['model'] == model]
        done = [a for a in rows if a['status'] in ['complete', 'error']]
        totals[model] = dict(
            completed=sum(a['status'] == 'complete' for a in rows),
            failed=sum(a['status'] == 'error' for a in rows),
            finished=len(done),
            total_seconds=round(sum(a.get('elapsed', 0) for a in done), 2),
            estimated_api_cost_usd=sum(a.get('estimated_cost_usd') or 0 for a in done),
            cost_missing=sum(
                a['model'] == 'openai' and a.get('estimated_cost_usd') is None for a in done
            ),
        )
    save(OUT / 'summary.json', dict(updated_at=stamp(), status=manifest['status'], models=totals))
    rows = manifest['attempts']
    done = sum(a['status'] in ('complete', 'error') for a in rows)
    table = ''.join(
        '<tr><td>'
        + html.escape(model)
        + '</td><td>'
        + str(t['completed'])
        + '</td><td>'
        + str(t['failed'])
        + '</td><td>'
        + str(t['total_seconds'])
        + '</td><td>$'
        + format(t['estimated_api_cost_usd'], '.4f')
        + '</td></tr>'
        for model, t in totals.items()
    )
    active = ''.join(
        '<p>' + html.escape(str(a)) + '</p>'
        for a in rows
        if a['status'] in ('submitting', 'running')
    )
    recent = ''.join(
        '<li><a href="http://127.0.0.1:8788/?answer='
        + a['job_id']
        + '#ask">'
        + html.escape(
            a['question_id'] + ' · ' + a['model'] + ' · ' + a['mode'] + ' · ' + a['status']
        )
        + '</a></li>'
        for a in rows
        if a['status'] in ('complete', 'error')
    )
    page = (
        '<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="15"><title>Full Q&A evaluation</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;background:#faf9f5;color:#132b49}table{border-collapse:collapse;width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid #ccd5dd}progress{width:100%}li{margin:8px 0}</style></head><body><h1>Full Q&A evaluation</h1><h2>'
        + str(done)
        + ' / '
        + str(len(rows))
        + ' attempts finished</h2><progress max="'
        + str(len(rows))
        + '" value="'
        + str(done)
        + '"></progress><p>'
        + html.escape(manifest['status'])
        + ' · Updated '
        + stamp()
        + '</p><p>'
        + html.escape(manifest.get('blocker', ''))
        + '</p>'
        + active
        + '<table><tr><th>Model</th><th>Completed</th><th>Failed</th><th>Recorded seconds</th><th>Estimated API cost</th></tr>'
        + table
        + '</table><p>120 questions · 4 models · 4 modes · local seed 42 · API unseeded. Failures count as results. Refreshes every 15 seconds.</p><h2>Saved answers</h2><ul>'
        + recent
        + '</ul></body></html>'
    )
    (OUT / 'progress.html').write_text(page, encoding='utf-8')


def finish(a, result):
    destination = OUT / 'runs' / f"{a['question_id']}-{a['model']}-{a['mode']}"
    shutil.copytree(ROOT / 'data/answers' / a['job_id'], destination, dirs_exist_ok=True)
    a.update(
        {
            k: result.get(k)
            for k in [
                'status',
                'elapsed',
                'retrieval_seconds',
                'generation_seconds',
                'estimated_cost_usd',
                'error',
                'citation_warnings',
                'answer_version',
                'graph_build_id',
            ]
        }
    )
    a.update(
        finished_at=stamp(),
        result_path=str(destination.relative_to(ROOT)),
        answer_words=len(result.get('answer', '').split()),
    )
    save(MANIFEST, manifest)
    report()
    print(a['model'], a['question_id'], a['mode'], a['status'], flush=True)


report()
processors = {}
try:
    if any(a['status'] == 'submitting' for a in manifest['attempts']):
        raise RuntimeError('Uncertain submission: reconcile existing app answers before resuming.')
    if any(a['status'] == 'running' and a['model'] == 'openai' for a in manifest['attempts']):
        raise RuntimeError('Reconcile interrupted API workers before resuming; no duplicate calls.')
    while True:
        rows = manifest['attempts']
        for a in rows:
            if a['status'] != 'running':
                continue
            proc = processors.get(a['job_id'])
            if proc is not None and proc.active:
                continue
            result = get('/api/answers/' + a['job_id'])
            if result['status'] in ('running', 'queued'):
                continue
            if a['model'] != 'openai' and get('/api/workspace-status')['busy']:
                continue
            finish(a, result)
        if all(a['status'] in ('complete', 'error') for a in rows):
            break
        if hashes() != frozen:
            raise RuntimeError('Pipeline files changed. Stopping new submissions.')
        local_active = any(a['status'] == 'running' and a['model'] != 'openai' for a in rows)
        api_active = sum(a['status'] == 'running' and a['model'] == 'openai' for a in rows)
        pending = []
        if not local_active and not get('/api/workspace-status')['busy']:
            local = next(
                (a for a in rows if a['status'] == 'pending' and a['model'] != 'openai'), None
            )
            if local:
                pending.append(local)
        pending.extend(
            [a for a in rows if a['status'] == 'pending' and a['model'] == 'openai'][
                : max(0, 7 - api_active)
            ]
        )
        for a in pending:
            q = next(q for q in questions if q['id'] == a['question_id'])
            a.update(
                status='submitting',
                submitted_at=stamp(),
                worker_limit=7 if a['model'] == 'openai' else 1,
            )
            save(MANIFEST, manifest)
            payload = dict(question=q['question'], model=a['model'], mode=a['mode'], seed=42)
            if a['model'] == 'openai':
                proc = SimpleNamespace(
                    database=config.DATABASE, lock=threading.Lock(), active=False
                )
                job = answers.start(proc, payload)
                processors[job] = proc
            else:
                req = urllib.request.Request(
                    BASE + '/api/answers',
                    data=json.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json'},
                )
                job = json.load(urllib.request.urlopen(req, timeout=30))['id']
            a.update(job_id=job, status='running')
            save(MANIFEST, manifest)
            report()
            print('START', a['model'], a['question_id'], a['mode'], job, flush=True)
        time.sleep(2)
    manifest.update(status='complete', finished_at=stamp())
    save(MANIFEST, manifest)
    report()
    print('FULL EVALUATION COMPLETE', flush=True)
except Exception as e:
    manifest.update(status='blocked', blocker=str(e), updated_at=stamp())
    save(MANIFEST, manifest)
    report()
    raise
