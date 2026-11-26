"""Configuration only: no model startup or database connections."""

import os
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get('STUDY_DESK_LITE_DATA', str(ROOT / 'data')))
DATABASE_CONFIG = Path.home() / '.study-desk-lite' / 'database.json'
DATABASE = os.environ.get('STUDY_DESK_LITE_DATABASE_URL') or (
    json.loads(DATABASE_CONFIG.read_text())['dsn']
    if DATABASE_CONFIG.is_file()
    else 'dbname=study_desk_lite host=localhost'
)
RUNTIME = ROOT / 'runtime' / 'llama.cpp' / 'llama-server.exe'
WHISPER_WEIGHTS = ROOT / 'models' / 'whisper' / 'large-v3'
