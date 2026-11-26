from database_support import temporary_database, database_for
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from study_desk.video import process_video


class VideoTests(unittest.TestCase):
    def test_captions_skip_audio_and_whisper(self):
        with temporary_database() as folder, \
             patch('study_desk.video.fetch_metadata', return_value={'title': 'Test'}), \
             patch('study_desk.video.fetch_captions', return_value={
                 'method':'manual captions','language':'en',
                 'segments':[{'start':0,'end':2,'text':'Test lecture.'}]}), \
             patch('study_desk.video.download_audio') as download, \
             patch('study_desk.video.local_transcribe') as whisper:
            path, method = process_video('https://www.youtube.com/watch?v=abcdefghijk',folder,lambda *args:None)
            self.assertEqual(path.read_text().strip(),'Test lecture.')
            self.assertEqual(method,'manual captions')
            download.assert_not_called();whisper.assert_not_called()

    def test_explicit_local_transcription(self):
        with temporary_database() as folder, \
             patch('study_desk.video.fetch_metadata', return_value={}), \
             patch('study_desk.video.fetch_captions', return_value=None), \
             patch('study_desk.video.download_audio', return_value=Path('audio.webm')) as download, \
             patch('study_desk.video.local_transcribe', return_value={
                 'segments':[{'start':0,'end':2,'text':'Local speech.'}]}) as whisper:
            _, method = process_video('https://www.youtube.com/watch?v=abcdefghijk',folder,lambda *args:None,mode='local')
            self.assertEqual(method,'Faster-Whisper large-v3')
            download.assert_called_once();whisper.assert_called_once()

    def test_caption_failure_does_not_trigger_download(self):
        with temporary_database() as folder, \
             patch('study_desk.video.fetch_metadata', return_value={}), \
             patch('study_desk.video.fetch_captions', side_effect=RuntimeError('blocked')), \
             patch('study_desk.video.download_audio') as download:
            with self.assertRaisesRegex(RuntimeError,'blocked'):
                process_video('https://www.youtube.com/watch?v=abcdefghijk',folder,lambda *args:None)
            download.assert_not_called()

    def test_missing_captions_does_not_transcribe(self):
        with temporary_database() as folder, \
             patch('study_desk.video.fetch_metadata', return_value={}), \
             patch('study_desk.video.fetch_captions', return_value=None), \
             patch('study_desk.video.download_audio') as download, \
             patch('study_desk.video.local_transcribe') as whisper:
            result = process_video('https://www.youtube.com/watch?v=abcdefghijk',folder,lambda *args:None)
            self.assertEqual(result, (None, None))
            download.assert_not_called();whisper.assert_not_called()

    def test_selecting_versions_preserves_both(self):
        from study_desk.storage import Store
        from study_desk.processing import Processor
        with temporary_database() as folder:
            root = Path(folder)
            db = database_for(root)
            captions, local = root / 'captions.txt', root / 'local.txt'
            captions.write_text('Caption text.'); local.write_text('Local text.')
            store = Store(db)
            video, _ = store.save_url('https://www.youtube.com/watch?v=abcdefghijk')
            store.save_version(video['id'], 'captions', captions, 'manual captions')
            store.save_version(video['id'], 'local', local, 'Faster-Whisper large-v3')
            store.close()
            processor = Processor(db)
            self.assertFalse(processor.start(video['id'], 'local'))
            self.assertFalse(processor.start(video['id'], 'captions'))
            store = Store(db)
            row = store.video(video['id'])
            self.assertEqual(row['transcript_path'], str(captions))
            self.assertEqual(set(row['versions']), {'captions','local'})
            store.close()
