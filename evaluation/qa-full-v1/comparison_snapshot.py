"""Publish read-only comparison JSON; answers stay in their original files."""

import json
import re
import time
from datetime import datetime, timezone

_cache = {}


def publish(root, manifest):
    rows = []
    for attempt in manifest['attempts']:
        row = {k: attempt.get(k) for k in ('question_id', 'model', 'mode', 'status', 'job_id')}
        if row['status'] in ('complete', 'error'):
            path = root / 'data/answers' / row['job_id'] / 'result.json'
            key = (str(path), path.stat().st_mtime_ns)
            if key not in _cache:
                data = json.loads(path.read_text(encoding='utf-8'))
                sources = data.get('sources', [])
                cited = {int(n) - 1 for n in re.findall(r'\[S(\d+)\]', data.get('answer', ''))}
                valid = [sources[i] for i in cited if 0 <= i < len(sources)]
                _cache[key] = dict(
                    words=len(
                        re.findall(
                            r"\b[\w]+(?:['’-][\w]+)*\b",
                            re.sub(r'\[S\d+\]', '', data.get('answer', '')),
                        )
                    ),
                    seconds=data.get('elapsed'),
                    cost=data.get('estimated_cost_usd'),
                    cited=len(valid),
                    videos=len({s['video_id'] for s in valid}),
                    graph_passages=sum(
                        str(s.get('retrieval', '')).startswith('graph') for s in sources
                    ),
                )
            row.update(_cache[key])
        rows.append(row)
    payload = json.dumps(
        dict(
            updated_at=datetime.now(timezone.utc).isoformat(),
            questions=manifest['questions'],
            rows=rows,
        ),
        ensure_ascii=False,
    ).replace('<', '\\u003c')
    destination = root / 'study_desk/web/data/answer-comparison-data.json'
    temporary = destination.with_suffix('.json.tmp')
    temporary.write_text(payload, encoding='utf-8')
    for attempt in range(21):
        try:
            temporary.replace(destination)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(0.1)
