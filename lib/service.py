"""查询编排：并发去重、每群最小间隔、两个上游的结果聚合。

职责边界：

- 入参校验与查询串规整（:mod:`lib.detect`）；
- 同群同文本进行中不重复请求上游；
- 每群最小间隔 2 秒，给被动识别削峰；
- VoiceHubPay 命中后逐张券回查 VoiceHub 状态（未配置则整段降级）；
- VoiceHubPay 明确 404 时，仍拿原文去 VoiceHub 按券码查一次，
  覆盖「站点直接发券、没有支付订单」的情况。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .config import CouponConfig, MIN_INTERVAL_SECONDS
from .contract import (
    STATE_DISABLED,
    STATE_ERROR,
    STATE_INVALID,
    STATE_NOT_FOUND,
    STATE_OK,
    STATE_THROTTLED,
)
from .detect import normalize_query
from .render import render_card_only, render_reply
from .texts import (
    TEXT_INVALID_QUERY,
    TEXT_NOT_FOUND,
    TEXT_NOT_FOUND_NO_VOICEHUB,
    TEXT_PAY_NOT_CONFIGURED,
    TEXT_QUERY_FAILED,
    TEXT_THROTTLED,
    TEXT_USAGE,
)
from .voicehub import CardStatus, VoiceHubCardClient
from .voicehubpay import QueryResult, VoiceHubPayClient

# 一次查询里最多同时回查 5 张券：够快，又不会把站点打出尖峰。
MAX_CONCURRENT_CARD_QUERIES = 5
# 限流表超过这个规模就顺手清理一分钟前的记录，避免长期运行后无限增长。
_THROTTLE_TABLE_LIMIT = 512
_THROTTLE_RETENTION_SECONDS = 60.0


@dataclass
class Outcome:
    """一次查询的最终结果（文案已渲染好，状态供调用方决定是否静默）。"""

    state: str
    text: str = ""
    payload: dict = field(default_factory=dict)


class CouponQueryService:
    """点歌券查询服务：把配置、两个客户端与去重/限流粘在一起。"""

    def __init__(
        self,
        config: CouponConfig,
        pay_client: Optional[Any] = None,
        card_client: Optional[Any] = None,
        now: Optional[Callable[[], float]] = None,
    ):
        self.config = config
        self.pay_client = pay_client or VoiceHubPayClient(config)
        self.card_client = card_client or VoiceHubCardClient(config)
        self._now = now or time.monotonic
        self._inflight: Dict[Tuple[str, str], "asyncio.Task[Outcome]"] = {}
        self._last_query_at: Dict[str, float] = {}

    async def query(self, text: str, group_id: str = "") -> Outcome:
        """查询一个订单号 / 券码。

        Args:
            text: 指令参数或被动识别命中的原文。
            group_id: 群号；私聊传空字符串（不做群级限流）。

        Returns:
            ``state`` 为 ok / not_found / invalid / throttled / disabled / error 的结果。
        """
        candidate = normalize_query(text)
        if not candidate:
            return Outcome(STATE_INVALID, TEXT_USAGE)
        if not self.config.pay_ready:
            return Outcome(STATE_DISABLED, TEXT_PAY_NOT_CONFIGURED)

        key = (str(group_id or ""), candidate)
        running = self._inflight.get(key)
        if running is not None:
            # 同群同文本已有请求在飞：共享同一个结果，不重复打上游
            return await asyncio.shield(running)

        if not self._allow(group_id):
            return Outcome(STATE_THROTTLED, TEXT_THROTTLED)

        task: "asyncio.Task[Outcome]" = asyncio.ensure_future(self._fetch(candidate))
        self._inflight[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            self._inflight.pop(key, None)

    def _allow(self, group_id: str) -> bool:
        """每群最小间隔检查；通过时记录本次时间。"""
        group_key = str(group_id or "")
        if not group_key:
            return True
        now = self._now()
        last = self._last_query_at.get(group_key)
        if last is not None and now - last < MIN_INTERVAL_SECONDS:
            return False
        if len(self._last_query_at) >= _THROTTLE_TABLE_LIMIT:
            cutoff = now - _THROTTLE_RETENTION_SECONDS
            self._last_query_at = {
                key: value for key, value in self._last_query_at.items() if value >= cutoff
            }
        self._last_query_at[group_key] = now
        return True

    async def _fetch(self, candidate: str) -> Outcome:
        """先问 VoiceHubPay；404 再按券码问 VoiceHub。"""
        result: QueryResult = await self.pay_client.query(candidate)
        if result.state == STATE_OK:
            payload = dict(result.payload or {})
            codes = _coupon_codes(payload, self.config.max_coupons)
            statuses = await self._card_statuses(codes)
            text = render_reply(
                payload,
                statuses,
                show_full_code=self.config.show_full_code,
                max_coupons=self.config.max_coupons,
            )
            return Outcome(STATE_OK, text, payload)
        if result.state == STATE_NOT_FOUND:
            return await self._card_only(candidate)
        if result.state == STATE_INVALID:
            return Outcome(STATE_INVALID, TEXT_INVALID_QUERY)
        return Outcome(STATE_ERROR, f"查询失败：{result.message or TEXT_QUERY_FAILED}")

    async def _card_only(self, candidate: str) -> Outcome:
        """VoiceHubPay 无此订单时的降级：只按券码查站点状态。"""
        if not self.config.voicehub_ready:
            # 无法进一步确认，只能告知未找到并说明降级原因
            return Outcome(STATE_NOT_FOUND, TEXT_NOT_FOUND_NO_VOICEHUB)

        card = await self.card_client.status(candidate)
        if card.state == STATE_OK:
            return Outcome(
                STATE_OK,
                render_card_only(
                    {"state": STATE_OK, "data": card.data},
                    candidate,
                    show_full_code=self.config.show_full_code,
                ),
            )
        if card.state in (STATE_NOT_FOUND, STATE_DISABLED):
            return Outcome(STATE_NOT_FOUND, TEXT_NOT_FOUND)
        return Outcome(STATE_ERROR, f"查询失败：{card.message or TEXT_QUERY_FAILED}")

    async def _card_statuses(self, codes: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """并发回查每张券的站点状态，单张失败只影响该张。"""
        if not codes:
            return {}
        if not self.config.voicehub_ready:
            # 降级：不触网，直接标记未配置，由渲染层显示固定文案
            return {code: {"state": STATE_DISABLED} for code in codes}

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CARD_QUERIES)

        async def one(code: str) -> CardStatus:
            async with semaphore:
                return await self.card_client.status(code)

        results = await asyncio.gather(*(one(code) for code in codes), return_exceptions=True)
        statuses: Dict[str, Dict[str, Any]] = {}
        for code, result in zip(codes, results):
            if isinstance(result, BaseException):
                statuses[code] = {"state": STATE_ERROR}
                continue
            statuses[code] = {
                "state": result.state,
                "data": result.data,
                "message": result.message,
            }
        return statuses


def _coupon_codes(payload: Mapping[str, Any], limit: int) -> List[str]:
    """从响应体里取前 ``limit`` 张券的明文券码（去重、保持顺序）。"""
    raw = payload.get("coupons")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    codes: List[str] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        # 纯卡密（voicehub_status=not_required）没有对应的 VoiceHub 点歌券，
        # 回查站点只会得到 404，反而在回复里写成「未收录（可能尚未发货）」。
        kind = item.get("kind")
        if isinstance(kind, str) and kind.strip().lower() == "card":
            continue
        code = item.get("code")
        if isinstance(code, str) and code.strip() and code.strip() not in codes:
            codes.append(code.strip())
        if len(codes) >= limit:
            break
    return codes


__all__ = ["CouponQueryService", "Outcome"]
