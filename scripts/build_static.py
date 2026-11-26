"""Build the read-only GitHub Pages app from the bundled dataset (standard library only)."""

import argparse
from contextlib import ExitStack
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from study_desk.licensing import attributed_notes


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


class Archive:
    def __init__(self, folder, stack):
        self.manifest = json.loads((folder / 'manifest.json').read_bytes())
        for name, expected in self.manifest['files'].items():
            path = folder / name
            if path.resolve().parent != folder.resolve():
                raise ValueError('Invalid bundle member')
            with path.open('rb') as source:
                actual = hashlib.file_digest(source, 'sha256').hexdigest()
            if path.stat().st_size != expected['bytes'] or actual != expected['sha256']:
                raise ValueError(f'Dataset checksum mismatch: {name}')
        self.tables = json.loads(gzip.decompress((folder / self.manifest['database']).read_bytes()))
        self.files = {}
        for name in self.manifest['archives']:
            archive = stack.enter_context(ZipFile(folder / name))
            for info in archive.infolist():
                if info.filename in self.files:
                    raise ValueError(f'Duplicate artifact: {info.filename}')
                self.files[info.filename] = archive

    def rows(self, table):
        return self.tables[table]['rows']

    def read(self, name):
        return self.files[name].read(name)

    def text(self, name):
        return self.read(name).decode('utf-8').replace('\r\n', '\n')


def artifact_path(value):
    prefix = '@study-desk-data/'
    if not value.startswith(prefix):
        raise ValueError(f'Expected a portable database file reference: {value}')
    name = value[len(prefix) :]
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Invalid artifact path')
    return name


def library(archive):
    result = []
    processing = {r['video_id']: r for r in archive.rows('video_processing')}
    metadata = {r['video_id']: r['data'] for r in archive.rows('video_metadata')}
    captions = {r['video_id']: r['status'] for r in archive.rows('caption_checks')}
    for record in sorted(archive.rows('video_intake'), key=lambda r: r['id'], reverse=True):
        ident = record['id']
        video = dict(record, **{k: v for k, v in processing[ident].items() if k != 'video_id'})
        video.update(metadata=metadata[ident], caption_status=captions[ident])
        video['versions'] = {
            r['kind']: r for r in archive.rows('transcript_versions') if r['video_id'] == ident
        }
        history = {}
        for row in sorted(archive.rows('study_run_history'), key=lambda r: r['run_number']):
            if row['video_id'] == ident:
                history.setdefault(row['model'], []).append(dict(row['data']))
        for runs in history.values():
            first = next((r['run_number'] for r in runs if r['status'] == 'complete'), None)
            for run in runs:
                run['graph_selected'] = run['run_number'] == first
        video['run_history'] = history
        video['study_runs'] = {model: runs[-1] for model, runs in history.items()}
        result.append(video)
    return result


def baseline_guide():
    folder = ROOT / 'baseline'
    settings = json.loads((folder / 'settings.json').read_bytes())
    result = json.loads((folder / 'result.json').read_bytes())
    intro = (
        '# OpenAI mixed-model baseline\n\n'
        'MIT 6.00 — Lecture 1: Computer Science and Programming (Fall 2008).\n\n'
        'Same transcript and Lite four-pass workflow as the local runs. '
        'One API run using the normal Study Desk model assignments; no slides or code attachments. '
        'Saved result only—viewing this page makes no API calls.\n\n'
        f"**Total time:** {result['total_seconds'] / 60:.2f} minutes · "
        f"**Estimated API cost:** ${result['estimated_cost_usd']:.4f}\n\n"
        '| Stage | Model | Time |\n|---|---|---:|\n'
    )
    for stage, model in settings['models'].items():
        intro += f"| {stage} | {model} | {result['stage_timings_seconds'][stage]:.1f}s |\n"
    return (
        intro
        + (
            '\nCost is estimated from recorded token usage and published rates, not a billing receipt. '
            'Model output is preserved and may contain errors.\n\n---\n\n'
        )
        + (folder / 'notes.md').read_text(encoding='utf-8')
    )


