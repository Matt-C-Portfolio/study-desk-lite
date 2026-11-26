"""One isolated OpenAI baseline; credentials come only from the environment."""

import hashlib, json, os, time
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from study_desk import config
from study_desk.study_pipeline import prepare, run, PASSES, VERSION
from study_desk.model import ModelOutputError
from study_desk.lecture_contracts import FORMAT_VERSION

PRICES = {'gpt-5.6-luna': (0.20, 0.02, 1.20), 'gpt-5.6-terra': (2.0, 0.20, 12.0)}
MODELS = ['gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-terra', 'gpt-5.6-luna']


def main():
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('Set OPENAI_API_KEY in the environment; never put it in this script.')
    videos = json.load(urlopen('http://127.0.0.1:8788/api/urls'))
    video = next(v for v in videos if v['id'] == 1)
    folder = (
        config.ROOT
        / 'data'
        / 'experiments'
        / ('openai-baseline-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    )
    folder.mkdir(parents=True)

    def save(name, data):
        (folder / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    old = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (config.ROOT / 'data' / 'videos').rglob('*')
        if p.is_file()
    }
    digest, chunks = prepare(video['transcript_path'])
    source = Path(video['transcript_path']).read_text(encoding='utf-8')
    (folder / 'transcript.txt').write_text(source, encoding='utf-8')
    save(
        'settings.json',
        dict(
            models=dict(zip(PASSES, MODELS)),
            pipeline=VERSION,
            format_version=FORMAT_VERSION,
            digest=digest,
            transcript_sha256=hashlib.sha256(source.encode()).hexdigest(),
            video_url=video['url'],
            license=video['metadata'].get('content_license'),
            reasoning_effort='low',
            seed=None,
            temperature='API default',
            method='Lite four-pass workflow and prompts; normal app stage assignments; advisory review; no extra audit or repair passes.',
            prices_per_million=PRICES,
            pricing_sources=[
                'https://developers.openai.com/api/docs/models/gpt-5.6-luna',
                'https://developers.openai.com/api/docs/models/gpt-5.6-terra',
            ],
            pricing_checked='2026-10-27',
        ),
    )
    calls = []
    stage = [0]
    stage_starts = {}
    stage_ends = {}
    started = time.monotonic()

    def report(index, done, total, activity):
        stage[0] = index
        stage_starts.setdefault(index, time.monotonic())
        stage_ends[index] = time.monotonic()
        save(
            'progress.json',
            dict(
                stage=PASSES[index],
                done=done,
                total=total,
                elapsed=round(time.monotonic() - started, 2),
            ),
        )
        print(f'{PASSES[index]} {done}/{total}', flush=True)

    class APIModel:
        def complete(self, prompt, on_token=None, json_mode=False, max_tokens=6000):
            index = stage[0]
            model = MODELS[index]
            number = len(calls) + 1
            payload = dict(
                model=model,
                input=prompt,
                reasoning={'effort': 'low'},
                store=False,
                max_output_tokens=max_tokens,
                prompt_cache_options={'mode': 'explicit'},
                text={
                    'format': {
                        'type': 'json_schema',
                        'name': 'study_pass',
                        'strict': True,
                        'schema': json_mode,
                    }
                },
            )
            save(f'call-{number:03d}-request.json', payload)
            req = Request(
                'https://api.openai.com/v1/responses',
                data=json.dumps(payload).encode(),
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
            )
            t = time.monotonic()
            with urlopen(req, timeout=600) as response:
                data = json.load(response)
            seconds = time.monotonic() - t
            save(f'call-{number:03d}-response.json', data)
            usage = data.get('usage', {})
            inp = usage.get('input_tokens', 0)
            out = usage.get('output_tokens', 0)
            details = usage.get('input_tokens_details', {})
            cached = details.get('cached_tokens', 0)
            a, b, c = PRICES[model]
            cost = ((inp - cached) * a + cached * b + out * c) / 1e6
            entry = dict(
                stage=PASSES[index],
                model=model,
                seconds=round(seconds, 3),
                usage=usage,
                estimated_cost_usd=cost,
                status=data.get('status'),
            )
            calls.append(entry)
            save('usage.json', calls)
            self.request_info = entry
            answer = ''.join(
                part.get('text', '')
                for item in data.get('output', [])
                if item.get('type') == 'message'
                for part in item.get('content', [])
                if part.get('type') == 'output_text'
            )
            if data.get('status') != 'completed':
                raise ModelOutputError(
                    'API response incomplete: ' + str(data.get('incomplete_details')), answer
                )
            if not answer:
                raise ModelOutputError('API returned no final text', answer)
            return answer

    result = {}
    print(folder, flush=True)
    try:
        output = run(APIModel(), chunks, folder, report)
        baseline = Path(video['run_history']['14B'][0]['folder']) / 'notes.md'
        credit = baseline.read_text(encoding='utf-8').partition('<!-- ocw-attribution -->')[2]
        if credit:
            with (folder / 'notes.md').open('a', encoding='utf-8') as f:
                f.write('\n\n<!-- ocw-attribution -->' + credit)
        result.update(
            status='complete', words=len((folder / 'notes.md').read_text(encoding='utf-8').split())
        )
    except Exception as exc:
        result.update(status='error', error=str(exc).replace(key, '[REDACTED]'))
    finally:
        result.update(
            total_seconds=round(time.monotonic() - started, 3),
            estimated_cost_usd=sum(c['estimated_cost_usd'] for c in calls),
            calls=len(calls),
            stage_timings_seconds={
                PASSES[i]: round(stage_ends[i] - t, 3) for i, t in stage_starts.items()
            },
            stage_api_seconds={
                name: round(sum(c['seconds'] for c in calls if c['stage'] == name), 3)
                for name in PASSES
            },
            old_outputs_unchanged=all(
                p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == h
                for p, h in old.items()
            ),
        )
        save('result.json', result)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
