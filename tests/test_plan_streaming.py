import json

import httpx
import pytest

from fitness.config import Settings
from fitness.provider import OpenAICompatibleProvider, ProviderError


def sse(delta=None, finish=None):
    return ('data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta or {},
        'finish_reason': finish}]}, ensure_ascii=False) + '\n\n').encode()


def test_provider_delivers_text_before_upstream_finishes_across_utf8_boundaries():
    seen = []

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            data = sse({'content': '今天练腿'})
            split = data.index('今'.encode()) + 1
            yield data[:split]
            yield data[split:]
            assert seen == ['今天练腿']
            yield sse({'content': '，保持轻量。'})
            yield sse(finish='stop')
            yield b'data: [DONE]\n\n'

    def handler(request):
        assert json.loads(request.content)['stream'] is True
        return httpx.Response(200, stream=Stream())

    reply = OpenAICompatibleProvider(Settings(live_enabled=True, api_key='test'),
        transport=httpx.MockTransport(handler)).complete([], on_text=seen.append)
    assert reply.content == '今天练腿，保持轻量。'


@pytest.mark.parametrize('tail', [b'', sse(finish='length') + b'data: [DONE]\n\n'])
def test_provider_rejects_incomplete_stream(tail):
    provider = OpenAICompatibleProvider(Settings(live_enabled=True, api_key='test'),
        transport=httpx.MockTransport(lambda _: httpx.Response(200,
            content=sse({'content': '未完成'}) + tail)))
    with pytest.raises(ProviderError, match='invalid_response'):
        provider.complete([], on_text=lambda _: None)


def test_readable_draft_arrives_before_extraction_and_counts_against_budget():
    from fitness.agent_contracts import RunLimits
    from fitness.agent_runtime import AgentRuntime
    from fitness.plan_streaming import plan_events
    from fitness.provider import ProviderReply

    events = []

    class Provider:
        def complete(self, messages, tools=None, **kwargs):
            if 'on_text' in kwargs:
                kwargs['on_text']('今天安排轻量训练。')
                return ProviderReply(content='今天安排轻量训练。', usage={'total_tokens': 5})
            assert any(event == ('text', {'text': '今天安排轻量训练。'}) for event in events)
            assert messages[-2]['content'] == '今天安排轻量训练。'
            return ProviderReply(content=json.dumps({'status': 'draft_ready', 'candidate': {'sets': 2}}),
                                 usage={'total_tokens': 7})

    class Tools:
        def __init__(self):
            self.retrieved_sources = {}

        def schemas(self):
            return []

    token = plan_events.set(lambda event, data: events.append((event, data)))
    try:
        runner = AgentRuntime(Provider(), RunLimits(), clock=lambda: 0)
        result = runner.run(role='训练规划，只输出JSON', task={}, tools=Tools(), validate=lambda c, s: [])
        assert result.status == 'draft_ready'
        assert result.trace['calls'] == 2
        assert result.trace['usage']['total_tokens'] == 12
        limited = AgentRuntime(Provider(), RunLimits(max_calls=1), clock=lambda: 0).run(
            role='训练规划', task={}, tools=Tools(), validate=lambda c, s: [])
        assert limited.reason_code == 'call_limit'
    finally:
        plan_events.reset(token)


def test_supplement_agent_does_not_stream_unvalidated_free_text():
    from fitness.agent_contracts import RunLimits
    from fitness.agent_runtime import AgentRuntime
    from fitness.plan_streaming import plan_events
    from fitness.provider import ProviderReply

    events = []

    class Provider:
        def complete(self, messages, tools=None, **kwargs):
            assert 'on_text' not in kwargs
            return ProviderReply(content=json.dumps({'status': 'draft_ready', 'candidate': {}}))

    class Tools:
        def schemas(self):
            return []

        def __init__(self):
            self.retrieved_sources = {}

    token = plan_events.set(lambda event, data: events.append((event, data)))
    try:
        result = AgentRuntime(Provider(), RunLimits(), clock=lambda: 0).run(
            role='你是补剂规划 Agent，只输出JSON', task={}, tools=Tools(), validate=lambda c, s: [])
        assert result.status == 'draft_ready'
        assert ('phase', {'message': '补剂建议'}) in events
        assert not any(event == 'text' for event, _ in events)
    finally:
        plan_events.reset(token)


def test_stream_routes_preserve_results_and_http_error_details(tmp_path, monkeypatch, profile_data):
    from fastapi.testclient import TestClient
    from planning_provider import ModelledTestProvider
    from test_api import main

    from fitness.config import Settings
    from fitness.orchestration import FitnessAgent
    from fitness.storage import Store

    monkeypatch.setattr(main, 'store', Store(tmp_path / 'stream.db'))
    monkeypatch.setattr(main, 'settings', Settings(api_key='synthetic-test-key'))
    provider = ModelledTestProvider()
    agent = FitnessAgent(main.store, None, main.settings, provider=provider)
    monkeypatch.setattr(main, 'planning_service', lambda: agent)
    client = TestClient(main.app)
    client.put('/api/profile', json={'profile': profile_data, 'expected_version': 0})
    result = client.post('/api/long-term-plans/stream', json={'start_date': '2026-10-21'})
    assert result.headers['content-type'].startswith('text/event-stream')
    frames = parse_events(result.text)
    saved = next(data for event, data in frames if event == 'result')
    assert saved['id'] == client.get('/api/planning/state').json()['long_term_plans'][0]['id']
    client.post(f"/api/long-term-plans/{saved['id']}/confirm")
    daily = client.post('/api/daily-plans/stream', json={'date': '2026-10-21'})
    assert any(event == 'result' for event, _ in parse_events(daily.text))

    def conflict(_):
        from fastapi import HTTPException
        raise HTTPException(409, {'message': '档案已更新', 'code': 'conflict'})

    monkeypatch.setattr(main, 'daily_plan', conflict)
    failure = parse_events(client.post('/api/daily-plans/stream', json={'date': '2026-10-21'}).text)
    assert failure[-1] == ('error', {'status': 409, 'detail': {'message': '档案已更新', 'code': 'conflict'}})
    assert not any(event == 'result' for event, _ in failure)


