"""测试辅助：假 AstrBot 事件、假 aiohttp 会话、异步收集器。"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional


class FakeEvent:
    """最小可用的 AstrMessageEvent 替身。"""

    def __init__(self, message: str = "", group: Any = "", origin: str = ""):
        self.message_str = message
        self._group = str(group).strip() if group not in (None, "") else ""
        if origin:
            self.unified_msg_origin = origin
        elif self._group:
            self.unified_msg_origin = f"aiocqhttp:GroupMessage:{self._group}"
        else:
            self.unified_msg_origin = "aiocqhttp:FriendMessage:user1"
        self.replies: List[str] = []
        self.stopped = False

    def get_group_id(self):
        return self._group

    def get_platform_name(self):
        return "aiocqhttp"

    def plain_result(self, text):
        self.replies.append(text)
        return text

    def stop_event(self):
        self.stopped = True


async def collect(agen) -> List[Any]:
    """把 async generator 收成列表（handler 都是 yield 形式）。"""
    return [item async for item in agen]


def run(coro):
    """在当前线程跑完一个协程（测试里避免写 asyncio.run 样板）。"""
    return asyncio.run(coro)


class FakeResponse:
    """假 aiohttp 响应：状态码 + JSON 体，或模拟非 JSON 响应。"""

    def __init__(self, status: int = 200, body: Optional[dict] = None, json_error: bool = False):
        self.status = status
        self._body = body if body is not None else {}
        self._json_error = json_error

    async def json(self, content_type=None):  # noqa: ARG002 - 对齐 aiohttp 签名
        if self._json_error:
            raise ValueError("not json")
        return self._body

    async def text(self):
        return str(self._body)


class _RequestContext:
    """``async with session.post(...)`` 的替身（请求参数由 FakeSession 记录）。"""

    def __init__(self, result):
        self._result = result

    async def __aenter__(self):
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """假 aiohttp 会话：按顺序发放预置响应，或统一抛一个异常。"""

    def __init__(self, recorder, responses, error=None, timeout=None):
        self.recorder = recorder
        self.responses = list(responses)
        self.error = error
        self.timeout = timeout

    def _next(self, method, url, kwargs):
        if not self.responses:
            response = FakeResponse(500, {})
        elif len(self.responses) == 1:
            response = self.responses[0]
        else:
            response = self.responses.pop(0)
        self.recorder.append(
            {"method": method, "url": url, "kwargs": kwargs, "timeout": self.timeout}
        )
        return _RequestContext(self.error or response)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def session_factory(recorder, response=None, error=None):
    """构造一个可注入客户端的会话工厂（签名与 ``make_session(timeout)`` 一致）。"""

    def factory(timeout=None, **kwargs):  # noqa: ARG001
        responses = response if isinstance(response, list) else [response or FakeResponse()]
        return FakeSession(recorder, responses, error=error, timeout=timeout)

    return factory


def recorded(records, index: int = 0) -> dict:
    """取第 index 次请求记录的 method/url/kwargs 平铺结果。"""
    record = records[index]
    merged = {"method": record["method"], "url": record["url"], "timeout": record["timeout"]}
    merged.update(record["kwargs"])
    return merged
