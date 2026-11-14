from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sys
from threading import Event
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'examples'))
from context_core import (ContextBuilder, ConversationService, Inbound, Memory, MemoryStore,
                          Message, estimate_history, render_cc_input)


def history(turns=12):
    return tuple(Message(f'{i}-{role}', f'turn-{i}', role,
                         f'虚构事件 {i} '+('reference '*12), 'web')
                 for i in range(turns) for role in ('user', 'assistant'))


def latest():
    return Message('latest', 'latest-turn', 'user', '唯一的新问题', 'phone')


class ContextTests(unittest.TestCase):
    def builder(self, summarizer=None):
        return ContextBuilder('固定规则', summarizer or (lambda rows: '虚构摘要'),
                              trigger=500, tail_budget=200, align_turns=2)

    def test_short_history_is_preserved(self):
        rows = history(1)
        ctx = self.builder().pack('a', rows, latest())
        self.assertIsNone(ctx.summary)
        self.assertEqual(ctx.recent, rows)

    def test_compression_preserves_original_and_complete_turns(self):
        rows = history()
        snapshot = tuple(rows)
        ctx = self.builder().pack('a', rows, latest())
        self.assertIsNotNone(ctx.summary)
        self.assertEqual(rows, snapshot)
        self.assertEqual(tuple(ctx.summary.source_ids)+tuple(m.id for m in ctx.recent),
                         tuple(m.id for m in rows))
        self.assertEqual(ctx.recent[0].role, 'user')
        self.assertEqual(ctx.recent[-1].role, 'assistant')
        self.assertLessEqual(estimate_history(ctx.recent), 200)

    def test_summary_cache_reuses_exact_input(self):
        calls = []
        builder = self.builder(lambda rows: calls.append(rows) or '摘要')
        one = builder.pack('a', history(), latest())
        two = builder.pack('a', history(), latest())
        self.assertFalse(one.summary_reused)
        self.assertTrue(two.summary_reused)
        self.assertEqual(len(calls), 1)

    def test_same_count_edited_content_and_other_conversation_do_not_share_summary(self):
        calls = []
        builder = self.builder(lambda rows: calls.append(rows) or '摘要')
        rows = history()
        builder.pack('a', rows, latest())
        edited = (replace(rows[0], text='不同事实 '+rows[0].text),)+rows[1:]
        builder.pack('a', edited, latest())
        builder.pack('b', rows, latest())
        self.assertEqual(len(calls), 3)

    def test_summary_failure_is_visible(self):
        rows = history()
        with self.assertRaises(RuntimeError):
            self.builder(lambda rows: '').pack('a', rows, latest())
        self.assertEqual(len(rows), 24)

    def test_single_large_turn_is_kept_whole_and_flagged(self):
        rows = history(1)+(Message('huge-u', 'huge', 'user', 'x'*1500, 'web'),
                           Message('huge-a', 'huge', 'assistant', 'y'*1500, 'web'))
        ctx = self.builder().pack('a', rows, latest())
        self.assertTrue(ctx.tail_over_budget)
        self.assertEqual(tuple(m.id for m in ctx.recent), ('huge-u', 'huge-a'))

    def test_latest_message_cannot_be_duplicated_in_history(self):
        with self.assertRaises(ValueError):
            self.builder().pack('a', (latest(),), latest())

    def test_recall_scoped_and_carries_provenance(self):
        store = MemoryStore()
        item = Memory('m1', '周五检查项目', ('检查',), ('source-1',))
        store.put('a', item)
        self.assertEqual(store.search('a', '检查几点'), (item,))
        self.assertEqual(store.search('b', '检查几点'), ())
        self.assertEqual(store.search('a', '检查几点', limit=0), ())
        ctx = self.builder().pack('a', (), latest(), (item,))
        self.assertIn('source-1', render_cc_input(ctx))


class ServiceTests(unittest.TestCase):
    def service(self):
        return ConversationService(ContextBuilder('规则', lambda rows: '摘要'))

    def test_channel_and_engine_switch_use_the_same_ledger(self):
        service = self.service()
        service.handle(Inbound('c', '1', 'web', '项目代号 LIME-73'), 'api', lambda ctx: '已记录约定')
        seen = []
        service.handle(Inbound('c', '2', 'phone', '继续'), 'cc-family',
                       lambda ctx: seen.append(ctx) or '接上了')
        self.assertEqual(len(seen[0].recent), 2)
        self.assertEqual(seen[0].recent[0].text, '项目代号 LIME-73')
        self.assertEqual(seen[0].recent[1].text, '已记录约定')
        self.assertEqual(service.snapshot('c')[-1].engine, 'cc-family')

    def test_duplicate_delivery_does_not_call_engine_again(self):
        service, calls = self.service(), []
        event = Inbound('c', '1', 'web', '同一条消息')
        generate = lambda ctx: calls.append(ctx) or '回答'
        service.handle(event, 'api', generate)
        result = service.handle(event, 'cc-family', generate)
        self.assertTrue(result.duplicate)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(service.snapshot('c')), 2)

    def test_different_channels_can_reuse_a_source_id(self):
        service = self.service()
        for channel in ('web', 'phone'):
            service.handle(Inbound('c', '1', channel, channel), 'api', lambda ctx: '回答')
        self.assertEqual(len(service.snapshot('c')), 4)

    def test_failed_generation_retry_does_not_duplicate_user(self):
        service = self.service()
        event = Inbound('c', '1', 'web', '保留这条输入')
        def fail(ctx):
            raise RuntimeError('synthetic error')
        with self.assertRaises(RuntimeError):
            service.handle(event, 'api', fail)
        self.assertEqual(len(service.snapshot('c')), 1)
        service.handle(event, 'api', lambda ctx: '重试成功')
        self.assertEqual([m.role for m in service.snapshot('c')], ['user', 'assistant'])

    def test_same_source_id_with_changed_content_is_rejected(self):
        service = self.service()
        service.handle(Inbound('c', '1', 'web', '原内容'), 'api', lambda ctx: '回答')
        with self.assertRaises(ValueError):
            service.handle(Inbound('c', '1', 'web', '变了'), 'api', lambda ctx: '回答')

    def test_conversations_are_isolated(self):
        service = self.service()
        service.handle(Inbound('a', '1', 'web', '只属于 A'), 'api', lambda ctx: '回答')
        service.handle(Inbound('b', '1', 'web', '只属于 B'), 'api',
                       lambda ctx: self.assertEqual(ctx.recent, ()) or '回答')
        self.assertNotIn('只属于 A', str(service.snapshot('b')))

    def test_entire_turns_are_serialized(self):
        service = self.service()
        entered, release = Event(), Event()
        def first(ctx):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test synchronization timeout')
            return '第一轮最终结果'
        def second(ctx):
            self.assertEqual(ctx.recent[-1].text, '第一轮最终结果')
            return '第二轮接上'
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(service.handle, Inbound('c', '1', 'web', '第一条'), 'api', first)
            self.assertTrue(entered.wait(3))
            two = pool.submit(service.handle, Inbound('c', '2', 'phone', '第二条'), 'cc', second)
            release.set()
            one.result(timeout=3)
            two.result(timeout=3)
        self.assertEqual(len(service.snapshot('c')), 4)


if __name__ == '__main__':
    unittest.main()
