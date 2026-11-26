from database_support import temporary_database, database_for
import tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
from study_desk.storage import Store
from study_desk.study_jobs import generate
from test_study_pipeline import FakeModel, ANSWERS
from contextlib import nullcontext

class RunHistoryTests(unittest.TestCase):
    def test_persistence_and_first_success(self):
        with temporary_database() as d:
            db=database_for(d)
            s=Store(db)
            video,_=s.save_url('https://www.youtube.com/watch?v=example')
            vid=video['id']
            s.new_run(vid,'7B',{'status':'error','folder':'old'})
            s.new_run(vid,'7B',{'status':'complete'})
            s.new_run(vid,'7B',{'status':'complete'})
            self.assertEqual([r['graph_selected'] for r in s.history(vid)['7B']],[False,True,False])
            s.close();s=Store(db)
            self.assertEqual(s.run_record(vid,'7B',1)['folder'],'old')
            self.assertEqual(len(s.history(vid)['7B']),3)
            s.remove_video(vid)
            self.assertEqual(s.history(vid),{})
            s.close()

    def test_fresh_runs_have_separate_outputs(self):
        with temporary_database() as d:
            db=database_for(d);s=Store(db)
            video,_=s.save_url('https://www.youtube.com/watch?v=k6U-i4gXkLM')
            transcript=Path(d)/'transcript.txt';transcript.write_text('Multiplying a string repeats it.')
            s.update_video(video['id'],'ready',transcript_path=str(transcript),method='manual captions')
            folders=[]
            for _ in range(2):
                s.new_run(video['id'],'1.5B',{'status':'running','passes':[{} for _ in range(4)]})
                model=FakeModel(ANSWERS)
                with patch('study_desk.study_jobs.load_model',return_value=nullcontext(model)):
                    generate(db,s.video(video['id']),'1.5B')
                r=s.runs(video['id'])['1.5B']
                self.assertEqual(r['status'],'complete')
                self.assertEqual(model.calls,4)
                self.assertTrue(all(p['cached_calls']==0 for p in r['passes']))
                folders.append(r['folder'])
            self.assertNotEqual(*folders)
            self.assertTrue(all((Path(f)/'notes.md').is_file() for f in folders))
            self.assertEqual([r['graph_selected'] for r in s.history(video['id'])['1.5B']],[True,False])
            s.close()
