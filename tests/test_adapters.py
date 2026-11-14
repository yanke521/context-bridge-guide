from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'examples'))
from anthropic_payload import build_payload, usage_totals, validate_base_url
from cc_command import build_cc_plan
from context_core import Memory
from demo import make_demo_context


class AdapterTests(unittest.TestCase):
    def test_clock_and_recall_do_not_change_cached_history_prefix(self):
        ctx = make_demo_context()
        changed = replace(ctx, volatile='不同时间、不同渠道说明', recalled=(
            Memory('m1', '新召回内容', ('新',), ('source-1',)),))
        one, two = build_payload(ctx, 'demo'), build_payload(changed, 'demo')
        self.assertEqual(one['system'], two['system'])
        self.assertEqual(one['messages'][:-1], two['messages'][:-1])
        self.assertNotEqual(one['messages'][-1], two['messages'][-1])
        self.assertNotIn('cache_control', one['messages'][-1]['content'][0])

    def test_cache_mode_off_omits_markers(self):
        payload = build_payload(make_demo_context(), 'demo', cache_mode='off')
        self.assertNotIn('cache_control', json.dumps(payload))

    def test_only_expected_markers_and_consistent_ttl(self):
        payload = build_payload(make_demo_context(), 'demo', ttl='1h')
        markers = []
        def visit(value):
            if isinstance(value, dict):
                if 'cache_control' in value:
                    markers.append(value['cache_control'])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(payload)
        self.assertEqual(len(markers), 2)
        self.assertTrue(all(m == {'type': 'ephemeral', 'ttl': '1h'} for m in markers))

    def test_latest_only_appears_once(self):
        ctx = make_demo_context()
        payload = build_payload(ctx, 'demo')
        self.assertEqual(json.dumps(payload, ensure_ascii=False).count(ctx.latest.text), 1)

    def test_cc_uses_stdin_without_resuming_or_exposing_credentials(self):
        ctx = make_demo_context()
        secret = 'TEST_ONLY_SECRET_VALUE'
        plan = build_cc_plan(ctx, model='demo', base_url='https://gateway.example',
                             api_key=secret, config_dir='./runtime/test-cc',
                             inherited_env={'ANTHROPIC_AUTH_TOKEN': 'other', 'CLAUDE_MODEL': 'stale',
                                            'CLAUDECODE': '1', 'PATH': '/usr/bin'})
        self.assertNotIn('--resume', plan.argv)
        self.assertIn('--no-session-persistence', plan.argv)
        self.assertNotIn('--dangerously-skip-permissions', plan.argv)
        self.assertEqual(plan.argv[plan.argv.index('--tools')+1], 'none')
        self.assertNotIn(secret, json.dumps(plan.preview()))
        self.assertNotIn(secret, repr(plan))
        self.assertEqual(plan.env['ANTHROPIC_API_KEY'], secret)
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', plan.env)
        self.assertNotIn('CLAUDE_MODEL', plan.env)
        self.assertEqual(plan.env['DISABLE_COMPACT'], '1')
        stdin = json.loads(plan.stdin)
        self.assertEqual(stdin['type'], 'user')
        self.assertIn(ctx.latest.text, stdin['message']['content'][0]['text'])
        self.assertNotIn(ctx.latest.text, ' '.join(plan.argv))

    def test_long_user_input_is_not_a_command_argument(self):
        ctx = make_demo_context()
        text = 'LONG_INPUT_'+'x'*150000
        ctx = replace(ctx, latest=replace(ctx.latest, text=text))
        plan = build_cc_plan(ctx, model='demo', base_url='https://gateway.example',
                             api_key='TEST_ONLY', config_dir='./runtime/test', inherited_env={})
        self.assertIn(text, plan.stdin)
        self.assertTrue(all(len(arg) < 10000 for arg in plan.argv))

    def test_usage_ratio_is_based_on_all_input_categories(self):
        totals = usage_totals({'input_tokens': 10, 'cache_creation_input_tokens': 20,
                               'cache_read_input_tokens': 70, 'output_tokens': 4})
        self.assertEqual(totals['total_input'], 100)
        self.assertAlmostEqual(totals['read_ratio'], 0.7)
        self.assertEqual(usage_totals({})['read_ratio'], 0)

    def test_base_url_validation(self):
        self.assertEqual(validate_base_url('https://gateway.example/'), 'https://gateway.example')
        self.assertEqual(validate_base_url('http://127.0.0.1:9000'), 'http://127.0.0.1:9000')
        for bad in ('http://gateway.example', 'https://u:p@gateway.example',
                    'https://gateway.example/v1/messages', 'https://gateway.example/?k=value'):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                validate_base_url(bad)


if __name__ == '__main__':
    unittest.main()
