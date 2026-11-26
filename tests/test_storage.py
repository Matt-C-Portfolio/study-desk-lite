import unittest
from concurrent.futures import ThreadPoolExecutor
import psycopg
from database_support import temporary_database, database_for
from study_desk.storage import Store


class StorageTests(unittest.TestCase):
    def test_parallel_workers_allocate_distinct_run_numbers(self):
        with temporary_database() as folder:
            database = database_for(folder)
            store = Store(database)
            video, _ = store.save_url('https://www.youtube.com/watch?v=test')
            store.close()

            def reserve(_):
                worker = Store(database)
                try:
                    return worker.new_run(video['id'], '7B', {'status': 'queued'})['run_number']
                finally:
                    worker.close()

            with ThreadPoolExecutor(max_workers=7) as workers:
                self.assertEqual(sorted(workers.map(reserve, range(15))), list(range(1, 16)))
            store = Store(database)
            self.assertEqual(len(store.history(video['id'])['7B']), 15)
            store.close()

    def test_failed_transaction_leaves_no_partial_records(self):
        with temporary_database() as folder:
            store = Store(database_for(folder))
            try:
                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    with store.db.transaction():
                        store.save_url('https://www.youtube.com/watch?v=test')
                        store.save_metadata(999, {'title': 'Missing lecture'})
                self.assertEqual(store.urls(), [])
            finally:
                store.close()