def build(output, bundle):
    output = output.resolve()
    if output.exists() or output == ROOT or ROOT.is_relative_to(output):
        raise ValueError('Choose a new output directory. Existing files are never replaced.')
    web = ROOT / 'study_desk' / 'web'
    with ExitStack() as stack:
        archive = Archive(bundle, stack)
        videos = library(archive)
        # Keep the existing browser presentation; transform only the generated copy.
        shutil.copytree(web, output)
        routes = {}

        def write(route, name, content):
            target = output / 'snapshot' / name
            if not target.resolve().is_relative_to(output / 'snapshot'):
                raise ValueError('Static asset points outside the output directory')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encode(content) if isinstance(content, (list, dict)) else content)
            routes[route] = 'snapshot/' + name

        write('/api/urls', 'library.json', videos)
        write('/api/workspace-status', 'workspace.json', {'busy': False})
        write('/api/providers', 'providers.json', {'openai': True, 'static': True})
        for video in videos:
            ident = video['id']
            prefix = f'/api/urls/{ident}'
            base = f'videos/{ident}'
            write(
                prefix + '/transcript',
                base + '/transcript.txt',
                archive.read(artifact_path(video['transcript_path'])),
            )
            write(
                prefix + '/captions',
                base + '/captions.txt',
                archive.read(artifact_path(video['versions']['captions']['path'])),
            )
            extension = 'png' if video['metadata']['thumbnail_mime'] == 'image/png' else 'jpg'
            write(
                prefix + '/thumbnail',
                base + '/thumbnail.' + extension,
                archive.read(base + '/thumbnail.image'),
            )
            for model, runs in video['run_history'].items():
                for run in runs:
                    number = run['run_number']
                    if run.get('folder'):
                        folder = artifact_path(run['folder']) + '/'
                        files = {
                            name[len(folder) :]: archive.text(name)
                            for name in archive.files
                            if name.startswith(folder)
                            and '/' not in name[len(folder) :]
                            and (name.endswith('.json') or name.endswith('.response.txt'))
                        }
                        write(
                            f'{prefix}/results/{model}/{number}',
                            f'{base}/{model}/{number}/outputs.json',
                            {'run': run, 'files': files},
                        )
                    if run['status'] == 'complete':
                        notes = attributed_notes(archive.text(artifact_path(run['output'])), video)
                        write(
                            f'{prefix}/notes/{model}/{number}',
                            f'{base}/{model}/{number}/notes.md',
                            notes.encode('utf-8'),
                        )
                for kind in ('notes', 'results'):
                    numbered = f'{prefix}/{kind}/{model}/{runs[-1]["run_number"]}'
                    if numbered in routes:
                        routes[f'{prefix}/{kind}/{model}'] = routes[numbered]

        for model in ('1.5B', '7B', '14B', 'openai'):
            graph = json.loads(archive.read(f'experiments/qa-full-v1/graph-{model}-snapshot.json'))
            latest = max(r['id'] for r in archive.rows('graph_build') if r['model'] == model)
            if graph['build']['id'] != latest:
                raise ValueError(f'Graph snapshot is not the current recorded build: {model}')
            write('/api/graph/' + model, 'graphs/' + model + '.json', graph)
        answers = 0
        for name in archive.files:
            match = re.fullmatch(r'answers/([0-9a-f]{32})/result.json', name)
            if match:
                write('/api/answers/' + match[1], name, archive.read(name))
                answers += 1
        comparison = json.loads((web / 'data/answer-comparison-data.json').read_bytes())
        if any('/api/answers/' + row['job_id'] not in routes for row in comparison['rows']):
            raise ValueError('A comparison answer is missing from the dataset')
        write('/api/baseline', 'baseline.json', {'guide': baseline_guide()})
        report = {
            'lectures': len(videos),
            'guide_attempts': sum(
                len(v['run_history'][m]) for v in videos for m in v['run_history']
            ),
            'graphs': 4,
            'comparison_answers': len(comparison['rows']),
            'saved_answers': answers,
            'dataset_manifest_sha256': hashlib.sha256(
                (bundle / 'manifest.json').read_bytes()
            ).hexdigest(),
        }
        (output / 'snapshot/routes.json').write_bytes(encode(routes))
        # A classic script keeps the route table available before any application request.
        (output / 'snapshot-routes.js').write_text(
            'window.STUDY_DESK_ROUTES=' + encode(routes).decode('utf-8') + ';\n', encoding='utf-8'
        )
        (output / 'snapshot/build.json').write_bytes(encode(report))
        for name in ('static.js', 'static.css'):
            shutil.copy2(ROOT / 'scripts/static' / name, output / name)
        for path in output.glob('*.js'):
            if path.name not in ('app.js', 'study.js', 'graph.js', 'ask.js'):
                continue
            text = path.read_text(encoding='utf-8')
            # Downloads and images bypass fetch, so point these assignments at real files.
            text = re.sub(r'(\.\s*(?:href|src)\s*=\s*)([^;]+);', r'\1window.staticUrl(\2);', text)
            # A completed local queue is not a request to start work in this read-only app.
            if path.name == 'ask.js':
                text = text.replace(
                    'const stored = JSON.parse(localStorage.getItem(storageKey));',
                    'const stored = null;',
                )
            path.write_text(text, encoding='utf-8')
        page = (output / 'index.html').read_text(encoding='utf-8')
        page = re.sub(r'((?:src|href)=["\'])/(?!/)', r'\1./', page)
        page = page.replace(
            '<title>Study Desk Lite</title>', '<title>Study Desk Lite · Project demo</title>'
        )
        page = page.replace(
            '</head>',
            '<link rel="stylesheet" href="./static.css" />\n<script src="./snapshot-routes.js"></script>\n<script src="./static.js"></script>\n</head>',
        )
        page = page.replace(
            '<main class="main">',
            '<main class="main"><aside class="static-banner" aria-label="Project demo"><strong>Study Desk Lite · Recorded project</strong><p>Explore ten lectures, saved study guides, concept graphs, and 1,920 answer attempts. No setup or API key needed. New generation is available in the local app.</p><nav aria-label="Project resources"><a href="#comparison">Model comparison</a><a href="#answer-comparison">Answer comparison</a><a href="https://github.com/Matt-C-Portfolio/study-desk-lite">Source &amp; setup</a><a href="./results/qa-summary.csv" download>Download results</a></nav></aside>',
        )
        page = (
            page.replace('Lite workspace', 'Recorded project')
            .replace(
                'On this computer<small>Local workspace</small>',
                'Saved experiment<small>Read-only demo</small>',
            )
            .replace('Stored locally</span>', 'Saved results</span>')
        )
        page = page.replace('Video intake</a>', 'Saved guide runs</a>').replace(
            'Ask Study Desk</a>', 'Saved answer</a>'
        )
        page = page.replace('Generate study materials', 'Saved study materials')
        page = page.replace(
            'Turn your selected transcript into source-backed study notes.',
            'Choose a lecture and browse its saved runs below.',
        )
        (output / 'index.html').write_text(page, encoding='utf-8')
        css = (
            (output / 'styles.css')
            .read_text(encoding='utf-8')
            .replace("url('/", "url('./")
            .replace('url("/', 'url("./')
        )
        (output / 'styles.css').write_text(css, encoding='utf-8')
        shutil.copytree(ROOT / 'evaluation/results', output / 'results')
        shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.md', output / 'THIRD_PARTY_NOTICES.md')
        (output / '.nojekyll').touch()
    report['files'] = sum(p.is_file() for p in output.rglob('*'))
    report['bytes'] = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'site')
    parser.add_argument('--bundle', type=Path, default=ROOT / 'evaluation/dataset')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output, args.bundle), indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Static build failed: {exc}\n')


if __name__ == '__main__':
    main()
