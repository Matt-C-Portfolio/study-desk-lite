import json
import unittest
from pathlib import Path
from unittest.mock import patch
from database_support import temporary_database,database_for
from study_desk.storage import Store
from study_desk.graph import select_inputs, split_passage
from study_desk.graph_pipeline import apply_merge,GraphPipeline
from study_desk.graph_store import save_inputs,save_graph,read_graph

class FakeEmbedder:
    pass

def vector(text):
    return [1.0]+[0.0]*767

class FakeModel:
    def complete(self,prompt,**kw):
        data=json.loads(prompt.split('DATA:\n')[-1])
        slots=kw['json_mode']['properties']
        if 'existing_areas' in data:
            return json.dumps({slot:{'areas':['Computer science']} for slot in slots})
        if 'decision' in next(iter(slots.values()))['properties']:
            return json.dumps({slot:dict(decision='keep',rationale='Distinct concepts') for slot in slots})
        return json.dumps({slot:dict(direction='none',predicate='',rationale='No evidence') for slot in slots})


def sample_claims():
    return [dict(id=f'V1:extract-1/topic-{i//2+1}/bullet-{i%2+1}',
        extraction_id=f'extract-1/topic-{i//2+1}/bullet-{i%2+1}',video_id=1,
        text=f'Original claim {i}',source=dict(id='S1',text='Exact transcript'),span_ids=[f's{i}'],
        original=dict(topic=dict(title=['Backpropagation','Backpropagation for beginners','Gradient descent'][i//2],
                                gist='Original topic explanation',examples=['Exact example']))) for i in range(6)]


class GraphTests(unittest.TestCase):
    def test_topics_preserve_claim_links_without_assignment_calls(self):
        from tempfile import TemporaryDirectory
        from copy import deepcopy
        claims=sample_claims();original=deepcopy(claims)
        # Identical titles in different extraction positions remain distinct candidates.
        claims[2]['original']['topic']['title']=claims[3]['original']['topic']['title']='Backpropagation'
        original=deepcopy(claims)
        with TemporaryDirectory() as folder,patch('study_desk.graph_pipeline.embed_texts',side_effect=lambda e,ts:[vector(t) for t in ts]):
            model=FakeModel()
            with patch.object(model,'complete',wraps=model.complete) as complete:
                p=GraphPipeline(model,FakeEmbedder(),Path(folder),{},lambda *a:None,lambda *a:None).run(claims)
                self.assertEqual(complete.call_count,3)  # One batch per model stage, not per claim/pair.
        self.assertEqual(claims,original)
        self.assertEqual(len(p.concepts),3)
        self.assertEqual(p.assignments[claims[0]['id']],p.assignments[claims[1]['id']])
        self.assertNotEqual(p.assignments[claims[0]['id']],p.assignments[claims[2]['id']])
        self.assertTrue(all(p.assignments[x['id']] for x in claims))
        self.assertEqual(p.edges,[])
        self.assertEqual(p.issues,[])
        self.assertEqual(len(p.areas),1)
        self.assertNotIn('Assign',{x['stage'] for x in p.calls})

    def test_batch_merge_and_relationships_bind_original_evidence_in_code(self):
        from tempfile import TemporaryDirectory
        from copy import deepcopy
        class Model(FakeModel):
            def complete(self,prompt,**kw):
                data=json.loads(prompt.split('DATA:\n')[-1]);slots=kw['json_mode']['properties']
                if 'existing_areas' in data:return super().complete(prompt,**kw)
                if 'decision' in next(iter(slots.values()))['properties']:
                    result={}
                    for slot,pair in data['pairs'].items():
                        labels=[data['concepts'][pair[side]]['label'] for side in ['left','right']]
                        result[slot]=dict(decision='merge' if all('Backpropagation' in x for x in labels) else 'keep',rationale='Meaning comparison')
                    return json.dumps(result)
                return json.dumps({slot:dict(direction='right_to_left',predicate='uses',rationale='Claim-based relationship') for slot in slots})
        claims=sample_claims();original=deepcopy(claims)
        with TemporaryDirectory() as folder,patch('study_desk.graph_pipeline.embed_texts',side_effect=lambda e,ts:[vector(t) for t in ts]):
            p=GraphPipeline(Model(),FakeEmbedder(),Path(folder),{},lambda *a:None,lambda *a:None).run(claims)
            log=json.loads((Path(folder)/'connect-0001.json').read_text())
        self.assertEqual(claims,original)
        self.assertEqual(p.assignments[claims[0]['id']],p.assignments[claims[2]['id']])
        self.assertEqual(p.concepts[1]['merged_into'],1)
        self.assertEqual(p.concepts[0]['aliases'],{'Backpropagation for beginners'})
        self.assertEqual(len(p.edges),1)
        edge=p.edges[0]
        self.assertEqual((edge['source_id'],edge['target_id']),(3,1))
        self.assertEqual(edge['claim_ids'],log['bindings']['P1']['context_claim_ids'])
        self.assertEqual(set(edge['span_ids']),{sid for x in claims if x['id'] in edge['claim_ids'] for sid in x['span_ids']})
        self.assertTrue(all(p.assignments[x['id']] for x in claims))

    def test_failed_model_batches_never_drop_topics_or_claims(self):
        from tempfile import TemporaryDirectory
        class BrokenModel:
            def complete(self,*args,**kwargs):return '{"invented_slot": {}}'
        claims=sample_claims()
        with TemporaryDirectory() as folder,patch('study_desk.graph_pipeline.embed_texts',side_effect=lambda e,ts:[vector(t) for t in ts]):
            p=GraphPipeline(BrokenModel(),FakeEmbedder(),Path(folder),{},lambda *a:None,lambda *a:None).run(claims)
        self.assertEqual(len(p.concepts),3)
        self.assertTrue(all(p.assignments[x['id']] for x in claims))
        self.assertEqual(p.edges,[])
        self.assertTrue(any(x['stage']=='Consolidate' for x in p.issues))
        self.assertTrue(any(x['stage']=='Connect' for x in p.issues))

    def test_concurrent_schema_checks_do_not_replace_hold_function(self):
        from concurrent.futures import ThreadPoolExecutor
        with temporary_database() as folder:
            database=database_for(folder);store=Store(database)
            sql="SELECT xmin::text version FROM pg_proc WHERE oid='protect_graph_hold()'::regprocedure"
            before=store.db.execute(sql).fetchone()['version']
            def check(_):
                other=Store(database)
                try:return other.db.execute(sql).fetchone()['version']
                finally:other.close()
            with ThreadPoolExecutor(max_workers=6) as pool:
                versions=list(pool.map(check,range(18)))
            self.assertEqual(versions,[before]*18)
            store.close()

    def test_held_build_cannot_be_started_by_stale_worker(self):
        from psycopg.types.json import Jsonb
        import psycopg
        from study_desk.graph_jobs import build
        with temporary_database() as folder:
            database=database_for(folder);store=Store(database)
            bid=store.db.execute('INSERT INTO graph_build(model,fingerprint,data) VALUES (%s,%s,%s) RETURNING id',
                ('openai','held',Jsonb(dict(status='held',detail='User hold')))).fetchone()['id']
            with self.assertRaises(psycopg.errors.RaiseException):
                store.db.execute('UPDATE graph_build SET data=%s WHERE id=%s',(Jsonb(dict(status='running')),bid))
            store.db.execute('UPDATE graph_build SET data=%s WHERE id=%s',(Jsonb(dict(status='error')),bid))
            self.assertEqual(store.db.execute('SELECT data FROM graph_build WHERE id=%s',(bid,)).fetchone()['data']['status'],'held')
            with patch('study_desk.openai_model.OpenAIModel') as api:
                build(database,bid,[],dict(model='openai',status='queued'))
                api.assert_not_called()
            from study_desk.graph_jobs import reserve
            with patch('study_desk.graph_jobs.select_inputs') as inputs:
                self.assertEqual(reserve(store,['openai'],rebuild=True),[])
                inputs.assert_not_called()
            # The user's direct build action creates a fresh build using current inputs.
            with patch('study_desk.graph_jobs.select_inputs',return_value=([],[],'current-inputs')):
                jobs=reserve(store,['openai'],allow_held=True)
                self.assertEqual(len(jobs),1)
                self.assertNotEqual(jobs[0][0],bid)
                self.assertEqual(jobs[0][2]['status'],'queued')
                self.assertEqual(reserve(store,['openai'],allow_held=True),[])
            self.assertEqual(store.db.execute('SELECT data FROM graph_build WHERE id=%s',(bid,)).fetchone()['data']['status'],'held')
            store.close()

    def test_bulk_graph_build_is_local_and_direct_openai_action_can_override_hold(self):
        from study_desk.processing import Processor
        with temporary_database() as folder:
            processor=Processor(database_for(folder))
            with patch('study_desk.graph_jobs.reserve',return_value=[]) as reserve,patch('study_desk.openai_model.api_key',return_value='test-only') as key:
                processor.start_graph('all')
                self.assertEqual(reserve.call_args.args[1],('1.5B','7B','14B'))
                self.assertFalse(reserve.call_args.kwargs['allow_held'])
                key.assert_not_called()
                processor.start_graph('openai')
                self.assertEqual(reserve.call_args.args[1],('openai',))
                self.assertTrue(reserve.call_args.kwargs['allow_held'])
                key.assert_called_once()

    def test_passage_windows_preserve_every_original_character(self):
        from types import SimpleNamespace
        from tokenizers import Tokenizer
        tokenizer=Tokenizer.from_file('models/bge-base-en-v1.5/tokenizer.json')
        text=('  Neural networks — gradients, naïve estimates, and α = 0.01.\n' * 90)+'  '
        pieces=list(split_passage(text,SimpleNamespace(tokenizer=tokenizer)))
        self.assertGreater(len(pieces),1)
        self.assertEqual(''.join(part for _,_,part in pieces),text)
        for a,b,part in pieces:
            self.assertEqual(part,text[a:b])
            self.assertLessEqual(len(tokenizer.encode(part).ids),512)

    def test_first_success_not_latest_and_extraction_not_guide(self):
        with temporary_database() as folder:
            store=Store(database_for(folder));v,_=store.save_url('https://www.youtube.com/watch?v=test')
            p=Path(folder);(p/'source.json').write_text('[{"id":"S1","text":"original"}]')
            (p/'extract-1.json').write_text('{"topics":[{"title":"Original","bullets":["Exact claim"],"examples":[]}]}')
            for status in ('error','complete','complete'):store.new_run(v['id'],'14B',dict(status=status,folder=folder))
            (p/'lecture-presets.json').write_text(json.dumps([dict(url=v['url'],title='Lecture')]))
            with patch('study_desk.config.ROOT',p):
                inputs,missing,_=select_inputs(store,'14B')
            self.assertEqual(inputs[0]['run_number'],2)
            self.assertEqual(inputs[0]['extracts'][0]['topics'][0]['bullets'],['Exact claim'])
            self.assertEqual(missing,[]);store.close()

    def test_transitive_merge_keeps_claims_and_aliases(self):
        cs=[dict(id=i,label=f'name{i}',aliases=set()) for i in range(1,4)]
        assignments={'a':{3},'b':{2,3},'c':{1}}
        apply_merge(cs,assignments,2,3);apply_merge(cs,assignments,1,3)
        self.assertEqual(assignments,{'a':{1},'b':{1},'c':{1}})
        self.assertEqual(cs[0]['aliases'],{'name2','name3'})
        self.assertEqual([c.get('merged_into') for c in cs],[None,1,1])

    def test_graph_sources_survive_merge_and_delete_invalidates_build(self):
        from psycopg.types.json import Jsonb
        with temporary_database() as folder:
            store=Store(database_for(folder));v,_=store.save_url('https://www.youtube.com/watch?v=test')
            store.new_run(v['id'],'14B',{'status':'complete'})
            bid=store.db.execute('INSERT INTO graph_build(model,fingerprint,data) VALUES (%s,%s,%s) RETURNING id',('14B','f',Jsonb(dict(status='complete')))).fetchone()['id']
            inp=dict(video_id=v['id'],model='14B',run_number=1,title='Test')
            info=dict(embedding_model='bge',embedding_revision='test')
            span=dict(id='s',video_id=v['id'],source_hash='h',source_id='S1',start=1,end=2,start_char=0,end_char=4,text='text',embedding=vector(''),**info)
            claim=dict(id='c',video_id=v['id'],extraction_id='x',text='EXACT',original={'examples':['EXAMPLE']},span_ids=['s'])
            save_inputs(store,bid,[inp],[claim],[span])
            cs=[dict(id=i,label=f'name{i}',description='desc',embedding=vector(''),aliases=set(),**info) for i in (1,2)]
            mapping={'c':{2}};apply_merge(cs,mapping,1,2)
            save_graph(store,bid,cs,mapping,[],[],{},[])
            result=read_graph(store,'14B')
            self.assertEqual(result['claims'][0]['claim_text'],'EXACT')
            self.assertEqual(result['claims'][0]['span_ids'],['s'])
            self.assertEqual(result['claims'][0]['concept_ids'],[1])
            self.assertEqual(store.history(v['id'])['14B'][0]['status'],'complete')
            store.remove_video(v['id'])
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM graph_build').fetchone()['n'],0)
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM evidence_span').fetchone()['n'],0)
            store.close()

if __name__=='__main__':unittest.main()
