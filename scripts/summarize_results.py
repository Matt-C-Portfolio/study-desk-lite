"""Rebuild descriptive Q&A tables from saved attempts, without inference or APIs."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    'question_id',
    'category',
    'model',
    'mode',
    'status',
    'elapsed',
    'retrieval_seconds',
    'generation_seconds',
    'estimated_cost_usd',
    'answer_words',
    'graph_build_id',
    'answer_version',
]


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--export-from',
        type=Path,
        help='Optional original qa-full-v1/manifest.json; exports only the listed metric fields',
    )
    parser.add_argument('--input', type=Path, default=ROOT / 'evaluation/results/qa-attempts.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'evaluation/results')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.export_from:
        raw = args.export_from.read_bytes()
        manifest = json.loads(raw)
        rows = [{key: row.get(key) for key in FIELDS} for row in manifest['attempts']]
        write_csv(args.output / 'qa-attempts.csv', FIELDS, rows)
        provenance = {
            key: manifest.get(key)
            for key in [
                'status',
                'started_at',
                'local_seed',
                'openai_seed',
                'api_workers',
                'notes',
                'pipeline_hashes',
            ]
        }
        provenance.update(
            source='data/experiments/qa-full-v1/manifest.json',
            source_sha256=hashlib.sha256(raw).hexdigest(),
            attempts=len(rows),
            questions=len(manifest['questions']),
        )
        (args.output / 'provenance.json').write_text(
            json.dumps(provenance, indent=2) + '\n', encoding='utf-8'
        )
    else:
        with args.input.open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
    seen = set()
    groups = defaultdict(list)
    for row in rows:
        key = (row['question_id'], row['model'], row['mode'])
        if key in seen or row['status'] not in {'complete', 'error'}:
            raise ValueError(
                'Expected distinct terminal attempts; do not silently drop duplicates or unfinished runs.'
            )
        seen.add(key)
        groups[row['model'], row['mode']].append(row)
        groups[row['model'], 'all'].append(row)
    summaries = []
    for (model, mode), attempts in sorted(groups.items()):
        completed = [row for row in attempts if row['status'] == 'complete']
        durations = [
            float(row['elapsed']) for row in completed if row.get('elapsed') not in (None, '')
        ]
        costs = [
            float(row['estimated_cost_usd'])
            for row in attempts
            if row.get('estimated_cost_usd') not in (None, '')
        ]
        summaries.append(
            dict(
                model=model,
                mode=mode,
                attempted=len(attempts),
                completed=len(completed),
                failed=len(attempts) - len(completed),
                failure_percent=round(100 * (len(attempts) - len(completed)) / len(attempts), 3),
                timed_completions=len(durations),
                median_completed_seconds=(
                    round(statistics.median(durations), 3) if durations else ''
                ),
                estimated_api_cost_usd=round(sum(costs), 8),
                missing_api_cost=(
                    sum(row.get('estimated_cost_usd') in (None, '') for row in attempts)
                    if model == 'openai'
                    else 0
                ),
            )
        )
    write_csv(args.output / 'qa-summary.csv', list(summaries[0]), summaries)
    print(
        f'Summarized {len(rows)} attempts into {len(summaries)} rows: {args.output / "qa-summary.csv"}'
    )


if __name__ == '__main__':
    main()
