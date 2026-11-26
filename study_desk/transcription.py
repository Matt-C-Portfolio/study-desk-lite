"""Local audio/video transcription. No URL fetching or graph dependencies."""

import json
import os
from pathlib import Path
import sys


def progress_line(end, duration):
    # Completion is reported only after transcript files have been saved.
    percent = min(99.9, max(0.0, end / duration * 100)) if duration > 0 else 0.0
    return f'Transcription progress: {percent:.2f}% ({min(end, duration):.1f}s / {duration:.1f}s)'


def transcribe(source, model_path, output, device='cpu', language=None):
    source, model_path, output = Path(source).resolve(), Path(model_path), Path(output).resolve()
    metadata_path = output.with_suffix('.segments.json')
    if not source.is_file():
        raise ValueError(f'Media file not found: {source}')
    if not (model_path / 'model.bin').is_file():
        raise ValueError(f'Local Whisper model missing: {model_path}')
    if output.exists() or metadata_path.exists():
        raise ValueError('Output already exists. Choose a different --output path.')
    # No implicit model downloads, including on an offline first run.
    os.environ['HF_HUB_OFFLINE'] = '1'
    dll_handles = []
    if os.name == 'nt' and device == 'cuda':
        packages = Path(sys.prefix) / 'Lib' / 'site-packages' / 'nvidia'
        for folder in packages.glob('*/bin'):
            dll_handles.append(os.add_dll_directory(str(folder)))
            os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
    from faster_whisper import WhisperModel

    print(f'Loading local Whisper large-v3 on {device}...', flush=True)
    model = WhisperModel(
        str(model_path),
        device=device,
        compute_type='float16' if device == 'cuda' else 'int8',
        local_files_only=True,
    )
    try:
        segments, info = model.transcribe(str(source), language=language, beam_size=5)
        print(progress_line(0, info.duration), flush=True)
        records = []
        for segment in segments:
            records.append(
                {'start': segment.start, 'end': segment.end, 'text': segment.text.strip()}
            )
            print(progress_line(segment.end, info.duration), flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('\n'.join(s['text'] for s in records) + '\n', encoding='utf-8')
        metadata_path.write_text(
            json.dumps(
                {
                    'source': str(source),
                    'model': 'large-v3',
                    'language': info.language,
                    'duration': info.duration,
                    'segments': records,
                },
                indent=2,
            ),
            encoding='utf-8',
        )
        print('Transcription progress: 100.00% — transcript saved', flush=True)
        print(f'Saved transcript: {output}\nSaved timestamps: {metadata_path}')
    finally:
        del model
