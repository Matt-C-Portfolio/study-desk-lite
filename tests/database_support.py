"""Real PostgreSQL tests isolated in disposable schemas and file directories."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from unittest.mock import patch
from study_desk import config

_databases = {}

def database_for(folder):
    return _databases[str(Path(folder).resolve())]

@contextmanager
def temporary_database():
    schema = 'lite_test_' + uuid4().hex
    with psycopg.connect(config.DATABASE, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with TemporaryDirectory() as folder, patch.object(config, 'DATA_DIR', Path(folder)):
                key = str(Path(folder).resolve())
                _databases[key] = make_conninfo(config.DATABASE, options=f'-c search_path={schema}')
                try:
                    yield folder
                finally:
                    _databases.pop(key, None)
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
