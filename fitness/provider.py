"""Bounded OpenAI-compatible model transport. It never executes tools."""

import codecs
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass
class ProviderReply:
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def _json_loads(value):
    def reject_constant(_):
        raise ValueError("non-finite number")

    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = item
        return result

    return json.loads(value, parse_constant=reject_constant, object_pairs_hook=unique_pairs)


def _matches_schema(value, schema, depth=0):
    """Validate the bounded subset of JSON Schema used by local tool contracts."""
    if depth > 20 or not isinstance(schema, dict):
        return False
    if "anyOf" in schema:
        return any(_matches_schema(value, option, depth + 1) for option in schema["anyOf"])
    if "oneOf" in schema:
        return sum(_matches_schema(value, option, depth + 1) for option in schema["oneOf"]) == 1
    types = {"object": dict, "array": list, "string": str, "integer": int,
             "number": (int, float), "boolean": bool, "null": type(None)}
    kind = schema.get("type")
    if kind not in types or not isinstance(value, types[kind]):
        return False
    if kind in {"integer", "number"} and (
        isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value))
    ):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if kind == "object":
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])) <= value.keys() or not value.keys() <= properties.keys():
            return False
        return all(_matches_schema(item, properties[key], depth + 1) for key, item in value.items())
    if kind == "array":
        if len(value) > schema.get("maxItems", 100) or len(value) < schema.get("minItems", 0):
            return False
        return all(_matches_schema(item, schema.get("items", {}), depth + 1) for item in value)
    if kind == "string":
        return schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4000)
    if kind in {"integer", "number"}:
        return schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf)
    return True


def _tool_schemas(tools):
    schemas = {}
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ProviderError("invalid_request")
        function = tool.get("function", {})
        if not isinstance(function, dict):
            raise ProviderError("invalid_request")
        name = function.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            raise ProviderError("invalid_request")
        if name in schemas or not isinstance(function.get("parameters"), dict):
            raise ProviderError("invalid_request")
        schemas[name] = function["parameters"]
    return schemas


def _normalize_reply(body, schemas, max_tool_calls=1):
    root_fields = {"id", "object", "created", "model", "choices", "usage", "system_fingerprint", "service_tier"}
    if not isinstance(body, dict) or not body.keys() <= root_fields:
        raise ProviderError("invalid_response")
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderError("invalid_response")
    choice = choices[0]
    if not choice.keys() <= {"index", "message", "finish_reason", "logprobs"}:
        raise ProviderError("invalid_response")
    if choice.get("finish_reason") not in {None, "stop", "tool_calls"}:
        raise ProviderError("invalid_response")
    message = choice.get("message")
    if not isinstance(message, dict) or not message.keys() <= {"role", "content", "tool_calls", "refusal"}:
        raise ProviderError("invalid_response")
    if message.get("role") != "assistant" or message.get("refusal"):
        raise ProviderError("invalid_response")
    content = message.get("content")
    calls = message.get("tool_calls") or []
    if content is not None and not isinstance(content, str):
        raise ProviderError("invalid_response")
    if not isinstance(calls, list) or len(calls) > max_tool_calls:
        raise ProviderError("invalid_tool_call")
    normalized = []
    for call in calls:
        if (not isinstance(call, dict) or not {"id", "type", "function"} <= call.keys()
                or not call.keys() <= {"id", "type", "function", "index"} or call["type"] != "function"):
            raise ProviderError("invalid_tool_call")
        if "index" in call and (type(call["index"]) is not int or not 0 <= call["index"] < max_tool_calls):
            raise ProviderError("invalid_tool_call")
        call_id, function = call["id"], call["function"]
        if not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", call_id):
            raise ProviderError("invalid_tool_call")
        if any(item["id"] == call_id for item in normalized):
            raise ProviderError("invalid_tool_call")
        if not isinstance(function, dict) or set(function) != {"name", "arguments"}:
            raise ProviderError("invalid_tool_call")
        name, raw_arguments = function["name"], function["arguments"]
        if not isinstance(name, str) or name not in schemas or not isinstance(raw_arguments, str):
            raise ProviderError("invalid_tool_call")
        try:
            arguments = _json_loads(raw_arguments)
        except (ValueError, TypeError, RecursionError):
            raise ProviderError("invalid_tool_call") from None
        if not isinstance(arguments, dict) or not _matches_schema(arguments, schemas[name]):
            raise ProviderError("invalid_tool_call")
        normalized.append({"id": call_id, "name": name, "arguments": arguments})
    if not normalized and (content is None or not content.strip()):
        raise ProviderError("invalid_response")
    usage = body.get("usage") or {}
    if not isinstance(usage, dict):
        raise ProviderError("invalid_response")
    allowed_usage = {"prompt_tokens", "completion_tokens", "total_tokens",
                     "prompt_tokens_details", "completion_tokens_details",
                     "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
    if not usage.keys() <= allowed_usage:
        raise ProviderError("invalid_response")
    counts = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        if key in usage:
            if type(usage[key]) is not int or not 0 <= usage[key] <= 1_000_000_000:
                raise ProviderError("invalid_response")
            counts[key] = usage[key]
    return ProviderReply(content=content, tool_calls=normalized, usage=counts)


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None,
                 client: httpx.Client | None = None, max_tool_calls: int = 1):
        if transport is not None and client is not None:
            raise ValueError("choose transport or client")
        if type(max_tool_calls) is not int or not 1 <= max_tool_calls <= 8:
            raise ValueError("max_tool_calls must be between 1 and 8")
        self.max_tool_calls = max_tool_calls
        self.settings = settings
        self.transport = transport
        self.client = client
        self.usage_totals = {}

    def complete(self, messages, tools=None, *, timeout_seconds=None, max_output_tokens=None,
                 on_text=None) -> ProviderReply:
        if not self.settings.live_enabled:
            raise ProviderError("live_disabled")
        if not self.settings.api_key:
            raise ProviderError("missing_api_key")
        if not isinstance(messages, list) or len(messages) > 100 or (tools is not None and not isinstance(tools, list)):
            raise ProviderError("invalid_request")
        timeout = self.settings.timeout_seconds if timeout_seconds is None else timeout_seconds
        output_tokens = 2048 if max_output_tokens is None else max_output_tokens
        if (type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 300
                or type(output_tokens) is not int or not 256 <= output_tokens <= 16384):
            raise ProviderError('invalid_request')
        schemas = _tool_schemas(tools)
        if on_text is not None and tools:
            raise ProviderError('invalid_request')
        payload = {"model": self.settings.model, "messages": messages,
                   "stream": on_text is not None, "max_tokens": output_tokens}
        if on_text is not None:
            payload['stream_options'] = {'include_usage': True}
        if tools:
            payload.update(tools=tools, parallel_tool_calls=False)
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise ProviderError("invalid_request") from None
        if len(encoded) > self.settings.max_request_bytes:
            raise ProviderError("request_too_large")
        started = time.monotonic()
        status = None
        counts = {}
        owned = self.client is None
        client = self.client or httpx.Client(transport=self.transport, trust_env=False)
        try:
            endpoint = self.settings.base_url.rstrip("/") + "/chat/completions"
            with client.stream("POST", endpoint, content=encoded, headers={
                "Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json",
            }, timeout=timeout, follow_redirects=False) as result:
                status = result.status_code
                if not 200 <= status < 300:
                    raise ProviderError("http_error")
                chunks = bytearray()
                stream = _TextStream(on_text, self.settings.max_response_bytes) if on_text is not None else None
                response_limit = self.settings.max_response_bytes
                if stream is not None:
                    # SSE repeats JSON metadata per token; bound it separately from the text.
                    response_limit += output_tokens * 1024
                received_bytes = 0
                for chunk in result.iter_bytes():
                    if time.monotonic() - started >= timeout:
                        raise ProviderError('timeout')
                    received_bytes += len(chunk)
                    if received_bytes > response_limit:
                        raise ProviderError("response_too_large")
                    if stream is None:
                        chunks.extend(chunk)
                    else:
                        stream.feed(chunk)
                        if stream.done:
                            break
                try:
                    body = stream.finish() if stream is not None else _json_loads(chunks)
                    reply = _normalize_reply(body, schemas, self.max_tool_calls)
                except (ValueError, TypeError, RecursionError, KeyError):
                    raise ProviderError("invalid_response") from None
                counts = reply.usage
                for key, value in counts.items():
                    self.usage_totals[key] = self.usage_totals.get(key, 0) + value
                return reply
        except httpx.TimeoutException:
            raise ProviderError("timeout") from None
        except httpx.HTTPError:
            raise ProviderError("network_error") from None
        finally:
            if owned:
                client.close()
            logger.info("provider_request model=%s latency_ms=%d status=%s usage=%s", self.settings.model,
                        round((time.monotonic() - started) * 1000), status, counts)


