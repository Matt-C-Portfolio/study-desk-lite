import io
import json
import unittest
from unittest.mock import patch
from study_desk.model import LocalModel

class BudgetTests(unittest.TestCase):
    def test_local_token_budget_and_endpoint(self):
        calls=[]
        def response(req, timeout):
            calls.append((req.full_url,json.loads(req.data)))
            if req.full_url.endswith('/apply-template'):
                value={'prompt':'rendered chat'}
            elif req.full_url.endswith('/tokenize'):
                value={'tokens':[1]*24000}
            else:
                value={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
            return io.BytesIO(json.dumps(value).encode())
        with patch('study_desk.model.urlopen',side_effect=response):
            model=LocalModel('http://127.0.0.1:8800')
            self.assertEqual(model.complete('test',max_tokens=16000),'{}')
        self.assertEqual(calls[-1][1]['max_tokens'],8256)
        self.assertTrue(all(url.startswith('http://127.0.0.1:8800/') for url,_ in calls))

    def test_overfull_prompt_never_reaches_generation(self):
        calls=[]
        def response(req, timeout):
            calls.append(req.full_url)
            value={'prompt':'large'} if req.full_url.endswith('/apply-template') else {'tokens':[1]*32000}
            return io.BytesIO(json.dumps(value).encode())
        with patch('study_desk.model.urlopen',side_effect=response):
            with self.assertRaisesRegex(ValueError,'No evidence was truncated'):
                LocalModel('http://127.0.0.1:8800').complete('test')
        self.assertEqual(len(calls),2)
