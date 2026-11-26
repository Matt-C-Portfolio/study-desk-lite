from database_support import temporary_database, database_for
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import nullcontext
from study_desk.study_pipeline import run, prepare
from study_desk.storage import Store
from study_desk.study_jobs import PassTimings, generate
from study_desk.model import ModelOutputError

TEXT = 'Multiplying a string repeats it.'
CODE = '"hi" * 3'
CHUNKS = [dict(id='S1', text=TEXT, start=0, end=10)]
TOPIC = dict(title='Strings', gist=TEXT, bullets=[TEXT], examples=[CODE])
BLOCK = dict(type='code', title='Example', body=CODE, items=[], latex='', caption='Repeats the string.', language='python')
SECTION = dict(title='Strings', takeaway=TEXT, subsections=[dict(title='Repetition', blocks=[BLOCK])])
ANSWERS = [dict(summary=TEXT, topics=[TOPIC]),
           dict(groups=[dict(title='Strings', topic_ids=['S1:T1'])]),
           dict(observations=['Possible mistake; verify manually.']),
           dict(sections=[SECTION])]

class FakeModel:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = 0
        self.prompts = []
    def complete(self, prompt, on_token=None, json_mode=False, max_tokens=6000):
        self.calls += 1
        self.prompts.append(prompt)
        if on_token:
            on_token(1)
        result = next(self.answers)
        if isinstance(result, Exception):
            raise result
        return json.dumps(result)