class _TextStream:
    """Incremental SSE text-only completion; tool responses use the normal path."""

    def __init__(self, emit, max_text_bytes):
        self.emit = emit
        self.max_text_bytes = max_text_bytes
        self.text_bytes = 0
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.buffer = ''
        self.lines = []
        self.parts = []
        self.usage = {}
        self.stopped = False
        self.done = False

    def feed(self, chunk):
        try:
            self.buffer += self.decoder.decode(chunk)
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                line = line.removesuffix('\r')
                if not line:
                    self._event()
                elif line.startswith('data:'):
                    self.lines.append(line[5:].lstrip(' '))
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError):
            raise ProviderError('invalid_response') from None

    def _event(self):
        if not self.lines:
            return
        data, self.lines = '\n'.join(self.lines), []
        if self.done:
            raise ValueError('event after done')
        if data == '[DONE]':
            self.done = True
            return
        body = _json_loads(data)
        if body.get('usage') is not None:
            self.usage = body['usage']
        choices = body['choices']
        if not choices:
            return
        if len(choices) != 1 or choices[0].get('index') != 0:
            raise ValueError('invalid choice')
        choice = choices[0]
        delta = choice['delta']
        if delta.get('tool_calls') or delta.get('refusal') or delta.get('role', 'assistant') != 'assistant':
            raise ValueError('not a text completion')
        content = delta.get('content')
        if content is not None:
            if not isinstance(content, str) or self.stopped:
                raise ValueError('invalid content')
            if content:
                self.text_bytes += len(content.encode('utf-8'))
                if self.text_bytes > self.max_text_bytes:
                    raise ProviderError('response_too_large')
                self.parts.append(content)
                self.emit(content)
        reason = choice.get('finish_reason')
        if reason is not None:
            if reason != 'stop' or self.stopped:
                raise ValueError('incomplete completion')
            self.stopped = True

    def finish(self):
        self.decoder.decode(b'', final=True)
        if not self.done or not self.stopped or self.buffer.strip() or self.lines:
            raise ValueError('incomplete stream')
        return {'choices': [{'message': {'role': 'assistant', 'content': ''.join(self.parts)},
                             'finish_reason': 'stop'}], 'usage': self.usage}
