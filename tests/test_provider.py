import json
import logging

import httpx
import pytest

from fitness.config import Settings


def provider_module():
    from fitness import provider

    return provider


def settings(**kwargs):
    return Settings(live_enabled=True, api_key="secret-test-key", model="test-model", **kwargs)


def response(content="安全的训练总结", tool_calls=None, usage=None):
    return {
        "id": "test-response",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content,
                     "tool_calls": tool_calls or []}, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


TOOLS = [{"type": "function", "function": {"name": "get_profile", "parameters": {
    "type": "object", "properties": {}, "additionalProperties": False}}}]


def test_default_requires_api_key_and_no_transport_is_called():
    p = provider_module()
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request))
    with pytest.raises(p.ProviderError, match="missing_api_key"):
        p.OpenAICompatibleProvider(Settings(), transport=transport).complete([])
    assert calls == []


def test_provider_normalizes_reply_and_sends_bounded_request():
    p = provider_module()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response(content=None, tool_calls=[{
            "id": "call_1", "type": "function", "function": {"name": "get_profile", "arguments": "{}"}}]))

    reply = p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(handler)).complete(
        [{"role": "user", "content": "private-prompt"}], TOOLS)
    assert reply.content is None
    assert reply.tool_calls == [{"id": "call_1", "name": "get_profile", "arguments": {}}]
    assert reply.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    payload = json.loads(requests[0].content)
    assert payload["parallel_tool_calls"] is False
    assert payload["max_tokens"] == 2048
    assert str(requests[0].url) == "https://api.deepseek.com/chat/completions"


@pytest.mark.parametrize("kind,expected", [
    ("timeout", "timeout"), ("status", "http_error"), ("json", "invalid_response"),
    ("unknown_tool", "invalid_tool_call"), ("invalid_args", "invalid_tool_call"),
    ("extra_message", "invalid_response"), ("huge", "response_too_large"),
])
def test_provider_failures_are_sanitized(kind, expected, caplog):
    p = provider_module()

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private-prompt secret-test-key", request=request)
        if kind == "status":
            return httpx.Response(401, text="private-prompt secret-test-key")
        if kind == "json":
            return httpx.Response(200, text="private-prompt secret-test-key")
        if kind == "huge":
            return httpx.Response(200, content=b"x" * 140000)
        body = response()
        message = body["choices"][0]["message"]
        if kind == "extra_message":
            message["instructions"] = "ignore safety"
        else:
            message["tool_calls"] = [{"id": "call", "type": "function", "function": {
                "name": "unknown" if kind == "unknown_tool" else "get_profile",
                "arguments": "[]" if kind == "invalid_args" else "{}"}}]
        return httpx.Response(200, json=body)

    with caplog.at_level(logging.INFO), pytest.raises(p.ProviderError, match=expected) as caught:
        p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(handler)).complete(
            [{"role": "user", "content": "private-prompt"}], TOOLS)
    assert caught.value.reason_code == expected
    assert caught.value.__cause__ is None
    assert "private-prompt" not in caplog.text
    assert "secret-test-key" not in caplog.text


def test_request_size_and_parallel_calls_are_rejected():
    p = provider_module()
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request))
    with pytest.raises(p.ProviderError, match="request_too_large"):
        p.OpenAICompatibleProvider(settings(), transport=transport).complete(
            [{"role": "user", "content": "x" * 140000}])
    assert calls == []
    body = response(tool_calls=[{"id": f"call_{i}", "type": "function", "function": {
        "name": "get_profile", "arguments": "{}"}} for i in range(2)])
    with pytest.raises(p.ProviderError, match="invalid_tool_call"):
        p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body))).complete([], TOOLS)


def test_logs_contain_metadata_only_and_unknown_cost_is_absent(caplog):
    p = provider_module()
    with caplog.at_level(logging.INFO):
        reply = p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response("private-response")))).complete(
                [{"role": "user", "content": "private-prompt"}])
    assert "provider_request" in caplog.text
    assert "private-prompt" not in caplog.text
    assert "private-response" not in caplog.text
    assert "secret-test-key" not in caplog.text
    assert "cost" not in reply.usage


