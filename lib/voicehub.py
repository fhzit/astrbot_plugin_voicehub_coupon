"""VoiceHub 开放接口客户端：按点歌券码查询站点状态。

契约（跨仓库契约第 1 节）：

- ``GET /api/open/card-codes/status?code=<CODE>``
- 请求头 ``x-api-key: <API Key>``，需要 ``card-codes:read`` 权限
- 200 ``{"success": true, "data": {...}}``；404 ``{"success": false, ...}``

该接口属「可选增强」：未配置站点地址或 API Key 时客户端直接返回 ``disabled``，
调用方仍能回复 VoiceHubPay 的订单与发货状态（降级，不报错）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import aiohttp

from astrbot.api import logger

from .config import CouponConfig
from .contract import (
    API_KEY_HEADER,
    CARD_CODE_QUERY_FIELD,
    CARD_CODE_STATUS_PATH,
    STATE_DISABLED,
    STATE_ERROR,
    STATE_NOT_FOUND,
    STATE_OK,
)
from .http import describe_client_error, log_network_error, make_session


@dataclass
class CardStatus:
    """一张点歌券在 VoiceHub 的状态。

    ``state`` 取值：``ok``（含 data）、``not_found``、``disabled``（未配置）、``error``。
    """

    state: str
    data: dict = field(default_factory=dict)
    message: str = ""


class VoiceHubCardClient:
    """调用 VoiceHub 的券码状态开放接口。"""

    def __init__(
        self,
        config: CouponConfig,
        session_factory: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self._session_factory = session_factory or make_session

    async def status(self, code: str) -> CardStatus:
        """查询单张券在站点的状态。

        Args:
            code: 券码明文（只在令牌鉴权的请求里使用，不会原样进聊天）。

        Returns:
            归一化结果；未配置时返回 ``disabled``，网络异常收敛为 ``error``。
        """
        if not self.config.voicehub_ready:
            return CardStatus(STATE_DISABLED)

        url = f"{self.config.voicehub_base_url}{CARD_CODE_STATUS_PATH}"
        headers = {API_KEY_HEADER: self.config.voicehub_api_key}
        params = {CARD_CODE_QUERY_FIELD: code}
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout_seconds)

        try:
            async with self._session_factory(timeout) as session:
                async with session.get(
                    url,
                    params=params,
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status < 400:
                        return CardStatus(STATE_ERROR, message="VoiceHub 拒绝重定向")
                    body = await self._read_json(response)
                    return self._interpret(response.status, body)
        except Exception as exc:  # noqa: BLE001 - 站点状态查询失败不应影响订单回复
            log_network_error(logger, "VoiceHub 券状态", exc, CARD_CODE_STATUS_PATH)
            return CardStatus(STATE_ERROR, message=describe_client_error(exc))

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse) -> dict:
        """读取响应体，非 JSON 或非对象时返回空字典。"""
        try:
            body: Any = await response.json(content_type=None)
            return body if isinstance(body, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _interpret(status: int, body: dict) -> CardStatus:
        """按状态码映射：200 成功、404 未收录、401/403 权限问题、其余错误。"""
        if status == 200 and body.get("success") is True:
            data = body.get("data")
            if isinstance(data, dict):
                return CardStatus(STATE_OK, data=data)
            return CardStatus(STATE_ERROR, message="VoiceHub 返回了空的状态数据")
        if status == 404:
            return CardStatus(STATE_NOT_FOUND)
        if status in (401, 403):
            return CardStatus(
                STATE_ERROR,
                message="VoiceHub API Key 无效或缺少 card-codes:read 权限",
            )
        if status >= 400:
            return CardStatus(STATE_ERROR, message=f"VoiceHub 返回状态码 {status}")
        return CardStatus(STATE_ERROR, message="VoiceHub 返回了无法识别的响应")


__all__ = ["CardStatus", "VoiceHubCardClient"]
