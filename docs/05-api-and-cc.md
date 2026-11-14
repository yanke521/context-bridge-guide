# 05 · API 与 Claude Code 怎么切换

## 先分清模型、接口和 harness

模型负责生成；接口负责收发请求；harness 负责工具执行和多步任务循环。`claude -p` 是以程序方式运行 Claude Code 的入口，`-p` 本身并不要求所有长期记忆都交给 CLI 管理。[程序化运行官方说明](https://code.claude.com/docs/en/headless)

一个应用可以使用三种模式：

| 模式 | 上下文由谁决定 | 主要收益 | 需要承担的工作 |
|---|---|---|---|
| 直接 API | 应用每轮组织请求 | 完整掌握压缩和注入 | 自己维护工具循环 |
| CC 原生续会话 | 应用注入设定，CLI 保留 transcript | 同一任务的工具过程连续 | 监控 CLI 上下文和压缩、会话轮换 |
| 中转驱动 CC，家里组织历史 | 应用每轮准备资料，CLI 完成本轮工具循环 | 自有摘要结构与 CC 工具能力结合 | 明确交接工具结论，控制完整请求容量 |

## 原生续会话怎么交接

应用保存 CLI session ID、稳定设定指纹、上次已消费的账本事件游标。

- 第一次：发送稳定设定、历史资料和当前消息。
- 连续使用：续接该会话，只追加当前动态资料与新消息。
- 期间换到其他引擎：再次回到 CC 时，补入消费游标之后的事件。
- 设定、模型或上下文需要重建：在当前工具回合结束后，用应用自己的账本准备新会话。

用“最后一条标记为 CC 的消息”寻找补课起点，是小系统的一种简化。更稳妥的是记录真正的 `engine_instance_id` 与 `last_consumed_event_id`：一次性 CC 调用和另一条 CC 会话并不共享 transcript，不能都当作“这个会话已经读过”。

原应用的既有 CC 档在上一轮上下文超过 160k 时准备轮换；另有缓存冷却等条件下约 80k 的提前轮换策略。这是项目策略，不是 Claude Code 的通用限制，也不保证某个工具回合内不会先触发 CLI 自己的压缩。

## 家里组织历史的模式

```text
共享账本 → 应用压缩 / 召回 → 本轮完整资料包
                           → 新的 claude -p 调用
                           → 本轮工具循环连续完成
                           → 最终回复、工具结论回到账本
```

每次用户发起新回合，都可以使用独立、无持久 session 的 CLI 调用。同一回合中的多次工具调用仍在同一个进程里运行；不是每调一次工具就重建上下文。

这个模式不依赖 CLI 上一轮 transcript，因此自有摘要不会再被 CLI 的跨轮摘要悄悄替换。代价是前一轮工具的全部原始输出不会自动保留：需要明确保存结果、记录文件引用，下轮必要时重新读取。

## `-p` 的参数例子

当前机器验证过 Claude Code 2.1.280。其他版本先检查 `claude --help`，尤其是 `--bare`、输入输出格式和权限参数。[CLI reference](https://code.claude.com/docs/en/cli-reference)

本仓库的 [cc_command.py](../examples/cc_command.py) 构造：

```text
claude --bare -p
  --setting-sources ""
  --strict-mcp-config --mcp-config '{"mcpServers":{}}'
  --no-session-persistence
  --model <明确的模型名>
  --system-prompt <稳定设定>
  --tools none
  --input-format stream-json
  --output-format stream-json --verbose
```

稳定 system 通过 `--system-prompt` 提供；历史资料和本轮用户输入通过流式 JSON 的标准输入传入，避免把超长聊天放进一个命令行参数。如果 system 本身也很长，应使用对应 CLI 版本支持的文件输入方式。凭据通过子进程环境传递，不放在命令参数、日志或仓库里。默认示例不给工具；接入任务工具时，另行设置允许的工具及权限，不直接照搬跳过所有权限的配置。

`--bare` 会跳过通常自动发现的一些项目说明、技能和连接；需要的能力要显式提供，不能一边关闭发现、一边假定原来的全部扩展仍会加载。[bare mode](https://code.claude.com/docs/en/headless#start-faster-with-bare-mode)

## CC 自己的压缩怎么处理

如果要求摘要结构完全由应用负责，可以对该子进程使用 `DISABLE_COMPACT=1`。这个开关关闭全部压缩，必须同时保证容量管理和失败反馈，不能拿它当作无限上下文开关。[环境变量说明](https://code.claude.com/docs/en/env-vars)

容量检查必须包含 CLI 注入的工具与指令、当前消息、图片、预计输出和本轮工具结果。字符数阈值只能作为保守预检，无法证明请求一定不超窗。超出时应明确失败并保留账本，或者重新整理输入；不要悄悄裁掉记忆。

原生续会话模式仍可保留 CLI 压缩作兜底，两种模式应有独立配置和会话状态。

## 接中转与切模型

使用 API 凭据及 `ANTHROPIC_BASE_URL` 指定兼容网关。只给这次子进程配置地址和模型，避免修改终端全局默认值。读取上游模型列表、支持特性、真实缓存效果，需要单独验证。

Anthropic 提供网关协议说明，同时明确不支持通过网关把 Claude Code 路由给非 Claude 模型。本教程围绕 Claude 模型的兼容接入；其他模型不能仅凭一次文本回复正常就宣称完整兼容。[网关官方说明](https://code.claude.com/docs/en/llm-gateway)

接入测试至少包含：文本、流式事件、工具调用与结果、下一轮续接、图像（若使用）、失败事件、超窗以及原模式回退。CLI 可能在 stdout 的结果事件里报告失败；必须检查 `is_error`、退出码和结果类型，不能把错误句子保存成正常回复。
