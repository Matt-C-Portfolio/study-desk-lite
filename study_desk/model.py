"""One HTTP boundary to the local model; no database or graph logic."""

import json
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


class ModelOutputError(ValueError):
    def __init__(self, message, output):
        super().__init__(message)
        self.output = output


class LocalModel:
    def __init__(self, base_url):
        self.seed = None
        if urlsplit(base_url).hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('The model URL must point to localhost.')
        self.url = base_url.rstrip('/') + '/v1/chat/completions'

    def complete(self, prompt, on_token=None, json_mode=False, max_tokens=6000):
        messages = [{'role': 'user', 'content': prompt}]
        base = self.url.removesuffix('/v1/chat/completions')

        def post(path, data):
            req = Request(
                base + path,
                data=json.dumps(data).encode(),
                headers={'Content-Type': 'application/json'},
            )
            with urlopen(req, timeout=30) as response:
                return json.load(response)

        # Use the loaded model's own chat template and tokenizer; never truncate evidence.
        rendered = post('/apply-template', {'messages': messages})['prompt']
        input_tokens = len(post('/tokenize', {'content': rendered, 'add_special': True})['tokens'])
        available = 32768 - input_tokens - 512
        if available < 1024:
            raise ValueError(
                'Lecture content exceeds the local context budget. No evidence was truncated.'
            )
        output_tokens = min(max_tokens, available)
        self.request_info = dict(
            input_tokens=input_tokens,
            requested_output_tokens=max_tokens,
            output_tokens=output_tokens,
            context=32768,
            reserved_tokens=512,
        )
        payload = {
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.6,
            'max_tokens': output_tokens,
            'stream': bool(on_token),
        }
        if self.seed is not None:
            payload['seed'] = self.seed
        self.request_info['seed'] = self.seed
        if json_mode:
            payload['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'study_pass',
                    'strict': True,
                    'schema': json_mode if isinstance(json_mode, dict) else {'type': 'object'},
                },
            }
        body = json.dumps(payload).encode()
        req = Request(self.url, data=body, headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=600) as response:
            if on_token:
                content, count, finish = '', 0, None
                for line in response:
                    if not line.startswith(b'data: '):
                        continue
                    payload = line[6:].strip()
                    if payload == b'[DONE]':
                        break
                    event = json.loads(payload)
                    if 'error' in event:
                        raise ValueError(str(event['error']))
                    for choice in event.get('choices', []):
                        delta = choice.get('delta', {})
                        content += delta.get('content') or ''
                        if delta.get('content') or delta.get('reasoning_content'):
                            count += 1
                            on_token(count)
                        finish = choice.get('finish_reason') or finish
                if finish is None:
                    raise ModelOutputError(
                        'Model stream ended before completion. Partial output is saved.', content
                    )
                result = {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}
            else:
                result = json.load(response)
        content = result['choices'][0]['message'].get('content') or ''
        # Some runtimes return reasoning in content; others use reasoning_content.
        if '</think>' in content:
            content = content.split('</think>', 1)[1]
        if result['choices'][0].get('finish_reason') == 'length':
            raise ModelOutputError(
                'Model output hit its token limit. Partial output is saved.', content
            )
        if not content.strip():
            raise ValueError('The model returned no final answer.')
        return content.strip()
