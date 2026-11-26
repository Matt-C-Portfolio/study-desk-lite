from database_support import temporary_database, database_for
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from study_desk.processing import Processor
from study_desk.storage import Store
from study_desk.model import LocalModel

class SeedsTests(unittest.TestCase):
 def test_queue_continues_after_failure(self):
  with temporary_database() as d:
   db=database_for(d);store=Store(db)
   video,_=store.save_url('https://www.youtube.com/watch?v=k6U-i4gXkLM')
   transcript=Path(d)/'transcript.txt';transcript.write_text('test')
   store.update_video(video['id'],'ready',transcript_path=str(transcript))
   processor=Processor(db)
   with patch('study_desk.processing.threading.Thread'):
    self.assertTrue(processor.start(video['id'],'generate_five','1.5B'))
   records=store.history(video['id'])['1.5B']
   self.assertEqual([r['seed'] for r in records],list(range(42,47)))
   self.assertTrue(all(r['status']=='queued' for r in records))
   with self.assertRaises(ValueError):processor.start(video['id'],'generate','7B',42)
   seen=[]
   def fake_generate(database,v,model,number):
    s=Store(database);r=s.run_record(v['id'],model,number);seen.append(r['seed'])
    s.close()
    if number==1:raise RuntimeError('test failure')
    s=Store(database);r.update(status='complete');s.save_run(v['id'],model,r);s.close()
   with patch('study_desk.study_jobs.generate',side_effect=fake_generate):
    processor._generate(store.video(video['id']),'1.5B',[r['run_number'] for r in records])
   self.assertEqual(seen,list(range(42,47)))
   self.assertFalse(processor.active)
   self.assertEqual([r['status'] for r in store.history(video['id'])['1.5B']],['error']+['complete']*4)
   for seed in [True,-1,'42',2**32]:
    with self.assertRaises(ValueError):processor.start(video['id'],'generate','1.5B',seed)
   store.close()

 def test_seed_sent_in_request(self):
  import io
  requests=[]
  def response(req,**kwargs):
   data=json.loads(req.data);requests.append(data)
   if req.full_url.endswith('/apply-template'):result={'prompt':'test'}
   elif req.full_url.endswith('/tokenize'):result={'tokens':[1,2,3]}
   else:result={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
   return io.BytesIO(json.dumps(result).encode())
  model=LocalModel('http://127.0.0.1:8800');model.seed=42
  with patch('study_desk.model.urlopen',side_effect=response):model.complete('test')
  self.assertEqual(requests[-1]['seed'],42)
  self.assertEqual(model.request_info['seed'],42)
  model.seed=None
  with patch('study_desk.model.urlopen',side_effect=response):model.complete('test')
  self.assertNotIn('seed',requests[-1])

 def test_all_local_runs_share_one_queue_and_continue(self):
  with temporary_database() as d:
   db=database_for(d);store=Store(db)
   video,_=store.save_url('https://www.youtube.com/watch?v=k6U-i4gXkLM')
   transcript=Path(d)/'transcript.txt';transcript.write_text('test')
   store.update_video(video['id'],'ready',transcript_path=str(transcript))
   processor=Processor(db)
   with patch('study_desk.processing.threading.Thread') as thread:
    processor.start(video['id'],'generate_all_local','openai')
   jobs=thread.call_args.kwargs['args'][1]
   self.assertEqual(jobs,[(m,n) for m in ['1.5B','7B','14B'] for n in range(1,6)])
   self.assertEqual(set(store.history(video['id'])),{'1.5B','7B','14B'})
   for m in ['1.5B','7B','14B']:
    self.assertEqual([r['seed'] for r in store.history(video['id'])[m]],list(range(42,47)))
   seen=[]
   def fake_generate(database,v,model,number):
    self.assertTrue(processor.active)
    seen.append((model,number))
    if number==1: raise RuntimeError('test failure')
    r=store.run_record(v['id'],model,number);r['status']='complete';store.save_run(v['id'],model,r)
   with patch('study_desk.study_jobs.generate',side_effect=fake_generate):
    processor._generate_queue(store.video(video['id']),jobs)
   self.assertEqual(seen,jobs)
   self.assertFalse(processor.active)
   for m in ['1.5B','7B','14B']:
    self.assertEqual([r['status'] for r in store.history(video['id'])[m]],['error']+['complete']*4)
   store.close()
