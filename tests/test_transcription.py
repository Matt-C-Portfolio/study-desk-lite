import unittest
from study_desk.transcription import progress_line


class ProgressTests(unittest.TestCase):
    def test_audio_progress(self):
        self.assertIn('25.00%', progress_line(30, 120))

    def test_completion_reserved_for_saved_files(self):
        self.assertIn('99.90%', progress_line(120, 120))
        self.assertIn('99.90%', progress_line(125, 120))

    def test_missing_duration(self):
        self.assertIn('0.00%', progress_line(0, 0))
