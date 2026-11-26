import unittest
from types import SimpleNamespace
from study_desk.answer_graph import expand
class GraphRetrievalTests(unittest.TestCase):
 def test_keeps_direct_evidence_and_records_relationship_route(self):
  passages=[dict(passage_id='p1',text='Direct evidence',title='one')]
  graph=dict(build={'id':'build'},claims=[dict(id='c1',span_ids=['p1']),dict(id='c2',span_ids=['p2'])],concepts=[dict(id='a',merged_into_id=None,claim_ids=['c1'],label='A'),dict(id='b',merged_into_id=None,claim_ids=['c2'],label='B')],edges=[dict(id='edge',source_id='b',target_id='a',predicate='supports',rationale='B supports A')],inputs=[dict(video_id=2,title='two',url='https://example.com')])
  row=dict(id='p2',video_id=2,text_content='Supporting evidence',embedding=[1.,0.],start_s=1,end_s=2)
  store=SimpleNamespace(db=SimpleNamespace(execute=lambda *args:[row]))
  embedder=SimpleNamespace(encode=lambda texts,**kw:[[1.,0.] for _ in texts])
  selected,relations,bid=expand(store,embedder,'q',passages,graph,{'p1','p2'})
  self.assertEqual([p['passage_id'] for p in selected],['p1','p2'])
  self.assertEqual(relations[0]['source'],'B')
  self.assertEqual(relations[0]['direct_source_ids'],['S1'])
  self.assertEqual(selected[1]['graph_path']['graph_source_id'],'S2')
  graph['edges']=[]
  selected,relations,_=expand(store,embedder,'q',passages,graph,{'p1','p2'})
  self.assertEqual(len(selected),1);self.assertEqual(relations,[])
 def test_no_connections_preserves_budget(self):
  passages=[dict(passage_id=f'p{i}',text=f'evidence {i}') for i in range(9)]
  graph=dict(build={'id':'build'},claims=[],concepts=[],edges=[])
  selected,relations,_=expand(None,None,'q',passages,graph,set())
  self.assertEqual(len(selected),6);self.assertEqual(relations,[])
if __name__=='__main__':unittest.main()
