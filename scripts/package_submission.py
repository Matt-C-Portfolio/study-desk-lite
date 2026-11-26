"""Copy an explicit set of submission files into a NEW directory. No Git writes."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TREES = ('study_desk', 'tests', 'scripts', 'docs', 'evaluation', 'baseline', '.github')
FILES = (
    '.gitattributes',
    '.gitignore',
    'README.md',
    'THIRD_PARTY_NOTICES.md',
    'requirements.txt',
    'requirements-cuda.txt',
    'requirements-windows.lock.txt',
    'study-desk.cmd',
    'lecture-presets.json',
    'evaluation/dataset/manifest.json',
    'models/manifest.json',
    'models/downloads.json',
    'models/bge-base-en-v1.5/manifest.json',
    'models/bge-base-en-v1.5/LICENSE',
    'models/bge-base-en-v1.5/tokenizer.json',
    'runtime/manifest.json',
)
EXCLUDED = {'__pycache__', '.cache', '.venv', '.git', '.pytest_cache'}
SUFFIXES = {'.pyc', '.log', '.key', '.gguf', '.onnx', '.bin', '.exe', '.dll', '.tmp', '.lock'}


def selected_files():
    # A source-only copy would leave the saved library and comparison links empty.
    bundle = ROOT / 'evaluation' / 'dataset'
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = bundle / name
        if path.resolve().parent != bundle.resolve() or not path.is_file():
            raise ValueError(f'Required dataset archive missing or outside bundle: {name}')
        if (
            path.stat().st_size != expected['bytes']
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']
        ):
            raise ValueError(f'Dataset archive checksum mismatch: {name}')
    paths = [ROOT / name for name in FILES]
    paths.extend(path for name in TREES for path in (ROOT / name).rglob('*') if path.is_file())
    selected = []
    for path in sorted(set(paths)):
        if not path.is_file():
            raise ValueError(f'Required submission file missing: {path.relative_to(ROOT)}')
        relative = path.relative_to(ROOT)
        if (
            EXCLUDED.intersection(relative.parts)
            or path.suffix in SUFFIXES
            or path.name.startswith('.env')
        ):
            continue
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError(f'File points outside the project: {relative}')
        if path.stat().st_size > 20_000_000:
            raise ValueError(f'Unexpected large file: {relative}')
        selected.append(path)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--output', type=Path, help='New destination directory; omit to list the package'
    )
    args = parser.parse_args()
    try:
        paths = selected_files()
        size = sum(p.stat().st_size for p in paths)
        if args.output is None:
            for path in paths:
                print(path.relative_to(ROOT).as_posix())
        else:
            destination = args.output.resolve()
            if destination.exists() or destination.is_relative_to(ROOT):
                raise ValueError(
                    'Choose a new directory outside the source project. Existing directories are never replaced.'
                )
            destination.mkdir(parents=True)
            manifest = {}
            for source in paths:
                relative = source.relative_to(ROOT)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                manifest[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
            (destination / 'submission-manifest.json').write_text(
                json.dumps(manifest, indent=2) + '\n', encoding='utf-8'
            )
            print(f'Created {destination}')
        print(
            f'{len(paths)} files; {size / 1_000_000:.2f} MB uncompressed. Source files unchanged.'
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Package error: {exc}\n')


if __name__ == '__main__':
    main()
