from database_support import temporary_database, database_for
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from study_desk.intake import normalize_url
from study_desk.ui import make_server


class IntakeTests(unittest.TestCase):
    def test_video_variants(self):
        self.assertEqual(normalize_url('https://youtu.be/abcdefghijk?t=10'),
                         normalize_url('https://www.youtube.com/watch?v=abcdefghijk&list=test'))

    def test_reject_other_hosts_and_playlists(self):
        for url in ['https://youtube.com.evil.test/watch?v=abcdefghijk',
                    'https://youtube.com/playlist?list=test', 'file:///tmp/test', None]:
            with self.assertRaises(ValueError):
                normalize_url(url)

    def test_http_save_duplicate_and_persist(self):
        with temporary_database() as folder:
            db=database_for(folder)
            server=make_server(db, 0)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                def post(origin=None):
                    headers={'Content-Type':'application/json'}
                    if origin: headers['Origin']=origin
                    return urlopen(Request(base+'/api/urls',data=json.dumps({'url':'https://youtu.be/abcdefghijk'}).encode(),headers=headers))
                with post() as r: self.assertEqual(r.status,201)
                with post() as r: self.assertFalse(json.load(r)['created'])
                with urlopen(base+'/api/urls') as r: self.assertEqual(len(json.load(r)),1)
                with self.assertRaises(HTTPError) as error: post('https://example.com')
                self.assertEqual(error.exception.code,403)
                from study_desk.storage import Store
                store=Store(db)
                try:
                    self.assertEqual(len(store.urls()),1)
                    self.assertEqual(store.runs(store.urls()[0]['id']), {})
                finally:
                    store.close()
                for asset in ('app.js', 'study.js', 'styles.css'):
                    with urlopen(base+'/'+asset) as response:
                        self.assertEqual(response.status, 200)
                        self.assertTrue(response.read())
            finally:
                server.shutdown();server.server_close();thread.join()
