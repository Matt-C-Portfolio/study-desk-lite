from database_support import temporary_database, database_for
import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from study_desk.openai_model import OpenAIModel,MODELS
from study_desk.processing import Processor
from study_desk.storage import Store

class OpenAITests(unittest.TestCase):
 def test_routing_usage_and_secret_not_saved(self):
  with temporary_database() as d, patch('study_desk.openai_model.api_key',return_value='test-secret'):
   model=OpenAIModel(d); requests=[]
   def response(req,**kwargs):
    requests.append(json.loads(req.data))
    return io.BytesIO(json.dumps({'status':'completed','usage':{'input_tokens':1000,'output_tokens':100,'input_tokens_details':{'cached_tokens':200}},'output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}]}).encode())
   with patch('study_desk.openai_model.urlopen',side_effect=response):
    for stage in range(4):
     model.stage=stage
     self.assertEqual(model.complete('lecture',json_mode={'type':'object'}),'{}')
   self.assertEqual([r['model'] for r in requests],MODELS)
   self.assertAlmostEqual(model.cost,.006248)
   self.assertTrue(all('seed' not in r for r in requests))
   self.assertTrue(all('test-secret' not in p.read_text() for p in Path(d).glob('*.json')))

 def test_selected_lecture_queues_separate_openai_run(self):
  with temporary_database() as d:
   db=database_for(d);store=Store(db)
   video,_=store.save_url('https://www.youtube.com/watch?v=k6U-i4gXkLM')
   transcript=Path(d)/'transcript.txt';transcript.write_text('selected transcript')
   store.update_video(video['id'],'ready',transcript_path=str(transcript))
   processor=Processor(db)
   with patch('study_desk.openai_model.api_key',return_value=''):
    with self.assertRaises(ValueError): processor.start(video['id'],'generate','openai')
   with patch('study_desk.openai_model.api_key',return_value='test'),patch('study_desk.processing.threading.Thread'):
    with self.assertRaises(ValueError): processor.start(video['id'],'generate_five','openai')
    processor.start(video['id'],'generate','openai',42)
   run=store.history(video['id'])['openai'][0]
   self.assertEqual(run['transcript_path'],str(transcript))
   self.assertIsNone(run['seed'])
   store.close()
