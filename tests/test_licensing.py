from database_support import temporary_database, database_for
import unittest
import tempfile
from pathlib import Path
from study_desk.licensing import lecture_license, attributed_notes
from study_desk.storage import Store


class LicensingTests(unittest.TestCase):
    def test_preset_saved_at_intake_and_download_credit_once(self):
        url = 'https://www.youtube.com/watch?v=k6U-i4gXkLM'
        with temporary_database() as folder:
            store = Store(database_for(folder))
            row, _ = store.save_url(url)
            video = store.video(row['id'])
            self.assertEqual(video['metadata']['content_license']['license_name'], 'CC BY-NC-SA 4.0')
            notes = attributed_notes('# Notes', video)
            self.assertIn('Eric Grimson and John Guttag', notes)
            self.assertIn('AI-generated', notes)
            self.assertEqual(attributed_notes(notes, video), notes)
            store.close()

    def test_unknown_video_does_not_inherit_license(self):
        self.assertIsNone(lecture_license('https://www.youtube.com/watch?v=unknown0000'))
        self.assertEqual(attributed_notes('Notes', {'metadata': {}}), 'Notes')
