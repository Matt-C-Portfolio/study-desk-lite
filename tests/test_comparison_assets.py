"""Comparison assets stay explicit, local-only, and independent of generation."""
import importlib.util
import json
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import patch

from study_desk import ui


class ComparisonAssetTests(TestCase):
    def setUp(self):
        with patch('study_desk.processing.Processor'):
            self.server = ui.make_server('unused', 0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def get(self, path, headers=None):
        with closing(HTTPConnection('127.0.0.1', self.server.server_port)) as connection:
            connection.request('GET', path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_only_named_assets_are_served_with_existing_policy(self):
        for name in ('comparison-cohort', 'answer-comparison-data'):
            with self.subTest(name=name):
                path = f'/data/{name}.json'
                status, headers, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertEqual(body, (ui.PAGE.parent / path[1:]).read_bytes())
                self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        for path in ('/data/other.json', '/data/../index.html', '/data/%2e%2e/index.html'):
            self.assertEqual(self.get(path)[0], 404)

    def test_host_and_origin_checks_apply_to_json(self):
        path = '/data/comparison-cohort.json'
        self.assertEqual(self.get(path, {'Host': 'example.com'})[0], 403)
        self.assertEqual(self.get(path, {'Origin': 'https://example.com'})[0], 403)

    def test_missing_asset_returns_error_instead_of_empty_results(self):
        with TemporaryDirectory() as folder, patch.object(ui, 'PAGE', Path(folder) / 'index.html'):
            status, _, body = self.get('/data/answer-comparison-data.json')
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {'error': 'Comparison data unavailable.'})


class ComparisonPublisherTests(TestCase):
    def test_publishes_metrics_without_rewriting_html_or_answers(self):
        module_path = Path(__file__).resolve().parents[1] / 'evaluation/qa-full-v1/comparison_snapshot.py'
        spec = importlib.util.spec_from_file_location('comparison_snapshot_test', module_path)
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        with TemporaryDirectory() as folder:
            root = Path(folder)
            web = root / 'study_desk/web'
            (web / 'data').mkdir(parents=True)
            page = web / 'index.html'
            page.write_bytes(b'<html>unchanged</html>')
            result = root / 'data/answers/saved/result.json'
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({
                'answer': 'One claim. [S1] [S1] [S9]', 'elapsed': 2.5,
                'estimated_cost_usd': .01,
                'sources': [{'video_id': 1, 'retrieval': 'graph'}, {'video_id': 2}],
            }), encoding='utf-8')
            original = result.read_bytes()
            manifest = {'questions': [{'id': 'q1', 'question': '<example>'}], 'attempts': [
                {'question_id': 'q1', 'model': '14B', 'mode': 'graph', 'status': 'complete', 'job_id': 'saved'},
                {'question_id': 'q1', 'model': '7B', 'mode': 'rag', 'status': 'pending', 'job_id': None},
            ]}
            publisher.publish(root, manifest)
            destination = web / 'data/answer-comparison-data.json'
            data = json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(data['questions'], manifest['questions'])
            self.assertEqual(data['rows'][0], dict(manifest['attempts'][0],
                words=2, seconds=2.5, cost=.01, cited=1, videos=1, graph_passages=1))
            self.assertEqual(data['rows'][1], manifest['attempts'][1])
            self.assertEqual(page.read_bytes(), b'<html>unchanged</html>')
            self.assertEqual(result.read_bytes(), original)
            self.assertFalse(destination.with_suffix('.json.tmp').exists())
            # An update replaces the same JSON asset and keeps array order.
            publisher.publish(root, manifest)
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8'))['rows'], data['rows'])
