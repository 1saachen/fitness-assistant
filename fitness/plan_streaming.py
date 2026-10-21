"""Request-scoped plan events and a bounded SSE bridge for synchronous planners."""

import asyncio
import json
import logging
from contextvars import ContextVar
from queue import Empty, Full, Queue
from threading import BoundedSemaphore, Event, Thread

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

plan_events = ContextVar('plan_events', default=None)
logger = logging.getLogger(__name__)
_worker_slots = BoundedSemaphore(4)


class StreamDisconnected(Exception):
    pass


def emit_plan_event(event, data):
    sink = plan_events.get()
    if sink is not None:
        sink(event, data)


def stream_plan(operation):
    async def events():
        slots = _worker_slots
        if not slots.acquire(blocking=False):
            data = {'status': 503, 'detail': {'message': '当前生成任务较多，请稍后重试。'}}
            yield f'event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
            return
        queue = Queue(maxsize=64)
        cancelled = Event()

        def emit(event, data):
            while not cancelled.is_set():
                try:
                    queue.put((event, data), timeout=0.2)
                    return
                except Full:
                    continue
            raise StreamDisconnected()

        def work():
            token = plan_events.set(emit)
            try:
                try:
                    emit('status', {'message': '正在读取资料，生成计划…'})
                    result = operation()
                    emit('result', jsonable_encoder(result))
                except HTTPException as exc:
                    emit('error', {'status': exc.status_code, 'detail': exc.detail})
                except StreamDisconnected:
                    raise
                except Exception:
                    logger.exception('plan_stream_failed')
                    emit('error', {'status': 500, 'detail': {'message': '本次生成未完成，请检查计划历史后重试。'}})
            except StreamDisconnected:
                pass
            finally:
                plan_events.reset(token)
                slots.release()

        try:
            Thread(target=work, daemon=True, name='plan-stream').start()
        except Exception:
            slots.release()
            raise

        def next_event():
            try:
                return queue.get(timeout=10)
            except Empty:
                return None

        try:
            while True:
                item = await asyncio.to_thread(next_event)
                if item is None:
                    yield ': keepalive\n\n'
                    continue
                event, data = item
                yield f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
                if event in {'result', 'error'}:
                    return
        finally:
            cancelled.set()

    return StreamingResponse(events(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
