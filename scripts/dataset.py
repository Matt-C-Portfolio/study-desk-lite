"""Export, verify, or restore the recorded dataset without running inference."""

import argparse
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from study_desk import config

BUNDLE = ROOT / 'evaluation' / 'dataset'
TOKEN = '@study-desk-data/'
# Dependency order, including the self-referencing concept table handled below.
TABLES = (
    'video_intake',
    'video_processing',
    'video_metadata',
    'transcript_versions',
    'caption_checks',
    'study_run_history',
    'study_runs',
    'graph_build',
    'graph_input',
    'evidence_span',
    'graph_claim',
    'claim_evidence',
    'concept',
    'concept_alias',
    'claim_concept',
    'concept_resolution',
    'subject_area',
    'concept_subject_area',
    'concept_edge',
    'edge_evidence',
    'rag_transcript',
    'rag_passage',
)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_bytes(value):
    def encode(item):
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        raise TypeError(f'Cannot encode {type(item).__name__}')

    return (json.dumps(value, ensure_ascii=False, default=encode) + '\n').encode('utf-8')


def walk(value, transform):
    if isinstance(value, dict):
        return {key: walk(item, transform) for key, item in value.items()}
    if isinstance(value, list):
        return [walk(item, transform) for item in value]
    return transform(value) if isinstance(value, str) else value


def portable(value, data_dir):
    if re.match(r'^(?:[A-Za-z]:[\\/]|/)', value) and '\n' not in value:
        try:
            return TOKEN + Path(value).resolve().relative_to(data_dir.resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return value


def relative_path(name):
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in ('.', '..') for part in path.parts)
        or re.search(r'[\\:\x00-\x1f]', name)
        or any(part.endswith((' ', '.')) for part in path.parts)
        or any(PureWindowsPath(part).is_reserved() for part in path.parts)
    ):
        raise ValueError(f'Unsafe dataset path: {name!r}')
    return path


def local(value, data_dir):
    if value.startswith(TOKEN):
        return str(data_dir / relative_path(value[len(TOKEN) :]))
    return value


def columns(connection, table):
    return connection.execute(
        '''SELECT column_name, data_type, is_identity FROM information_schema.columns
           WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position''',
        (table,),
    ).fetchall()


def snapshot(database, data_dir):
    result = {}
    with psycopg.connect(database, row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        for table in TABLES:
            fields = columns(connection, table)
            if not fields:
                raise ValueError(f'Missing dataset table: {table}')
            keys = connection.execute(
                '''SELECT k.column_name FROM information_schema.table_constraints t
                   JOIN information_schema.key_column_usage k
                     USING (constraint_catalog, constraint_schema, constraint_name, table_name)
                   WHERE t.table_schema=current_schema() AND t.table_name=%s
                     AND t.constraint_type='PRIMARY KEY' ORDER BY k.ordinal_position''',
                (table,),
            ).fetchall()
            rows = connection.execute(
                sql.SQL('SELECT * FROM {} ORDER BY {}').format(
                    sql.Identifier(table),
                    sql.SQL(',').join(sql.Identifier(k['column_name']) for k in keys),
                )
            ).fetchall()
            if table in ('study_runs', 'study_run_history', 'graph_build') and any(
                row['data'].get('status') in ('running', 'queued') for row in rows
            ):
                raise ValueError('Finish or stop active work before exporting the dataset.')
            result[table] = {'columns': fields, 'rows': walk(rows, lambda v: portable(v, data_dir))}
    return result


def export(bundle, database, data_dir):
    bundle, data_dir = bundle.resolve(), data_dir.resolve()
    if bundle.exists() or bundle.is_relative_to(data_dir):
        raise ValueError('Export requires a new directory outside the runtime data directory.')
    tables = snapshot(database, data_dir)
    paths, omitted = [], []
    for path in sorted(data_dir.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(data_dir).as_posix()
        if path.suffix in ('.tmp', '.lock', '.pid', '.partial') or (
            path.parent == data_dir and path.suffix == '.log'
        ):
            omitted.append(name)
            continue
        relative_path(name)
        if not path.resolve().is_relative_to(data_dir):
            raise ValueError(f'Dataset file points outside data directory: {name}')
        paths.append((path, name))
    if not paths:
        raise ValueError('No saved dataset files found.')
    bundle.mkdir(parents=True)
    database_path = bundle / 'database.json.gz'
    database_path.write_bytes(gzip.compress(json_bytes(tables), compresslevel=9, mtime=0))
    archives, archive, directory_bytes, file_bytes = [], None, 0, 0
    try:
        for path, name in paths:
            content = path.read_bytes()
            if len(content) > 14_000_000:
                raise ValueError(f'Artifact too large for this small-file dataset format: {name}')
            if (
                archive is None
                or archive.fp.tell() + directory_bytes + len(content) + 1000 > 15_000_000
            ):
                if archive is not None:
                    archive.close()
                target = bundle / f'artifacts-{len(archives) + 1:03d}.zip'
                archives.append(target)
                archive = ZipFile(target, 'x', compression=ZIP_DEFLATED, compresslevel=7)
                directory_bytes = 0
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content, compress_type=ZIP_DEFLATED, compresslevel=7)
            directory_bytes += 100 + len(name.encode('utf-8'))
            file_bytes += len(content)
    finally:
        if archive is not None:
            archive.close()
    manifest = {
        'format': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'description': 'Recorded ten-lecture Study Desk Lite corpus and experiment artifacts.',
        'table_rows': {name: len(table['rows']) for name, table in tables.items()},
        'artifact_files': len(paths),
        'artifact_bytes': file_bytes,
        'omitted_transient_files': omitted,
        'database': database_path.name,
        'archives': [p.name for p in archives],
        'files': {
            p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)}
            for p in [database_path, *archives]
        },
        'paths': 'Database paths use @study-desk-data/. Artifact contents retain their original bytes and historical paths.',
    }
    (bundle / 'manifest.json').write_bytes(json_bytes(manifest))
    return manifest