class StudyTests(unittest.TestCase):
    def test_typed_blocks_reject_duplicate_fields(self):
        import copy
        from study_desk.lecture_contracts import BLOCK, BLOCK_FIELDS
        from study_desk.lecture_document import validate_guide
        self.assertEqual(len(BLOCK['anyOf']), len(BLOCK_FIELDS))
        for kind in ('bullets', 'steps', 'comparison'):
            value = copy.deepcopy(ANSWERS[3])
            block = value['sections'][0]['subsections'][0]['blocks'][0]
            block.update(type=kind, body='', items=['One fact.'], caption='', language='')
            validate_guide(value)
            block['body'] = 'One fact.'
            with self.assertRaises(ValueError):
                validate_guide(value)

    def test_ceiling_is_flagged_without_trimming(self):
        import copy
        answer = copy.deepcopy(ANSWERS[3])
        caption = 'x' * 500
        answer['sections'][0]['subsections'][0]['blocks'][0]['caption'] = caption
        with temporary_database() as directory:
            output = run(FakeModel(ANSWERS[:3]+[answer]), CHUNKS, directory, lambda *a: None)
            self.assertIn(caption, output.read_text())
            comparison = json.loads((Path(directory)/'comparison.json').read_text())
            self.assertIn('ceiling', comparison['issues'][0]['problem'])
            run(FakeModel([]), CHUNKS, directory, lambda *a: None)
            self.assertTrue(list(Path(directory).glob('notes.*.md')))

    def test_consolidation_revision_reuses_only_extraction(self):
        with temporary_database() as directory:
            run(FakeModel(ANSWERS), CHUNKS, directory, lambda *a: None)
            original = (Path(directory)/'format.json').read_bytes()
            model = FakeModel(ANSWERS[1:])
            reused = []
            with patch('study_desk.study_pipeline.CONSOLIDATE_VERSION', 'test-new'):
                run(model, CHUNKS, directory, lambda *a: None, on_cache=reused.append)
            self.assertEqual(model.calls, 3)
            self.assertEqual(reused, [0])
            archives = list(Path(directory).glob('format.*.json'))
            self.assertTrue(any(p.read_bytes() == original for p in archives))

    def test_format_field_limits(self):
        import copy
        from study_desk.lecture_document import validate_guide
        valid = copy.deepcopy(ANSWERS[3])
        block = valid['sections'][0]['subsections'][0]['blocks'][0]
        block['caption'] = 'x' * 500
        validate_guide(valid)
        block['caption'] += 'x'
        with self.assertRaisesRegex(ValueError, 'character limit'):
            validate_guide(valid)

    def test_rich_document_and_advisory_review(self):
        with temporary_database() as directory:
            model = FakeModel(ANSWERS)
            output = run(model, CHUNKS, directory, lambda *a: None)
            text = output.read_text(encoding='utf-8')
            self.assertIn('```python', text)
            self.assertIn(CODE, text)
            self.assertIn('### Repetition', text)
            self.assertNotIn('Possible mistake', text)
            payload = json.loads(model.prompts[3].split('DATA:\n')[1])
            self.assertEqual(payload['examples'], [CODE])
            self.assertNotIn('observations', payload)
            comparison = json.loads((Path(directory)/'comparison.json').read_text())
            self.assertEqual(comparison['reviews'][0]['observations'], ANSWERS[2]['observations'])

    def test_broken_review_does_not_block_notes(self):
        for review in ({}, ModelOutputError('truncated review', '{partial')):
            with self.subTest(review=review), temporary_database() as directory:
                output = run(FakeModel(ANSWERS[:2]+[review]+ANSWERS[3:]), CHUNKS, directory, lambda *a: None)
                self.assertIn(CODE, output.read_text())
                comparison = json.loads((Path(directory)/'comparison.json').read_text())
                self.assertEqual(comparison['issues'][0]['stage'], 'Review')

    def test_topic_formatting_is_isolated_and_resumable(self):
        with temporary_database() as directory:
            other = dict(title='Variables', gist='Assignment', bullets=['Assignment'], examples=['x = 2'], source_ids=['S1'])
            organized = dict(groups=[dict(title='Strings', topic_ids=['S1:T1']), dict(title='Variables', topic_ids=['S1:T2'])])
            extracted = dict(summary=TEXT, topics=[TOPIC, other])
            model = FakeModel([extracted, organized, ANSWERS[2], ANSWERS[3], RuntimeError('stop')])
            with self.assertRaises(RuntimeError):
                run(model, CHUNKS, directory, lambda *a: None)
            self.assertNotIn('x = 2', model.prompts[3])
            resumed = FakeModel([ANSWERS[3]])
            run(resumed, CHUNKS, directory, lambda *a: None)
            self.assertEqual(resumed.calls, 1)
            self.assertIn('x = 2', resumed.prompts[0])

    def test_partial_extraction_output_survives_retry(self):
        with temporary_database() as directory:
            with self.assertRaises(ModelOutputError):
                run(FakeModel([ModelOutputError('limit', '{partial')]), CHUNKS, directory, lambda *a: None)
            run(FakeModel(ANSWERS), CHUNKS, directory, lambda *a: None)
            responses = list(Path(directory).glob('extract-1.*.response.txt'))
            self.assertEqual(len(responses), 2)
            self.assertIn('{partial', [p.read_text() for p in responses])

    def test_timings_persist_with_results(self):
        with temporary_database() as directory:
            db = database_for(directory)
            transcript = Path(directory)/'transcript.txt'
            transcript.write_text(TEXT)
            store = Store(db)
            video, _ = store.save_url('https://www.youtube.com/watch?v=abcdefghijk')
            store.update_video(video['id'], 'ready', '', str(transcript), 'test')
            store.save_run(video['id'], '1.5B', {'status':'running', 'passes':[{} for _ in range(4)]})
            with patch('study_desk.study_jobs.load_model', return_value=nullcontext(FakeModel(ANSWERS))):
                generate(db, store.video(video['id']), '1.5B')
            result = store.runs(video['id'])['1.5B']
            self.assertEqual(result['status'], 'complete')
            self.assertTrue(all(p['elapsed'] >= 0 for p in result['passes']))
            files = list(Path(result['folder']).glob('timings-*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(len(json.loads(files[0].read_text())['passes']), 4)
            store.close()

    def test_pass_timings_do_not_include_load_or_later_passes(self):
        timer = PassTimings()
        self.assertEqual(timer.update(0, 100), 0)
        self.assertEqual(timer.update(0, 112.5, True), 12.5)
        self.assertEqual(timer.update(1, 115), 0)
        self.assertEqual(timer.update(1, 118, True), 3)
        self.assertEqual(timer.update(0, 120), 12.5)
        timer.reuse(0)
        timer.reuse(0)
        self.assertEqual(timer.cached[0], 2)

    def test_four_passes_and_resume_without_repeating_calls(self):
        with temporary_database() as directory:
            model = FakeModel(ANSWERS)
            events = []
            output = run(model, CHUNKS, directory, lambda *args: events.append(args))
            self.assertEqual(model.calls, 4)
            self.assertIn('0:00–0:10', output.read_text(encoding='utf-8'))
            self.assertEqual(events[-1], (3, 1, 1, 0))
            cached = FakeModel([])
            reused = []
            run(cached, CHUNKS, directory, lambda *args: None, on_cache=reused.append)
            self.assertEqual(cached.calls, 0)
            self.assertEqual(reused, [0, 1, 2, 3])

    def test_failed_format_resumes_at_format(self):
        with temporary_database() as directory:
            with self.assertRaises(RuntimeError):
                run(FakeModel(ANSWERS[:3]+[RuntimeError('interrupted')]), CHUNKS, directory, lambda *a: None)
            model = FakeModel(ANSWERS[3:])
            run(model, CHUNKS, directory, lambda *a: None)
            self.assertEqual(model.calls, 1)

    def test_changed_source_invalidates_cache_identity(self):
        with temporary_database() as directory:
            path = Path(directory)/'transcript.txt'
            path.write_text(TEXT)
            first, chunks = prepare(path)
            self.assertEqual(chunks[0]['text'], TEXT)
            path.write_text(TEXT+' Another sentence.')
            self.assertNotEqual(prepare(path)[0], first)

    def test_models_saved_separately_and_interrupted_runs_recover(self):
        with temporary_database() as directory:
            store = Store(database_for(directory))
            store.save_url('https://www.youtube.com/watch?v=example')
            store.save_run(1,'1.5B',{'status':'complete'})
            store.save_run(1,'14B',{'status':'running'})
            store.recover_runs()
            self.assertEqual(store.runs(1)['1.5B']['status'],'complete')
            self.assertEqual(store.runs(1)['14B']['status'],'error')
            store.close()
