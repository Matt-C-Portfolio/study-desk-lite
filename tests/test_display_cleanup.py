import copy
import unittest
from study_desk.lecture_document import clean_display


class DisplayCleanupTests(unittest.TestCase):
    def guide(self, **overrides):
        block = dict(type='bullets', body='', items=[], caption='')
        block.update(overrides)
        return {'sections': [{'title': 'Example', 'subsections': [{'blocks': [block]}]}]}

    def block(self, result):
        return result['sections'][0]['subsections'][0]['blocks'][0]

    def test_duplicate_body_and_items_preserve_original(self):
        guide = self.guide(body='* Forms the heart of modern computers by executing instructions.', items=['Forms the heart of modern computers', 'Does not execute instructions.'])
        original = copy.deepcopy(guide)
        result, changes = clean_display(guide)
        self.assertEqual(guide, original)
        self.assertEqual(self.block(result)['body'], '')
        self.assertEqual(len(self.block(result)['items']), 2)
        self.assertTrue(changes)

    def test_cutoff_keeps_complete_sentences(self):
        guide = self.guide(caption='A complete sentence. ' + 'x' * 479)
        result, changes = clean_display(guide)
        self.assertEqual(self.block(result)['caption'], 'A complete sentence.')
        self.assertTrue(changes)

    def test_inline_numbered_list(self):
        result, _ = clean_display(self.guide(caption='Primitives: 1. Read. 2. Write. 3. Move.'))
        self.assertEqual(self.block(result)['caption'], 'Primitives:\n\n1. Read.\n2. Write.\n3. Move.')

    def test_code_and_complete_caption_unchanged(self):
        guide = self.guide(type='code', body='print(1)\nprint(1)', caption='Print twice.')
        result, changes = clean_display(guide)
        self.assertEqual(result, guide)
        self.assertEqual(changes, [])