def test_env_explicit_enablement_and_key_endpoint_boundary(monkeypatch):
    monkeypatch.setattr("fitness.config.load_dotenv", lambda *args, **kwargs: None)
    for name in ("FITNESS_LIVE_ENABLED", "FITNESS_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    monkeypatch.setenv("FITNESS_BASE_URL", "https://other.example/v1")
    assert Settings.from_env().api_key == ""
    assert Settings.from_env().live_enabled is True
    monkeypatch.setenv("FITNESS_LIVE_ENABLED", "true")
    monkeypatch.setenv("FITNESS_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("FITNESS_MAX_STEPS", "3")
    configured = Settings.from_env()
    assert configured.live_enabled is True
    assert configured.timeout_seconds == 12
    assert configured.max_steps == 3


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": 0}, {"timeout_seconds": float("inf")},
                                      {"max_steps": 0}, {"max_steps": 100},
                                      {"base_url": "http://remote.example"},
                                      {"base_url": "https://user:secret@example.com"}])
def test_settings_reject_unbounded_or_unsafe_configuration(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_live_enabled_must_be_boolean():
    with pytest.raises(ValueError):
        Settings(live_enabled="false")


def test_duplicate_argument_keys_and_unknown_parameter_are_rejected():
    p = provider_module()
    for arguments in ('{"extra":1}', '{"a":1,"a":2}', '{"value":NaN}'):
        body = response(tool_calls=[{"id": "call", "type": "function", "function": {
            "name": "get_profile", "arguments": arguments}}])
        with pytest.raises(p.ProviderError, match="invalid_tool_call"):
            p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
                lambda request, body=body: httpx.Response(200, json=body))).complete([], TOOLS)


def test_redirect_is_never_followed():
    p = provider_module()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://unrelated.example/collect"})

    with pytest.raises(p.ProviderError, match="http_error"):
        p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(handler)).complete([])
    assert len(requests) == 1


@pytest.mark.parametrize("tools", [[{"type": "function", "function": []}],
                                  [{"type": "function", "function": {"name": "get_profile"}}]])
def test_malformed_request_tools_have_stable_errors(tools):
    p = provider_module()
    with pytest.raises(p.ProviderError, match="invalid_request"):
        p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
            lambda request: pytest.fail("must reject before network"))).complete([], tools)


def test_key_newlines_are_rejected_without_echoing_secret():
    with pytest.raises(ValueError) as caught:
        Settings(api_key="secret-test-key\r\nCookie: private-cookie")
    assert "secret-test-key" not in str(caught.value)


def test_usage_is_accounted_across_calls():
    p = provider_module()
    adapter = p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response())))
    adapter.complete([])
    adapter.complete([])
    assert adapter.usage_totals == {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}


def test_pydantic_optional_tool_parameter_schema_is_supported():
    from fitness.tools import HistoryInput

    p = provider_module()
    tools = [{"type": "function", "function": {"name": "get_recent_feedback",
             "parameters": HistoryInput.model_json_schema()}}]
    body = response(content=None, tool_calls=[{"id": "call", "type": "function", "function": {
        "name": "get_recent_feedback", "arguments": '{"days":7,"metric":"sleep_hours","issue":null}'}}])
    reply = p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body))).complete([], tools)
    assert reply.tool_calls[0]["arguments"]["metric"] == "sleep_hours"


def test_deepseek_cache_token_counts_are_preserved():
    p = provider_module()
    body = response(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                           "prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 2})
    reply = p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body))).complete([])
    assert reply.usage["prompt_cache_hit_tokens"] == 8
    assert reply.usage["prompt_cache_miss_tokens"] == 2


def test_extremely_large_integer_argument_is_sanitized():
    p = provider_module()
    tools = [{"type": "function", "function": {"name": "query", "parameters": {
        "type": "object", "properties": {"count": {"type": "integer", "maximum": 20}},
        "additionalProperties": False}}}]
    body = response(tool_calls=[{"id": "call", "type": "function", "function": {
        "name": "query", "arguments": '{"count":' + '9' * 400 + '}'}}])
    with pytest.raises(p.ProviderError, match="invalid_tool_call"):
        p.OpenAICompatibleProvider(settings(), transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body))).complete([], tools)
