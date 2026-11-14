"""Preview a CC invocation. This example never starts a process or executes a tool."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from anthropic_payload import validate_base_url
from context_core import PackedContext, render_cc_input
from demo import make_demo_context


@dataclass
class CCPlan:
    argv: list[str]
    stdin: str
    env: dict[str, str] = field(repr=False)

    def preview(self) -> dict:
        return {'argv': self.argv, 'stdin': self.stdin,
                'configured_environment_names': [
                    'ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'CLAUDE_CONFIG_DIR',
                    'DISABLE_COMPACT', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC']}


def build_cc_plan(ctx: PackedContext, *, model: str, base_url: str, api_key: str,
                  config_dir: str, inherited_env: dict[str, str] | None = None) -> CCPlan:
    base = validate_base_url(base_url)
    env = dict(os.environ if inherited_env is None else inherited_env)
    for name in list(env):
        if name.startswith(('ANTHROPIC_', 'CLAUDE_')) or name == 'CLAUDECODE':
            env.pop(name, None)
    env.update(ANTHROPIC_API_KEY=api_key, ANTHROPIC_BASE_URL=base,
               CLAUDE_CONFIG_DIR=str(Path(config_dir).resolve()), DISABLE_COMPACT='1',
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
    argv = ['claude', '--bare', '-p', '--setting-sources', '', '--strict-mcp-config',
            '--mcp-config', '{"mcpServers":{}}', '--no-session-persistence',
            '--model', model, '--system-prompt', ctx.stable, '--tools', 'none',
            '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose']
    stdin = json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'text', 'text': render_cc_input(ctx)}]}}, ensure_ascii=False)+'\n'
    return CCPlan(argv, stdin, env)


def main():
    # Public placeholders only. Do not read or print the user's existing credentials.
    plan = build_cc_plan(make_demo_context(), model='your-claude-model',
                         base_url='https://gateway.example', api_key='PUBLIC_DEMO_PLACEHOLDER',
                         config_dir='./runtime/isolated-cc', inherited_env={})
    print('Preview only: no Claude Code process, tools, filesystem changes, or network calls.')
    print(json.dumps(plan.preview(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
