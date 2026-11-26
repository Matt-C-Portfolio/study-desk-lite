"""Local HTTP adapter. Video work is delegated to the background processor."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

import psycopg

import re

from .storage import Store
from . import config
from .intake import normalize_url

PAGE = Path(__file__).with_name('web') / 'index.html'


def make_server(database, port=8788):
    from .processing import Processor

    processor = Processor(database)

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, mime='application/json'):
            data = (
                body
                if isinstance(body, bytes)
                else (
                    body.encode('utf-8')
                    if isinstance(body, str)
                    else json.dumps(body).encode('utf-8')
                )
            )
            self.send_response(status)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header(
                'Content-Security-Policy',
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-src https://www.youtube-nocookie.com; frame-ancestors 'none'; base-uri 'none'",
            )
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            port = self.server.server_port
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            return self.headers.get('Host') in hosts and self.headers.get('Origin') in {
                None,
                *(f'http://{host}' for host in hosts),
            }

        def do_GET(self):
            if not self.allowed():
                return self.respond(403, {'error': 'Local requests only.'})
            answer_match = re.fullmatch(r'/api/answers/([0-9a-f]{32})', self.path)
            if answer_match:
                from .answers import read

                try:
                    return self.respond(200, read(answer_match[1]))
                except ValueError as exc:
                    return self.respond(404, {'error': str(exc)})
            if self.path == '/api/providers':
                from .openai_model import api_key

                return self.respond(200, {'openai': bool(api_key())})
            if self.path == '/api/workspace-status':
                return self.respond(200, {'busy': processor.active})
            if self.path == '/api/baseline':
                folder = PAGE.parents[2] / 'baseline'
                if not (folder / 'notes.md').is_file():
                    return self.respond(200, {'guide': None})
                settings = json.loads((folder / 'settings.json').read_text(encoding='utf-8'))
                result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
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
                    intro += (
                        f"| {stage} | {model} | {result['stage_timings_seconds'][stage]:.1f}s |\n"
                    )
                intro += (
                    '\nCost is estimated from recorded token usage and published rates, not a billing receipt. '
                    'Model output is preserved and may contain errors.\n\n---\n\n'
                )
                return self.respond(
                    200, {'guide': intro + (folder / 'notes.md').read_text(encoding='utf-8')}
                )
            if self.path.split('?', 1)[0] == '/':
                return self.respond(200, PAGE.read_text(encoding='utf-8'), 'text/html')
            if self.path in ('/data/comparison-cohort.json', '/data/answer-comparison-data.json'):
                try:
                    data = (PAGE.parent / self.path[1:]).read_bytes()
                except OSError:
                    return self.respond(404, {'error': 'Comparison data unavailable.'})
                return self.respond(200, data)
            if self.path == '/unc-interlocking-nc.png':
                return self.respond(
                    200, (PAGE.parent / 'unc-interlocking-nc.png').read_bytes(), 'image/png'
                )
            if re.fullmatch(
                r'/vendor/katex/(katex\.min\.(js|css)|fonts/[A-Za-z0-9_-]+\.(woff2?|ttf))',
                self.path,
            ):
                asset = PAGE.parent / self.path[1:]
                if not asset.is_file():
                    return self.respond(404, {'error': 'Asset missing.'})
                mime = {
                    '.js': 'text/javascript',
                    '.css': 'text/css',
                    '.woff2': 'font/woff2',
                    '.woff': 'font/woff',
                    '.ttf': 'font/ttf',
                }[asset.suffix]
                return self.respond(200, asset.read_bytes(), mime)
            assets = {
                '/ask.js': 'text/javascript',
                '/graph.js': 'text/javascript',
                '/study.js': 'text/javascript',
                '/app.js': 'text/javascript',
                '/styles.css': 'text/css',
                '/vendor/marked.js': 'text/javascript',
                '/vendor/purify.js': 'text/javascript',
            }
            if self.path in assets:
                return self.respond(
                    200,
                    (PAGE.parent / self.path[1:]).read_text(encoding='utf-8'),
                    assets[self.path],
                )
            match = re.fullmatch(r'/api/graph/(1\.5B|7B|14B|openai)', self.path)
            if match:
                from .graph_store import read_graph

                store = Store(database)
                try:
                    return self.respond(200, read_graph(store, match[1]))
                finally:
                    store.close()
            if self.path == '/api/urls':
                store = Store(database)
                try:
                    videos = store.urls()
                    for video in videos:
                        video['study_runs'] = store.runs(video['id'])
                        video['run_history'] = store.history(video['id'])
                    return self.respond(200, videos)
                finally:
                    store.close()
            match = re.fullmatch(
                r'/api/urls/(\d+)/results/(1\.5B|7B|14B|openai)(?:/(\d+))?', self.path
            )
            if match:
                store = Store(database)
                try:
                    record = store.run_record(int(match[1]), match[2], match[3])
                    if not record.get('folder'):
                        return self.respond(404, {'error': 'No saved pass outputs yet.'})
                    folder = Path(record['folder'])
                    files = {
                        path.name: path.read_text(encoding='utf-8')
                        for path in folder.iterdir()
                        if path.suffix == '.json' or path.name.endswith('.response.txt')
                    }
                    return self.respond(200, {'run': record, 'files': files})
                except OSError:
                    return self.respond(404, {'error': 'Pass outputs unavailable.'})
                finally:
                    store.close()
            match = re.fullmatch(
                r'/api/urls/(\d+)/notes/(1\.5B|7B|14B|openai)(?:/(\d+))?', self.path
            )
            if match:
                store = Store(database)
                try:
                    record = store.run_record(int(match[1]), match[2], match[3])
                    if record.get('status') != 'complete':
                        return self.respond(404, {'error': 'Study notes are not ready.'})
                    from .licensing import attributed_notes

                    text = attributed_notes(
                        Path(record['output']).read_text(encoding='utf-8'),
                        store.video(int(match[1])),
                    )
                    return self.respond(200, text, 'text/plain')
                except OSError:
                    return self.respond(404, {'error': 'Saved study notes are missing.'})
                finally:
                    store.close()
            match = re.fullmatch(r'/api/urls/(\d+)/(transcript|captions)', self.path)
            if match:
                store = Store(database)
                try:
                    video = store.video(int(match[1]))
                    path = (
                        (
                            video['versions'].get('captions', {}).get('path')
                            if match[2] == 'captions'
                            else video['transcript_path']
                        )
                        if video
                        else None
                    )
                    if not path:
                        return self.respond(404, {'error': 'Transcript not ready.'})
                    return self.respond(200, Path(path).read_text(encoding='utf-8'), 'text/plain')
                except OSError:
                    return self.respond(
                        404, {'error': 'Transcript file missing. Retry processing.'}
                    )
                finally:
                    store.close()
            match = re.fullmatch(r'/api/urls/(\d+)/thumbnail', self.path)
            if match:
                store = Store(database)
                try:
                    video = store.video(int(match[1]))
                    mime = video['metadata'].get('thumbnail_mime') if video else None
                    if not mime:
                        return self.respond(404, {'error': 'Thumbnail unavailable.'})
                    image = config.DATA_DIR / 'videos' / match[1] / 'thumbnail.image'
                    return self.respond(200, image.read_bytes(), mime)
                except OSError:
                    return self.respond(404, {'error': 'Thumbnail unavailable.'})
                finally:
                    store.close()
            self.respond(404, {'error': 'Not found.'})

        def do_DELETE(self):
            if not self.allowed():
                return self.respond(403, {'error': 'Local requests only.'})
            match = re.fullmatch(r'/api/urls/(\d+)', self.path)
            if not match:
                return self.respond(404, {'error': 'Not found.'})
            try:
                processor.remove(int(match[1]))
                return self.respond(200, {'removed': True})
            except ValueError as exc:
                return self.respond(409, {'error': str(exc)})
            except (OSError, psycopg.Error):
                return self.respond(
                    500, {'error': 'Could not remove all lecture data. Please retry.'}
                )

        def do_POST(self):
            if not self.allowed():
                return self.respond(403, {'error': 'Local requests only.'})
            process_match = re.fullmatch(r'/api/urls/(\d+)/process', self.path)
            graph_match = re.fullmatch(r'/api/graph/(1\.5B|7B|14B|openai|all)/build', self.path)
            if (
                self.path not in ('/api/urls', '/api/answers')
                and not process_match
                and not graph_match
            ):
                return self.respond(404, {'error': 'Not found.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Send a small JSON request containing a video URL.')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a URL object.')
                if self.path == '/api/answers':
                    from .answers import start

                    return self.respond(202, {'id': start(processor, payload)})
                if graph_match:
                    ids = processor.start_graph(graph_match[1], payload.get('rebuild') is True)
                    return self.respond(202 if ids else 200, {'build_ids': ids})
                if process_match:
                    started = processor.start(
                        int(process_match[1]),
                        payload.get('action', 'check'),
                        payload.get('model'),
                        payload.get('seed'),
                        payload.get('rights_confirmed', False),
                    )
                    return self.respond(202 if started else 200, {'started': started})
                url = normalize_url(payload.get('url'))
                store = Store(database)
                try:
                    row, created = store.save_url(url)
                finally:
                    store.close()
                self.respond(201 if created else 200, {'item': row, 'created': created})
            except (ValueError, UnicodeError) as exc:
                self.respond(400, {'error': str(exc)})
            except psycopg.Error:
                self.respond(500, {'error': 'Could not save the URL. Please try again.'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def run(database, port):
    with make_server(database, port) as server:
        print(f'Study Desk Lite: http://127.0.0.1:{server.server_port}', flush=True)
        print(
            'Caption-first processing available. Press Ctrl+C to stop (active job finishes).',
            flush=True,
        )
        server.serve_forever()
