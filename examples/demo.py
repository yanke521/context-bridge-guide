"""Run with python3 examples/demo.py. All responses are offline teaching substitutes."""
from context_core import (ContextBuilder, ConversationService, Inbound, Memory, MemoryStore,
                          PackedContext, render_cc_input)


def teaching_summary(messages):
    """A deterministic keyword extractor for the demo, not an LLM summarizer."""
    facts = [m.text for m in messages if '约定' in m.text or '代号' in m.text]
    return '教学摘要替身；选取明确事实：\n'+'\n'.join(dict.fromkeys(facts)) if facts else '教学摘要替身：较早记录为测试占位内容。'


def teaching_engine(ctx: PackedContext) -> str:
    """Read synthetic evidence deterministically. No model or CC process is called."""
    evidence = render_cc_input(ctx)
    if '几点' in ctx.latest.text or '检查' in ctx.latest.text:
        answer = '约定是周五 16:20。' if '周五 16:20' in evidence else '当前资料里找不到时间。'
    elif '代号' in ctx.latest.text:
        answer = '项目代号 LIME-73。' if 'LIME-73' in evidence else '当前资料里找不到代号。'
    else:
        answer = '离线示例已收到这条消息。'
    print(f'  组装：历史估算={ctx.history_estimate} 摘要={bool(ctx.summary)} '
          f'复用摘要={ctx.summary_reused} 原文={len(ctx.recent)}条 召回={len(ctx.recalled)}条')
    return answer


def make_demo_context():
    from context_core import Message
    builder = ContextBuilder('你是示例助手。区分历史证据、当前事实和用户的新请求。',
                             teaching_summary, trigger=350, tail_budget=130, align_turns=2)
    history = tuple(Message(f'h{i}', f't{i//2}', 'user' if i%2 == 0 else 'assistant',
                            '虚构历史：项目代号 LIME-73。' if i == 0 else '这是离线示例的历史占位文字。'*5,
                            'web') for i in range(16))
    latest = Message('latest', 'latest-turn', 'user', '项目代号是什么？', 'phone')
    return builder.pack('demo-conversation', history, latest, now='2026-11-14T12:00:00Z')


def main():
    print('离线教学演示：无网络、无真实模型、无真实聊天数据。')
    builder = ContextBuilder('你是示例助手；事实须有来源。', teaching_summary,
                             trigger=350, tail_budget=130, align_turns=2)
    memories = MemoryStore()
    service = ConversationService(builder, memories)
    first = Inbound('demo-conversation', 'web-1', 'web', '约定周五 16:20 检查项目，代号 LIME-73。')
    service.handle(first, 'api-demo', teaching_engine)
    memories.put('demo-conversation', Memory('appointment-1', '约定周五 16:20 检查项目。',
                                          ('检查', '几点'), ('web:web-1:user',)))
    for i in range(8):
        service.handle(Inbound('demo-conversation', f'filler-{i}', 'web',
                               '这是虚构的日常占位对话。'*9), 'api-demo', teaching_engine)
    phone = Inbound('demo-conversation', 'phone-1', 'phone', '之前说的检查是几点？')
    print('\n手机接着问：')
    result = service.handle(phone, 'api-demo', teaching_engine)
    print(' ', result.message.text)
    duplicate = service.handle(phone, 'cc-family-demo', teaching_engine)
    print('  重复投递被识别：', duplicate.duplicate)
    print('\n切换到 CC 资料包模式（本例依然用离线替身）：')
    switched = service.handle(Inbound('demo-conversation', 'bridge-1', 'bridge', '项目代号是什么？'),
                              'cc-family-demo', teaching_engine)
    print(' ', switched.message.text)
    print('  同一账本条数：', len(service.snapshot('demo-conversation')))


if __name__ == '__main__':
    main()
