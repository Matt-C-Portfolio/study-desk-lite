import unittest
from types import SimpleNamespace
from study_desk.answers import context,prompt_for,start,read,answer_schema,render_answer
class AnswerTests(unittest.TestCase):
 def test_plain_does_not_retrieve(self):
  self.assertEqual(context(None,None,'question','14B','plain'),([],[],None))
 def test_prompt_separates_source_and_graph(self):
  p=prompt_for('question',[{'text':'evidence','title':'video'}],[{'relation':'uses'}])
  self.assertIn('"id": "S1"',p);self.assertIn('not evidence',p);self.assertIn('untrusted data',p)
 def test_validation_before_work(self):
  for data in [{},{'question':'x','model':'bad','mode':'rag'},{'question':'x','model':'14B','mode':'rag','seed':True}]:
   with self.assertRaises(ValueError):start(None,data)
 def test_path_restriction(self):
  with self.assertRaises(ValueError):read('../config')
 def test_citations_selected_not_guessed(self):
  text,warnings=render_answer({'blocks':[{'text':'A claim.','source_ids':['S2','S2']}],'evidence_limitation':''},[{},{}])
  self.assertEqual(text,'A claim. [S2]');self.assertEqual(warnings,[])
 def test_missing_and_unknown_ids_remain_visible(self):
  text,warnings=render_answer({'blocks':[{'text':'A','source_ids':[]},{'text':'B','source_ids':['S9']}],'evidence_limitation':''},[{}])
  self.assertEqual(len(warnings),2);self.assertIn('[S9]',text)
 def test_insufficient_evidence_escape(self):
  text,warnings=render_answer({'blocks':[],'evidence_limitation':'Not covered.'},[{}])
  self.assertIn('Not covered.',text);self.assertNotIn('[S',text)
 def test_schema_limits_ids(self):
  ids=answer_schema([{},{}])['properties']['blocks']['items']['properties']['source_ids']
  self.assertEqual(ids['minItems'],1);self.assertEqual(ids['items']['enum'],['S1','S2'])
 def test_code_citation_outside_fence(self):
  text,_=render_answer({'blocks':[{'text':'```python\nx=1\n```','source_ids':['S1']}],'evidence_limitation':''},[{}])
  self.assertTrue(text.endswith('```\n\n[S1]'))
if __name__=='__main__'  :unittest.main()
