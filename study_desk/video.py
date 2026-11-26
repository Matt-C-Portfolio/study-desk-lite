"""Caption-first video acquisition. Does not call the language model or graph."""

import html
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.parse import parse_qs, urlsplit

from . import config


def fetch_metadata(url, folder):
    from yt_dlp import YoutubeDL

    with YoutubeDL(
        {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'skip_download': True,
            'socket_timeout': 30,
            'retries': 2,
        }
    ) as downloader:
        info = downloader.extract_info(url, download=False)
    if info.get('is_live'):
        raise ValueError('This lecture is still live. Process it after the recording is available.')
    fields = (
        'id',
        'title',
        'description',
        'channel',
        'channel_id',
        'channel_url',
        'uploader',
        'duration',
        'upload_date',
        'view_count',
        'like_count',
        'license',
        'categories',
        'tags',
        'chapters',
        'language',
        'thumbnail',
        'webpage_url',
    )
    metadata = {key: info.get(key) for key in fields}
    from .licensing import lecture_license

    metadata['content_license'] = lecture_license(url)
    metadata['source_url'] = url
    metadata['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    thumbnail = metadata.get('thumbnail')
    if thumbnail:
        host = urlsplit(thumbnail).hostname or ''
        if urlsplit(thumbnail).scheme == 'https' and (
            host == 'ytimg.com' or host.endswith('.ytimg.com')
        ):
            try:
                with urlopen(thumbnail, timeout=30) as response:
                    content = response.read(5 * 1024 * 1024 + 1)
                    mime = response.headers.get_content_type()
                if len(content) <= 5 * 1024 * 1024 and mime in {
                    'image/jpeg',
                    'image/png',
                    'image/webp',
                }:
                    (folder / 'thumbnail.image').write_bytes(content)
                    metadata['thumbnail_mime'] = mime
                else:
                    metadata['thumbnail_warning'] = 'Thumbnail format or size was unsupported.'
            except OSError:
                metadata['thumbnail_warning'] = 'Thumbnail download failed; source URL retained.'
    (folder / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    return metadata


def fetch_captions(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
    from requests import Session

    class TimedSession(Session):
        def request(self, *args, **kwargs):
            kwargs.setdefault('timeout', 30)
            return super().request(*args, **kwargs)

    # Blocked requests and network errors are errors, not proof captions are absent.
    with TimedSession() as session:
        try:
            tracks = list(YouTubeTranscriptApi(http_client=session).list(video_id))
        except TranscriptsDisabled:
            return None
        if not tracks:
            return None
        tracks.sort(key=lambda t: (not t.language_code.lower().startswith('en'), t.is_generated))
        track = tracks[0]
        segments = [
            {
                'start': s['start'],
                'end': s['start'] + s['duration'],
                'text': html.unescape(s['text']).strip(),
            }
            for s in track.fetch().to_raw_data()
        ]
        segments = [s for s in segments if s['text']]
        if not segments:
            raise ValueError('The caption track was empty. Please retry; no audio was downloaded.')
        return {
            'segments': segments,
            'language': track.language_code,
            'method': 'automatic captions' if track.is_generated else 'manual captions',
        }


def download_audio(url, folder, progress):
    from yt_dlp import YoutubeDL

    last_percent = [-1]

    def hook(event):
        total = event.get('total_bytes') or event.get('total_bytes_estimate')
        if event.get('status') == 'downloading' and total:
            percent = int(event.get('downloaded_bytes', 0) * 100 / total)
            if percent // 10 != last_percent[0] // 10:
                last_percent[0] = percent
                progress('downloading', f'No captions available. Downloading audio: {percent}%')

    options = {
        'format': 'bestaudio/best',
        'outtmpl': str(folder / 'audio.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 2,
        'progress_hooks': [hook],
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        path = Path(downloader.prepare_filename(info))
        if not path.is_file():
            raise ValueError('Audio download did not produce a file.')
        return path


def local_transcribe(audio, folder, progress):
    output = folder / 'transcript.txt'
    # A previous successful child can be reused after interruption before DB update.
    metadata = output.with_suffix('.segments.json')
    if output.is_file() and metadata.is_file():
        return json.loads(metadata.read_text(encoding='utf-8'))
    # Keep incomplete attempts rather than overwriting their evidence.
    for path in (output, metadata):
        if path.exists():
            import time

            path.rename(path.with_name(path.name + f'.partial-{time.time_ns()}'))
    command = [
        sys.executable,
        '-u',
        '-m',
        'study_desk',
        'transcribe',
        str(audio),
        '--output',
        str(output),
        '--device',
        'cuda',
    ]
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    with subprocess.Popen(
        command,
        cwd=config.ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        **kwargs,
    ) as child:
        tail = []
        for line in child.stdout:
            line = line.strip()
            tail.append(line)
            tail = tail[-10:]
            if line.startswith(('Loading local', 'Transcription progress:')):
                progress('transcribing', line)
        if child.wait() != 0:
            raise RuntimeError(
                'Local transcription failed. Stop other GPU jobs and retry. '
                + ' '.join(tail)[-600:]
            )
    return json.loads(metadata.read_text(encoding='utf-8'))


def process_video(url, folder, progress, save_metadata=lambda metadata: None, mode='check'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    video_id = parse_qs(urlsplit(url).query)['v'][0]
    if mode == 'check':
        progress('checking', 'Saving lecture details and thumbnail…')
        save_metadata(fetch_metadata(url, folder))
        progress('checking', 'Checking available captions…')
        result = fetch_captions(video_id)
        if result is None:
            return None, None
        folder = folder / 'captions'
        folder.mkdir(exist_ok=True)
    elif mode == 'local':
        folder = folder / 'local'
        folder.mkdir(exist_ok=True)
        progress('downloading', 'Downloading audio for your local transcription…')
        audio = download_audio(url, folder, progress)
        progress('transcribing', 'Transcribing locally with Faster-Whisper…')
        result = local_transcribe(audio, folder, progress)
        result['method'] = 'Faster-Whisper large-v3'
    else:
        raise ValueError('Unknown transcript action.')
    if not result.get('segments'):
        raise ValueError('No speech or captions were found.')
    result['source_url'] = url
    output = folder / 'transcript.txt'
    output.write_text('\n'.join(s['text'] for s in result['segments']) + '\n', encoding='utf-8')
    output.with_suffix('.segments.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    return output, result['method']
