"""Own one local llama.cpp process for a generation job, then release its VRAM."""

from contextlib import contextmanager
import json
import socket
import subprocess
import time
from urllib.request import urlopen

from . import config
from .model import LocalModel

MODELS = {
    size: config.ROOT / 'models' / f'DeepSeek-R1-Distill-Qwen-{size}-Q4_K_M.gguf'
    for size in ('1.5B', '7B', '14B')
}


@contextmanager
def load_model(size, folder):
    weights = MODELS.get(size)
    if not weights or not weights.is_file() or not config.RUNTIME.is_file():
        raise ValueError('Local model or llama.cpp runtime is missing.')
    # A separate port avoids replacing an independently running CLI model.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 8800))
    with (folder / 'runtime.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(
            [
                str(config.RUNTIME),
                '-m',
                str(weights),
                '--host',
                '127.0.0.1',
                '--port',
                '8800',
                '-c',
                '32768',
                '-np',
                '1',
                '-ngl',
                '99',
                '-fa',
                'on',
                '-ctk',
                'q8_0',
                '-ctv',
                'q8_0',
            ],
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        'Model could not start. Check runtime.log; close other GPU models and retry.'
                    )
                try:
                    with urlopen('http://127.0.0.1:8800/health', timeout=2) as response:
                        if json.load(response).get('status') == 'ok':
                            break
                except (OSError, ValueError):
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError('Local model loading timed out.')
            yield LocalModel('http://127.0.0.1:8800')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
