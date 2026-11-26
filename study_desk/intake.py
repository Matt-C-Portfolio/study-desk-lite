"""Validate a video URL without fetching anything from the network."""

import re
from urllib.parse import urlsplit, parse_qs


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Paste a valid YouTube video URL.')
    url = urlsplit(value.strip())
    if url.scheme not in {'http', 'https'} or url.username or url.password or url.port:
        raise ValueError('Use an http or https YouTube video URL.')
    host = (url.hostname or '').lower()
    parts = url.path.strip('/').split('/')
    video_id = ''
    if host in {'youtu.be', 'www.youtu.be'} and len(parts) == 1:
        video_id = parts[0]
    elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
        if url.path == '/watch':
            video_id = parse_qs(url.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in {'shorts', 'live', 'embed'}:
            video_id = parts[1]
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('Use a link to one YouTube video, rather than a channel or playlist.')
    return f'https://www.youtube.com/watch?v={video_id}'
