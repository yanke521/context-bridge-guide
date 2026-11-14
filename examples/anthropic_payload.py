"""Preview a synthetic Messages payload. Network requires an explicit --send flag."""
from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from context_core import PackedContext, background_text, recall_text
from demo import make_demo_context


def build_payload(ctx: PackedContext, model: str, *, cache_mode: str = 'mark',
                  ttl: str = '5m') -> dict:
    if cache_mode not in ('mark', 'off') or ttl not in ('5m', '1h'):
        raise ValueError('Expected cache mode mark/off and TTL 5m/1h')
    control = {'type': 'ephemeral', 'ttl': ttl}
    system = [{'type': 'text', 'text': ctx.stable}]
    if cache_mode == 'mark':
        system[-1]['cache_control'] = dict(control)
    messages = []
    background = background_text(ctx)
    if background:
        messages.append({'role': 'user', 'content': [{'type': 'text', 'text': background}]})
    for m in ctx.recent:
        if m.role not in ('user', 'assistant'):
            raise ValueError('Text-only example cannot encode a tool protocol message')
        messages.append({'role': m.role, 'content': [{'type': 'text', 'text': m.text}]})
    # This marker never includes the changing clock, channel, or query-specific recall.
    if cache_mode == 'mark' and messages:
        messages[-1]['content'][-1]['cache_control'] = dict(control)
    dynamic = '\n\n'.join(x for x in (ctx.latest.text, ctx.volatile, recall_text(ctx)) if x)
    messages.append({'role': 'user', 'content': [{'type': 'text', 'text': dynamic}]})
    return {'model': model, 'max_tokens': 512, 'system': system, 'messages': messages}


def usage_totals(usage: dict) -> dict:
    plain = int(usage.get('input_tokens') or 0)
    created = int(usage.get('cache_creation_input_tokens') or 0)
    read = int(usage.get('cache_read_input_tokens') or 0)
    total = plain + created + read
    return {'ordinary_input': plain, 'cache_created': created, 'cache_read': read,
            'total_input': total, 'read_ratio': read/total if total else 0.0,
            'output': int(usage.get('output_tokens') or 0)}


def validate_base_url(base: str) -> str:
    parts = urlsplit(base)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Use a root base URL without credentials, query or fragment')
    local = parts.hostname in ('127.0.0.1', 'localhost', '::1')
    if not parts.hostname or not (parts.scheme == 'https' or (local and parts.scheme == 'http')):
        raise ValueError('Use HTTPS, or HTTP only for a local test service')
    if parts.path not in ('', '/'):
        raise ValueError('Base URL must be the root, without /v1/messages')
    return base.rstrip('/')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='Explicitly send ONE real API request')
    parser.add_argument('--cache-mode', choices=('mark', 'off'), default='mark')
    parser.add_argument('--ttl', choices=('5m', '1h'), default='5m')
    args = parser.parse_args()
    model = os.getenv('MODEL_ID', 'your-claude-model')
    payload = build_payload(make_demo_context(), model, cache_mode=args.cache_mode, ttl=args.ttl)
    if not args.send:
        print('Preview only: synthetic data; no network request. Short payload may not meet cache minimums.')
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key or model == 'your-claude-model':
        parser.error('Set ANTHROPIC_API_KEY and MODEL_ID locally before using --send')
    try:
        base = validate_base_url(os.getenv('ANTHROPIC_BASE_URL', 'https://api.anthropic.com'))
        request = Request(base+'/v1/messages', data=json.dumps(payload).encode(), method='POST',
                          headers={'x-api-key': key, 'anthropic-version': '2023-06-01',
                                   'content-type': 'application/json'})
        with urlopen(request, timeout=60) as response:
            body = json.load(response)
        if 'usage' not in body:
            raise ValueError('Response has no usage object')
        print(json.dumps(usage_totals(body['usage']), ensure_ascii=False, indent=2))
    except Exception as exc:
        # Do not echo a request, credential, or arbitrary provider response into logs.
        parser.exit(1, f'Request failed: {type(exc).__name__}; HTTP status={getattr(exc, "code", "unknown")}\n')


if __name__ == '__main__':
    main()
