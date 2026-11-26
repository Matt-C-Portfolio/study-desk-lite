import unittest
from study_desk.topic_groups import topic_catalog, assemble_groups


class TopicGroupTests(unittest.TestCase):
    def test_merge_preserves_details_examples_and_sources(self):
        ledger = [dict(source_id='S1', topics=[dict(title='Division', gist='Python 2.',
            bullets=['Integer division truncates.'], examples=['3 / 5 → 0'])]),
            dict(source_id='S2', topics=[dict(title='Real division', gist='Use a float.',
            bullets=['Integer division truncates.', 'Float division differs.'], examples=['3 / 5.0 → 0.6'])])]
        catalog = topic_catalog(ledger)
        result, issues = assemble_groups(dict(groups=[dict(title='Division', topic_ids=['S1:T1', 'S2:T1'])]), catalog)
        topic = result['topics'][0]
        self.assertEqual(topic['examples'], ['3 / 5 → 0', '3 / 5.0 → 0.6'])
        self.assertEqual(topic['bullets'], ['Integer division truncates.', 'Float division differs.'])
        self.assertEqual(topic['gist'], 'Python 2.\n\nUse a float.')
        self.assertEqual(topic['source_ids'], ['S1', 'S2'])
        self.assertFalse(issues)

    def test_bad_ids_do_not_drop_content_or_hide_mistakes(self):
        catalog = topic_catalog([dict(source_id='S1', topics=[
            dict(title=str(i), gist=str(i), bullets=[str(i)], examples=[str(i)]) for i in range(2)])])
        result, issues = assemble_groups(dict(groups=[dict(title='Group', topic_ids=['S1:T1', 'S1:T1', 'bad'])]), catalog)
        self.assertEqual([t['examples'] for t in result['topics']], [['0'], ['1']])
        self.assertEqual(len(issues), 3)
