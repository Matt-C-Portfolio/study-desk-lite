"""Read-only installation checks; never start a model or submit an API request."""

import argparse
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['1.5B', '7B', '14B'], default='1.5B')
    parser.add_argument(
        '--database',
        action='store_true',
        help='Check connection and schema permissions without creating tables',
    )
    parser.add_argument(
        '--embeddings', action='store_true', help='Require BGE for graphs and retrieval'
    )
    parser.add_argument(
        '--whisper', action='store_true', help='Require optional local transcription weights'
    )
    parser.add_argument(
        '--verify-models',
        action='store_true',
        help='Hash selected weights; may take several minutes',
    )
    args = parser.parse_args()
    failures = []

    def check(ok, label, remedy=''):
        print(
            f"{'OK' if ok else 'MISSING'}: {label}" + (f' -- {remedy}' if not ok and remedy else '')
        )
        if not ok:
            failures.append(label)

    check(sys.version_info[:2] == (3, 11), 'Python 3.11 (tested version)')
    check(sys.platform == 'win32', 'Windows (supported local runtime)')
    for distribution, module in [
        ('faster-whisper', 'faster_whisper'),
        ('youtube-transcript-api', 'youtube_transcript_api'),
        ('yt-dlp', 'yt_dlp'),
        ('psycopg', 'psycopg'),
        ('onnxruntime', 'onnxruntime'),
        ('tokenizers', 'tokenizers'),
        ('numpy', 'numpy'),
        ('requests', 'requests'),
    ]:
        try:
            importlib.import_module(module)
            check(True, f'{distribution} {importlib.metadata.version(distribution)}')
        except (ImportError, OSError):
            check(False, distribution, 'Install requirements-windows.lock.txt; see docs/SETUP.md')

    def asset(relative, expected=None):
        path = ROOT / relative
        check(path.is_file(), relative, 'See docs/SETUP.md')
        if path.is_file() and expected and args.verify_models:
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            check(
                digest == expected,
                relative + ' SHA-256',
                'Use the pinned download in models/downloads.json',
            )

    asset('runtime/llama.cpp/llama-server.exe')
    model = next(
        m
        for m in json.loads((ROOT / 'models/manifest.json').read_text())
        if m['name'].endswith('-' + args.model)
    )
    asset('models/' + model['file'], model['sha256'])
    if args.embeddings:
        manifest = json.loads((ROOT / 'models/bge-base-en-v1.5/manifest.json').read_text())
        for item in manifest['files']:
            asset('models/bge-base-en-v1.5/' + item['file'], item['sha256'])
    if args.whisper:
        for name in [
            'model.bin',
            'config.json',
            'tokenizer.json',
            'vocabulary.json',
            'preprocessor_config.json',
        ]:
            asset('models/whisper/large-v3/' + name)
    if args.database:
        try:
            from study_desk import config
            import psycopg

            with psycopg.connect(config.DATABASE, connect_timeout=5) as conn:
                row = conn.execute(
                    "SELECT current_schema(), has_database_privilege(current_database(), 'CREATE'), has_schema_privilege(current_schema(), 'CREATE')"
                ).fetchone()
            check(bool(row[0]) and row[2], 'Database connection and schema CREATE permission')
            check(row[1], 'Database CREATE permission for isolated test schemas')
        except Exception as exc:
            # Database exceptions may contain connection parameters; do not print them.
            check(
                False,
                f'Database connection ({type(exc).__name__})',
                'See PostgreSQL setup; credentials are not printed',
            )
    print('\nNo downloads, generation, API calls, or database writes were performed.')
    print(
        'Setup checks passed.'
        if not failures
        else f'{len(failures)} setup check(s) need attention.'
    )
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