def verify(bundle):
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    if manifest['format'] != 1 or set(manifest['table_rows']) != set(TABLES):
        raise ValueError('Unsupported dataset format or table set.')
    names = [manifest['database'], *manifest['archives']]
    if len(set(names)) != len(names) or set(names) != set(manifest['files']):
        raise ValueError('Dataset file list is inconsistent.')
    for name in names:
        if len(relative_path(name).parts) != 1:
            raise ValueError('Bundle members must be direct files.')
        path, expected = bundle / name, manifest['files'][name]
        if path.stat().st_size != expected['bytes'] or digest(path) != expected['sha256']:
            raise ValueError(f'Dataset checksum mismatch: {name}')
    return manifest


def extract(bundle, manifest, destination):
    seen, total = set(), 0
    for name in manifest['archives']:
        with ZipFile(bundle / name) as archive:
            for info in archive.infolist():
                path = relative_path(info.filename)
                key = info.filename.casefold()
                if (
                    key in seen
                    or info.is_dir()
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError(f'Duplicate or unsupported artifact: {info.filename}')
                seen.add(key)
                total += info.file_size
                if total > manifest['artifact_bytes'] or len(seen) > manifest['artifact_files']:
                    raise ValueError('Archive exceeds declared dataset size.')
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
    if len(seen) != manifest['artifact_files'] or total != manifest['artifact_bytes']:
        raise ValueError('Dataset artifact count or size mismatch.')


def empty_database(connection):
    tables = [
        row['tablename']
        for row in connection.execute(
            'SELECT tablename FROM pg_tables WHERE schemaname=current_schema()'
        )
    ]
    if set(tables) - set(TABLES):
        raise ValueError('Restore requires a dedicated Study Desk Lite database/schema.')
    for table in tables:
        if connection.execute(
            sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(table))
        ).fetchone():
            raise ValueError(
                'Database already contains data; restore never replaces existing records.'
            )


