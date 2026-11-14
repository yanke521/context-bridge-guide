# 02 · API 缓存：稳定内容放前面

## 缓存像什么

每次请求都带着一本资料册。缓存让服务端有机会复用它以前处理过的前半本；如果每轮都在第一页写上新的时间，后面的旧内容也很难沿用上次的前缀。

缓存不会把没发送的往事变成记忆，也不会让已经占满的上下文窗口空出来。省成本和控制上下文长度，需要分别处理。

## 先按变化频率整理资料

| 层 | 典型内容 | 摆放建议 |
|---|---|---|
| 长期稳定 | 核心设定、基础规则 | 最前面，固定顺序 |
| 偶尔更新 | 已确认的长期偏好、工具说明 | 稳定层后面 |
| 阶段更新 | 档案目录、阶段资料 | 独立组织，更新时知道哪段变了 |
| 每轮变化 | 当前时间、渠道、当前问题召回的记忆、临时状态 | 历史之后，靠近最新输入 |

应用可以先统一构建这些层，再由 API、CC 适配器分别编码。不要在两个分支各自维护一套人设和记忆拼装。

Anthropic 明确说明缓存覆盖 `tools → system → messages` 的前缀，支持显式断点及不同 TTL；具体能力随模型和服务变化。[Prompt caching 官方文档](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

所以，单纯把时间从 system 的开头移到末尾，仍可能破坏后面的历史缓存。更合适的结构是：

```text
固定工具定义
稳定 system
阶段摘要
稳定历史前缀 / 最近原文
这轮的新消息 + 当前时间、渠道、相关记忆
```

## 一个真实踩过的坑

测试时两次调用只隔几秒，时间字符串没变化，缓存看起来很好。实际聊天隔几分钟，时间和临时状态变了，历史又整段重新处理。

验证时，要同时改变真实场景里的变量：跨分钟、追加历史、更新相关记忆、执行多轮工具，以及切换模型。不要用静止的两次请求代替这些测试。

## 历史窗口也要尽量稳定

如果每轮都删掉最早一条历史，历史的开头就一直变。可以把窗口起点按小批次对齐，再保证它不突破预算。这样一段时间内请求前缀保持相同，跨过边界才整体移动一次。

对齐有代价：它可能多保留一些内容。遇到大段代码、网页或附件文本时，必须重新检查预算，不能假定“多二十条肯定很短”。原文与附件保留在账本里，请求视图可以放简短说明和可检索引用。

## 工具轮要照顾新的前缀

本轮第一次请求之后，模型又可能追加：

```text
assistant: tool_use
user: tool_result
assistant: 下一次 tool_use
user: 下一次 tool_result
```

这些新内容也会被后续工具轮重读。缓存标记应随新的可缓存块推进，同时撤下本轮不再需要的旧标记；全请求的断点数量要一起计算。不同 TTL 混用时，要遵守服务端排序规则；最小实现先用统一 TTL。

缓存断点上限、回溯范围、最小缓存长度及 TTL 排序都有产品约束，接入时查对应版本文档，不把某次测试的数字当成所有中转的约定。[官方缓存约束与示例](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#explicit-cache-breakpoints)

## 中转站要实测

地址兼容 Messages API，不代表缓存语义和扣费口径完全一致。可以把端点能力记录成：

- `mark`：按已验证的显式断点方式发送。
- `provider-managed`：不附加显式标记，观察提供方自己的复用行为。
- `unknown/off`：尚未证实，按未命中处理收益估算。

这几个名字是应用自己的能力分类；`provider-managed` 不等于 Anthropic 请求体里的 automatic caching 开关。

最小实验是“同端点、同模型、同内容、同工具、同参数”的首次与再次请求，再补上改变一个变量的对照组。等待间隔、实际账单和模型版本都应记录下来。

## 看哪些数字

对遵循 Anthropic usage 语义的接口：

```python
total_input = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
read_ratio = cache_read_input_tokens / total_input if total_input else 0
```

读缓存比例和费用节省比例不是同一个数字。费用还取决于写入、读取、普通输入和输出各自单价；中转的账单也可能另有规则。[官方 usage 口径](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-do-i-calculate-total-input-tokens-from-the-usage-fields)

对应例子：[anthropic_payload.py](../examples/anthropic_payload.py)。默认只展示请求；例子短，不保证达到模型最小缓存长度，也没有假造缓存命中数据。
