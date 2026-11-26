from database_support import temporary_database, database_for
import tempfile
import unittest
from pathlib import Path
from study_desk.processing import Processor
from study_desk.storage import Store

class RemovalTests(unittest.TestCase):
    def test_removes_all_lecture_data_and_preserves_other_lecture(self):
        with temporary_database() as tmp:
            db = database_for(tmp)
            processor = Processor(db)
            store = Store(db)
            first, _ = store.save_url('https://www.youtube.com/watch?v=first')
            other, _ = store.save_url('https://www.youtube.com/watch?v=other')
            vid = first['id']
            folder = Path(tmp) / 'videos' / str(vid)
            folder.mkdir(parents=True)
            (folder / 'notes.md').write_text('saved results')
            store.save_metadata(vid, {'title': 'Test'})
            store.save_version(vid, 'local', folder / 'transcript.txt', 'local')
            store.caption_status(vid, 'unavailable')
            store.update_video(vid, 'ready')
            store.save_run(vid, '14B', {'status': 'complete'})
            store.close()
            processor.active = True
            with self.assertRaises(ValueError):
                processor.remove(vid)
            self.assertTrue(folder.exists())
            processor.active = False
            processor.remove(vid)
            self.assertFalse(folder.exists())
            store = Store(db)
            self.assertIsNone(store.video(vid))
            self.assertIsNotNone(store.video(other['id']))
            for table in ('study_runs', 'transcript_versions', 'caption_checks', 'video_metadata', 'video_processing'):
                self.assertEqual(store.db.execute(f'SELECT COUNT(*) AS count FROM {table} WHERE video_id=%s', (vid,)).fetchone()['count'], 0)
            store.close()