def load_tables(connection, tables, data_dir):
    for table in TABLES:
        expected = columns(connection, table)
        if tables[table]['columns'] != expected:
            raise ValueError(f'Dataset schema does not match installed code: {table}')
        rows = walk(tables[table]['rows'], lambda v: local(v, data_dir))
        names = [field['column_name'] for field in expected]
        merges = []
        if table == 'concept':
            for row in rows:
                if row['merged_into_id'] is not None:
                    merges.append((row['merged_into_id'], row['build_id'], row['id']))
                    row['merged_into_id'] = None
        values = [
            [
                Jsonb(row[n]) if field['data_type'] == 'jsonb' else row[n]
                for n, field in zip(names, expected)
            ]
            for row in rows
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                sql.SQL('INSERT INTO {} ({}) OVERRIDING SYSTEM VALUE VALUES ({})').format(
                    sql.Identifier(table),
                    sql.SQL(',').join(map(sql.Identifier, names)),
                    sql.SQL(',').join(sql.Placeholder() for _ in names),
                ),
                values,
            )
            if merges:
                cursor.executemany(
                    'UPDATE concept SET merged_into_id=%s WHERE build_id=%s AND id=%s', merges
                )
        for field in expected:
            if field['is_identity'] == 'YES':
                name = field['column_name']
                next_id = max((row[name] for row in rows), default=0) + 1
                connection.execute(
                    sql.SQL('ALTER TABLE {} ALTER COLUMN {} RESTART WITH {}').format(
                        sql.Identifier(table),
                        sql.Identifier(name),
                        sql.Literal(next_id),
                    )
                )


def restore(bundle, database, data_dir):
    bundle, data_dir = bundle.resolve(), data_dir.resolve()
    if data_dir.exists() and (not data_dir.is_dir() or any(data_dir.iterdir())):
        raise ValueError('Data directory is not empty; restore never replaces existing files.')
    manifest = verify(bundle)
    tables = json.loads(gzip.decompress((bundle / manifest['database']).read_bytes()))
    if set(tables) != set(TABLES) or any(
        len(tables[name]['rows']) != manifest['table_rows'][name] for name in TABLES
    ):
        raise ValueError('Database row counts do not match the manifest.')
    # No Processor, model, downloader, or background worker is started.
    from study_desk.retrieval import SCHEMA as retrieval_schema

    data_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.study-desk-restore-', dir=data_dir.parent) as temporary:
        staged = Path(temporary) / 'data'
        staged.mkdir()
        installed = False
        try:
            with psycopg.connect(database, row_factory=dict_row) as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':dataset-restore', 0))"
                )
                empty_database(connection)
                extract(bundle, manifest, staged)
                for name in ('schema.sql', 'graph_schema.sql'):
                    connection.execute((ROOT / 'study_desk' / name).read_text(encoding='utf-8'))
                connection.execute(retrieval_schema)
                connection.execute(
                    sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(
                        sql.SQL(',').join(map(sql.Identifier, TABLES)),
                    )
                )
                empty_database(connection)
                load_tables(connection, tables, data_dir)
                # Both directories are siblings under the explicitly selected parent.
                if staged.resolve().parent.parent != data_dir.parent or data_dir.parent == data_dir:
                    raise ValueError('Invalid restore destination.')
                if data_dir.exists():
                    data_dir.rmdir()  # Only succeeds for an empty directory.
                staged.rename(data_dir)
                installed = True
            # The database transaction commits only after the files are installed.
        except BaseException:
            if installed:
                data_dir.rename(staged)
            raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('restore', 'verify', 'export'))
    parser.add_argument(
        '--bundle', type=Path, default=BUNDLE, help='Dataset directory (export requires a new one)'
    )
    args = parser.parse_args()
    try:
        if args.action == 'verify':
            manifest = verify(args.bundle)
        else:
            manifest = globals()[args.action](args.bundle, config.DATABASE, config.DATA_DIR)
        size = sum(item['bytes'] for item in manifest['files'].values()) / 1_000_000
        print(
            f"Dataset {args.action} complete: {manifest['table_rows']['video_intake']} lectures, "
            f"{manifest['artifact_files']:,} artifact files, {size:.2f} MB compressed."
        )
    except psycopg.Error:
        # Connection errors can contain credentials from a malformed DSN.
        parser.exit(
            1,
            'Dataset database operation failed; check PostgreSQL configuration and schema permissions.\n',
        )
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Dataset error: {exc}\n')


if __name__ == '__main__':
    main()
