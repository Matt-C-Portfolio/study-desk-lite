"""Optional OpenAI backend. The key is read from environment or user configuration."""

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .model import ModelOutputError

MODELS = ['gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-terra', 'gpt-5.6-luna']
STAGES = ['Extract', 'Consolidate', 'Review', 'Format']
PRICES = {'gpt-5.6-luna': (0.20, 0.02, 1.20), 'gpt-5.6-terra': (2.0, 0.20, 12.0)}
KEY_FILE = Path.home() / '.config' / 'study-desk-lite' / 'openai.key'


def api_key():
    return os.environ.get('OPENAI_API_KEY', '').strip() or (
        KEY_FILE.read_text(encoding='utf-8').strip() if KEY_FILE.is_file() else ''
    )


class OpenAIModel:
    def __init__(self, folder):
        self.key = api_key()
        if not self.key:
            raise ValueError('OpenAI key is not configured on this computer.')
        self.folder = Path(folder)
        self.stage = 0
        self.calls = []

    @property
    def cost(self):
        return sum(call['estimated_cost_usd'] for call in self.calls)

    def complete(self, prompt, on_token=None, json_mode=False, max_tokens=6000):
        model = MODELS[self.stage]
        number = len(self.calls) + 1
        payload = dict(
            model=model,
            input=prompt,
            reasoning={'effort': 'low'},
            store=False,
            max_output_tokens=max_tokens,
            prompt_cache_options={'mode': 'explicit'},
            text={
                'format': {
                    'type': 'json_schema',
                    'name': 'study_pass',
                    'strict': True,
                    'schema': json_mode,
                }
            },
        )

        def save(name, data):
            (self.folder / name).write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8'
            )

        save(f'api-call-{number:03d}-request.json', payload)
        request = Request(
            'https://api.openai.com/v1/responses',
            data=json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'},
        )
        start = time.monotonic()
        try:
            with urlopen(request, timeout=600) as response:
                data = json.load(response)
        except HTTPError as exc:
            # Never include request headers, credentials, or server echoes in errors.
            raise RuntimeError(
                f'OpenAI request failed (HTTP {exc.code}). Check account credits and API access.'
            ) from None
        save(f'api-call-{number:03d}-response.json', data)
        usage = data.get('usage', {})
        inp, out = usage.get('input_tokens', 0), usage.get('output_tokens', 0)
        details = usage.get('input_tokens_details', {})
        cached, writes = details.get('cached_tokens', 0), details.get('cache_write_tokens', 0)
        a, b, c = PRICES[model]
        cost = ((inp - cached - writes) * a + cached * b + writes * a * 1.25 + out * c) / 1e6
        self.request_info = dict(
            stage=STAGES[self.stage],
            model=model,
            seconds=round(time.monotonic() - start, 3),
            usage=usage,
            estimated_cost_usd=cost,
            status=data.get('status'),
        )
        self.calls.append(self.request_info)
        save(
            'api-usage.json',
            dict(
                calls=self.calls,
                estimated_cost_usd=self.cost,
                prices_per_million=PRICES,
                pricing_checked='2026-10-27',
                pricing_source='https://developers.openai.com/api/docs/pricing',
                cost_basis='Token usage estimate, not billing receipt',
            ),
        )
        answer = ''.join(
            p.get('text', '')
            for item in data.get('output', [])
            if item.get('type') == 'message'
            for p in item.get('content', [])
            if p.get('type') == 'output_text'
        )
        if data.get('status') != 'completed' or not answer:
            raise ModelOutputError(
                'OpenAI response incomplete. Partial output and usage are saved.', answer
            )
        return answer
