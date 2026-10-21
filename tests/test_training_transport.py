import json

import httpx
import pytest

from fitness.config import Settings
from fitness.provider import OpenAICompatibleProvider


def test_training_transport_accepts_bounded_timeout_and_output_override():
    seen = {}
    def handle(request):
        seen.update(json.loads(request.content))
        assert request.extensions['timeout']['read'] == 3
        return httpx.Response(200, json={'choices': [{'message': {
            'role': 'assistant', 'content': '{}'}, 'finish_reason': 'stop'}]})
    provider = OpenAICompatibleProvider(Settings(live_enabled=True, api_key='test'),
        transport=httpx.MockTransport(handle))
    provider.complete([], timeout_seconds=3, max_output_tokens=4096)
    assert seen['max_tokens'] == 4096


def test_run_limits_are_configured_and_validated(monkeypatch):
    monkeypatch.setenv('FITNESS_AGENT_MAX_CALLS', '8')
    settings = Settings.from_env()
    assert settings.agent_max_calls == 8
    with pytest.raises(ValueError):
        Settings(agent_max_calls=True)


def test_training_accepts_deepseek_indexed_batch_with_explicit_limit():
    calls = [{"index": i, "id": f"call_{i}", "type": "function", "function": {
        "name": "read", "arguments": "{}"}} for i in range(2)]
    body = {"choices": [{"message": {"role": "assistant", "content": None,
        "tool_calls": calls}, "finish_reason": "tool_calls"}]}
    from fitness.provider import ProviderError
    tools_schema = [{"type": "function", "function": {"name": "read", "parameters": {
        "type": "object", "properties": {}, "additionalProperties": False}}}]
    adapter = OpenAICompatibleProvider(Settings(live_enabled=True, api_key="test"),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), max_tool_calls=8)
    reply = adapter.complete([], tools_schema)
    assert [call["id"] for call in reply.tool_calls] == ["call_0", "call_1"]
    assert all(set(call) == {"id", "name", "arguments"} for call in reply.tool_calls)
    calls[1]["id"] = "call_0"
    with pytest.raises(ProviderError, match="invalid_tool_call"):
        adapter.complete([], tools_schema)
