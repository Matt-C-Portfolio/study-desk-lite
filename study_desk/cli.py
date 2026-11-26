"""Start the lecture workspace or transcribe a local media file."""

import argparse
import sys

from . import config


def main():
    parser = argparse.ArgumentParser(description='Study Desk Lite — local lecture processing')
    sub = parser.add_subparsers(dest='command', required=True)
    ui = sub.add_parser('ui', help='Open the local lecture workspace')
    ui.add_argument('--port', type=int, default=8788)
    transcribe = sub.add_parser('transcribe', help='Transcribe a local audio/video file')
    transcribe.add_argument('file')
    transcribe.add_argument('--output', required=True, help='New .txt output path')
    transcribe.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    transcribe.add_argument('--language', default=None)
    args = parser.parse_args()
    try:
        if args.command == 'ui':
            from .ui import run

            run(config.DATABASE, args.port)
        else:
            from .transcription import transcribe

            transcribe(args.file, config.WHISPER_WEIGHTS, args.output, args.device, args.language)
    except KeyboardInterrupt:
        print('Stopped.', file=sys.stderr)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