def parse_events(body):
    return [(frame.split('\n')[0][7:], json.loads(frame.split('\ndata: ')[1]))
            for frame in body.strip().split('\n\n') if frame.startswith('event: ')]


def test_sse_bridge_yields_text_while_operation_is_still_running_and_stops_on_disconnect():
    import asyncio
    from threading import Event

    from fitness.plan_streaming import StreamDisconnected, emit_plan_event, stream_plan

    continue_work, stopped = Event(), Event()

    def operation():
        emit_plan_event('text', {'text': '先读这段草稿'})
        assert continue_work.wait(3)
        try:
            emit_plan_event('status', {'message': '准备保存'})
        except StreamDisconnected:
            stopped.set()
            raise
        pytest.fail('disconnected operation must stop before saving')

    async def consume():
        events = stream_plan(operation).body_iterator
        assert 'event: status' in await anext(events)
        assert '先读这段草稿' in await anext(events)
        await events.aclose()
        continue_work.set()
        assert await asyncio.to_thread(stopped.wait, 3)

    asyncio.run(consume())


def test_streamed_usage_and_response_size_limits_are_preserved():
    body = (sse({'content': '可读计划'}) + sse(finish='stop') +
            b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":3,"total_tokens":7}}\n\n' +
            b'data: [DONE]\n\n')
    settings = Settings(live_enabled=True, api_key='test', max_response_bytes=1024)
    provider = OpenAICompatibleProvider(settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))
    assert provider.complete([], on_text=lambda _: None).usage['total_tokens'] == 7
    provider = OpenAICompatibleProvider(settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse({'content': 'x' * 2000}))))
    with pytest.raises(ProviderError, match='response_too_large'):
        provider.complete([], on_text=lambda _: None)


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('limit,text', [(128_000, '今天练腿' * 256), (1024, 'x' * 1024)],
                         ids=['normal_chinese_plan', 'exact_text_limit'])
def test_stream_metadata_does_not_consume_the_plan_text_budget(combined, limit, text):
    seen = []
    frames = [('data: ' + json.dumps({
        'id': 'completion-example', 'object': 'chat.completion.chunk',
        'created': 1792540800, 'model': 'test-model', 'system_fingerprint': 'test',
        'choices': [{'index': 0, 'delta': {'content': char}, 'finish_reason': None}],
    }, ensure_ascii=False) + '\n\n').encode() for char in text]
    frames.extend([sse(finish='stop'),
        b'data: {"choices":[],"usage":{"total_tokens":1024}}\n\n', b'data: [DONE]\n\n'])
    assert sum(map(len, frames)) > limit

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            if combined:
                yield b''.join(frames)
            else:
                yield frames[0]
                assert seen == [text[0]]
                yield from frames[1:]

    provider = OpenAICompatibleProvider(
        Settings(live_enabled=True, api_key='test', max_response_bytes=limit),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())))
    reply = provider.complete([], on_text=seen.append)
    assert reply.content == ''.join(seen) == text
    assert reply.usage == provider.usage_totals == {'total_tokens': 1024}


def test_stream_text_budget_counts_utf8_bytes_before_emitting_overflow():
    seen = []

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield sse({'content': '今' * 341})
            yield sse({'content': '天'})
            pytest.fail('must stop reading when the text budget is exceeded')

    provider = OpenAICompatibleProvider(
        Settings(live_enabled=True, api_key='test', max_response_bytes=1024),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())))
    with pytest.raises(ProviderError, match='response_too_large'):
        provider.complete([], on_text=seen.append)
    assert seen == ['今' * 341]


def test_stream_transport_budget_stops_excessive_metadata_without_text():
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(300):
                yield b':' + b'x' * 1024 + b'\n\n'
            pytest.fail('metadata must have a finite transport budget')

    provider = OpenAICompatibleProvider(
        Settings(live_enabled=True, api_key='test', max_response_bytes=1024),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())))
    with pytest.raises(ProviderError, match='response_too_large'):
        provider.complete([], max_output_tokens=256,
            on_text=lambda _: pytest.fail('metadata must not be emitted as text'))


def test_provider_stops_reading_at_done_even_if_upstream_keeps_connection_open():
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield sse({'content': '完整草稿'}) + sse(finish='stop') + b'data: [DONE]\n\n'
            pytest.fail('must not wait for the upstream connection to close after DONE')

    provider = OpenAICompatibleProvider(Settings(live_enabled=True, api_key='test'),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())))
    assert provider.complete([], on_text=lambda _: None).content == '完整草稿'


def test_stream_bridge_rejects_excess_work_without_starting_another_operation(monkeypatch):
    import asyncio
    from threading import BoundedSemaphore, Event

    from fitness import plan_streaming

    monkeypatch.setattr(plan_streaming, '_worker_slots', BoundedSemaphore(1))
    release = Event()

    def operation():
        assert release.wait(3)
        return {'id': 'saved'}

    async def consume():
        first = plan_streaming.stream_plan(operation).body_iterator
        assert 'event: status' in await anext(first)
        second = plan_streaming.stream_plan(lambda: pytest.fail('capacity must be bounded')).body_iterator
        rejected = await anext(second)
        assert 'event: error' in rejected and '503' in rejected
        await second.aclose()
        release.set()
        assert 'event: result' in await anext(first)
        await first.aclose()

    try:
        asyncio.run(consume())
    finally:
        release.set()
