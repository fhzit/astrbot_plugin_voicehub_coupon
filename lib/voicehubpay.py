"""VoiceHubPay 机器人查询客户端。

接口契约（跨仓库契约第 2 节）：

- ``POST /api/bot/coupon-query``
- 请求头 ``X-Bot-Token: <BOT_QUERY_TOKEN>``
- 请求体 ``{"query": "<订单号或券码>"}``
- 200 ``{"ok": true, "found_by": ..., "order": {...}, "coupons": [...]}``
- 404 ``NOT_FOUND`` / 400 ``INVALID_QUERY`` / 401 ``UNAUTHORIZED`` / 503 ``BOT_QUERY_DISABLED``

客户端只做「发一次请求 + 把状态收敛成三种结果」，不渲染文案、不写日志里的令牌。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import aiohttp

from astrbot.api import logger

from .config import CouponConfig
from .contract import (
    BOT_TOKEN_HEADER,
    COUPON_QUERY_PATH,
    ERROR_BOT_QUERY_DISABLED,
    ERROR_INVALID_QUERY,
    ERROR_NOT_FOUND,
    ERROR_UNAUTHORIZED,
    QUERY_FIELD,
    STATE_ERROR,
    STATE_INVALID,
    STATE_NOT_FOUND,
    STATE_OK,
)
from .http import describe_client_error, log_network_error, make_session


@dataclass
class QueryResult:
    """一次订单查询的结果。

    ``state`` 取值：``ok``（含 payload）、``not_found``、``invalid``、``error``。
    """

    state: str
    payload: dict = field(default_factory=dict)
    message: str = ""


class VoiceHubPayClient:
    """调用 VoiceHubPay 的机器人查询接口。"""

    def __init__(
        self,
        config: CouponConfig,
        session_factory: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self._session_factory = session_factory or make_session

    async def query(self, text: str) -> QueryResult:
        """按订单号 / 爱发电单号 / 券码查询一次。

        Args:
            text: 已规整的查询串（服务层保证非空、无空白）。

        Returns:
            归一化结果；任何网络异常都收敛为 ``error``，不向上抛。
        """
        if not self.config.pay_ready:
            return QueryResult(STATE_ERROR, message="插件未配置 VoiceHubPay 地址或机器人令牌")

        url = f"{self.config.voicehubpay_base_url}{COUPON_QUERY_PATH}"
        headers = {
            BOT_TOKEN_HEADER: self.config.voicehubpay_bot_token,
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout_seconds)

        try:
            async with self._session_factory(timeout) as session:
                async with session.post(
                    url,
                    json={QUERY_FIELD: text},
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status < 400:
                        # 共享令牌不得被重定向带到别的主机
                        return QueryResult(STATE_ERROR, message="VoiceHubPay 拒绝重定向")
                    body = await self._read_json(response)
                    return self._interpret(response.status, body)
        except Exception as exc:  # noqa: BLE001 - 查询失败不得打断消息处理
            log_network_error(logger, "VoiceHubPay 查询", exc, COUPON_QUERY_PATH)
            return QueryResult(STATE_ERROR, message=describe_client_error(exc))

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse) -> dict:
        """读取响应体，非 JSON 或非对象时返回空字典。"""
        try:
            body: Any = await response.json(content_type=None)
            return body if isinstance(body, dict) else {}
        except Exception:  # noqa: BLE001 - 上游返回非 JSON 时按无正文处理
            return {}

    @staticmethod
    def _interpret(status: int, body: dict) -> QueryResult:
        """把 HTTP 状态码 + 响应体映射为四种结果之一。"""
        error = str(body.get("error") or "").strip().upper()

        if status == 200 and body.get("ok") is True:
            return QueryResult(STATE_OK, payload=body)

        if status == 404 or error == ERROR_NOT_FOUND:
            return QueryResult(STATE_NOT_FOUND)

        if status in (401, 403) or error == ERROR_UNAUTHORIZED:
            return QueryResult(
                STATE_ERROR,
                message="VoiceHubPay 拒绝了机器人令牌（401），请检查 voicehubpay_bot_token",
            )

        if status == 503 or error == ERROR_BOT_QUERY_DISABLED:
            return QueryResult(
                STATE_ERROR,
                message="VoiceHubPay 未开启机器人查询接口，请联系站点管理员",
            )

        if status == 400 or error == ERROR_INVALID_QUERY:
            return QueryResult(STATE_INVALID, message="VoiceHubPay 不接受该查询内容")

        if status >= 400:
            return QueryResult(STATE_ERROR, message=f"VoiceHubPay 返回状态码 {status}")

        return QueryResult(STATE_ERROR, message="VoiceHubPay 返回了无法识别的响应")


__all__ = ["QueryResult", "VoiceHubPayClient"]
