"""Portable dataset round trips use disposable schemas; no model work."""

from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

import psycopg
from psycopg.types.json import Jsonb

from database_support import database_for, temporary_database
from study_desk.storage import Store
from study_desk.retrieval import SCHEMA

spec = importlib.util.spec_from_file_location(
    'dataset', Path(__file__).resolve().parents[1] / 'scripts' / 'dataset.py'
)
dataset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dataset)


class DatasetTests(TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.source = Path(stack.enter_context(temporary_database()))
        self.source_db = database_for(self.source)
        self.target = Path(stack.enter_context(temporary_database()))
        self.target_db = database_for(self.target)
        self.bundle = Path(stack.enter_context(TemporaryDirectory())) / 'dataset'
        folder = self.source / 'videos' / '4'
        folder.mkdir(parents=True)
        (folder / 'transcript.txt').write_bytes('Lecture evidence \u2014 original.\r\n'.encode())
        (folder / 'runtime.log').write_bytes(b'Saved failed attempt details\n')
        (self.source / 'server.stdout.log').write_bytes(b'Unrelated server log')
        (self.source / 'worker.lock').write_bytes(b'1')
        store = Store(self.source_db)
        self.addCleanup(store.close)
        store.db.execute(SCHEMA)
        store.db.execute(
            "INSERT INTO video_intake(id,url) VALUES (4,'https://www.youtube.com/watch?v=k6U-i4gXkLM')"
        )
        store.db.execute(
            "INSERT INTO video_processing VALUES (4,'ready','',%s,'captions')",
            (str(folder / 'transcript.txt'),),
        )
        store.db.execute(
            'INSERT INTO study_run_history VALUES (4,%s,12,%s)',
            (
                '1.5B',
                Jsonb({'folder': str(folder), 'status': 'error', 'detail': 'Original failure'}),
            ),
        )
        store.db.execute(
            'INSERT INTO graph_build(id,model,fingerprint,data) OVERRIDING SYSTEM VALUE VALUES (9,%s,%s,%s)',
            (
                '1.5B',
                'fingerprint',
                Jsonb({'status': 'held', 'folder': str(folder)}),
            ),
        )
        for number in (2, 3):
            store.db.execute(
                'INSERT INTO concept VALUES (9,%s,%s,%s,NULL,%s,%s,%s)',
                (
                    number,
                    f'Concept {number}',
                    'Description',
                    [0.125] * 768,
                    'BGE',
                    'revision',
                ),
            )
        store.db.execute('UPDATE concept SET merged_into_id=3 WHERE id=2')
        store.db.execute(
            "INSERT INTO rag_transcript(video_id,transcript_digest,embedding_revision) VALUES (4,'digest','revision')"
        )
        self.manifest = dataset.export(self.bundle, self.source_db, self.source)

    def test_round_trip_preserves_records_files_and_identity_sequences(self):
        before = dataset.snapshot(self.source_db, self.source)
        dataset.restore(self.bundle, self.target_db, self.target)
        self.assertEqual(dataset.snapshot(self.target_db, self.target), before)
        for name in ('transcript.txt', 'runtime.log'):
            relative = Path('videos/4') / name
            self.assertEqual(
                (self.source / relative).read_bytes(), (self.target / relative).read_bytes()
            )
        self.assertEqual(self.manifest['artifact_files'], 2)
        self.assertFalse((self.target / 'worker.lock').exists())
        self.assertFalse((self.target / 'server.stdout.log').exists())
        with psycopg.connect(self.target_db) as connection:
            path = connection.execute('SELECT transcript_path FROM video_processing').fetchone()[0]
            self.assertEqual(Path(path), self.target.resolve() / 'videos/4/transcript.txt')
            video_id = connection.execute(
                "INSERT INTO video_intake(url) VALUES ('https://example.com/new') RETURNING id"
            ).fetchone()[0]
            build_id = connection.execute(
                "INSERT INTO graph_build(model,fingerprint,data) VALUES ('7B','new','{}') RETURNING id"
            ).fetchone()[0]
            self.assertEqual((video_id, build_id), (5, 10))

    def test_existing_files_and_records_are_never_replaced(self):
        sentinel = self.target / 'keep.txt'
        sentinel.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'not empty'):
            dataset.restore(self.bundle, self.target_db, self.target)
        self.assertEqual(sentinel.read_bytes(), b'keep')
        sentinel.unlink()
        store = Store(self.target_db)
        try:
            store.db.execute("INSERT INTO video_intake(url) VALUES ('existing')")
            with self.assertRaisesRegex(ValueError, 'already contains data'):
                dataset.restore(self.bundle, self.target_db, self.target)
            self.assertEqual(
                store.db.execute('SELECT url FROM video_intake').fetchone()['url'], 'existing'
            )
            self.assertFalse(any(self.target.iterdir()))
        finally:
            store.close()

    def test_corruption_is_rejected_before_restoring(self):
        archive = self.bundle / self.manifest['archives'][0]
        archive.write_bytes(archive.read_bytes() + b'corrupted')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            dataset.restore(self.bundle, self.target_db, self.target)
        self.assertFalse(any(self.target.iterdir()))

    def test_unsafe_archive_path_is_rejected_even_with_matching_checksum(self):
        archive = self.bundle / self.manifest['archives'][0]
        with ZipFile(archive, 'w') as output:
            output.writestr('../escape.txt', 'bad')
        self.manifest['files'][archive.name] = {
            'bytes': archive.stat().st_size,
            'sha256': dataset.digest(archive),
        }
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unsafe dataset path'):
            dataset.restore(self.bundle, self.target_db, self.target)
        self.assertFalse((self.target.parent / 'escape.txt').exists())
        self.assertFalse(any(self.target.iterdir()))

    def test_database_failure_rolls_back_tables_and_staged_files(self):
        with patch.object(dataset, 'load_tables', side_effect=ValueError('Simulated failure')):
            with self.assertRaisesRegex(ValueError, 'Simulated failure'):
                dataset.restore(self.bundle, self.target_db, self.target)
        self.assertFalse(any(self.target.iterdir()))
        with psycopg.connect(self.target_db) as connection:
            self.assertEqual(
                connection.execute(
                    'SELECT count(*) FROM pg_tables WHERE schemaname=current_schema()'
                ).fetchone()[0],
                0,
            )
