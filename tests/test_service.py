"""查询编排：去重、限流、聚合与两类降级分支。"""

from __future__ import annotations

import asyncio

import pytest

from astrbot_plugin_voicehub_coupon.lib.config import CouponConfig
from astrbot_plugin_voicehub_coupon.lib.service import CouponQueryService
from astrbot_plugin_voicehub_coupon.lib.texts import (
    TEXT_CARD_DISABLED,
    TEXT_CARD_ERROR,
    TEXT_INVALID_QUERY,
    TEXT_NOT_FOUND,
    TEXT_NOT_FOUND_NO_VOICEHUB,
    TEXT_NO_PAY_ORDER,
    TEXT_PAY_NOT_CONFIGURED,
    TEXT_THROTTLED,
    TEXT_USAGE,
)
from astrbot_plugin_voicehub_coupon.lib.voicehub import CardStatus
from astrbot_plugin_voicehub_coupon.lib.voicehubpay import QueryResult

from support import run

QUERY = "20261122153000001234"
CODE = f"{QUERY}-001"
GROUP = "123456789"

CARD_DATA = {
    "code": CODE,
    "status": "USED",
    "createdAt": "2026-11-22T07:30:00.000Z",
    "assignment": {"status": "USED", "usedAtText": "2026/11/22 18:00:00"},
    "redeem": {
        "redeemedAtText": "2026/11/22 18:00:00",
        "source": "SCHEDULE_AUTO",
        "songTitle": "告白气球",
        "songArtist": "周杰伦",
    },
}


def config(**overrides) -> CouponConfig:
    base = {
        "voicehubpay_base_url": "https://pay.example.com",
        "voicehubpay_bot_token": "bot-secret",
        "voicehub_base_url": "https://voicehub.example.com",
        "voicehub_api_key": "vh-key",
        "group_ids": GROUP,
        "max_coupons": 10,
    }
    base.update(overrides)
    return CouponConfig.from_mapping(base)


def payload(codes=(CODE,)) -> dict:
    return {
        "ok": True,
        "found_by": "coupon_code",
        "source": "shop",
        "order": {
            "order_no": QUERY,
            "source": "shop",
            "amount_cents": 990,
            "amount_paid_cents": 990,
            "payment_status": "paid",
            "order_status": "active",
            "fulfillment_status": "success",
            "created_at": "2026-11-22T07:30:00.000Z",
            "items": [{"name": "点歌券", "quantity": 1, "unit_price_cents": 990}],
        },
        "coupons": [
            {"code": code, "masked_code": "2026****01", "unit_status": "success"}
            for code in codes
        ],
    }


class FakePayClient:
    """可记录调用、可被事件闸门挡住的假 VoiceHubPay 客户端。"""

    def __init__(self, result=None):
        self.calls: list = []
        self.result = result or QueryResult("ok", payload())
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def query(self, text):
        self.calls.append(text)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        return self.result


class FakeCardClient:
    """按券码返回预置状态；可让指定券码抛异常，验证单张失败不影响其它券。"""

    def __init__(self, default: CardStatus | None = None, overrides=None, raise_for=()):
        self.calls: list = []
        self.default = default or CardStatus("ok", dict(CARD_DATA))
        self.overrides = overrides or {}
        self.raise_for = set(raise_for)

    async def status(self, code):
        self.calls.append(code)
        if code in self.raise_for:
            raise RuntimeError("boom")
        return self.overrides.get(code, self.default)


def build(config_obj=None, pay=None, card=None, now=None):
    pay = pay or FakePayClient()
    card = card or FakeCardClient()
    service = CouponQueryService(config_obj or config(), pay_client=pay, card_client=card, now=now)
    return service, pay, card


def test_successful_query_merges_voicehub_status():
    service, pay, card = build()
    outcome = run(service.query(QUERY, GROUP))

    assert outcome.state == "ok"
    assert pay.calls == [QUERY]
    assert card.calls == [CODE]
    assert f"订单号：{QUERY}" in outcome.text
    assert "发货：已发货" in outcome.text
    assert "站点：已核销" in outcome.text
    assert "歌曲 《告白气球》- 周杰伦" in outcome.text
    assert CODE not in outcome.text


def test_coupon_lookup_is_capped_by_max_coupons():
    codes = [f"{QUERY}-00{i}" for i in range(1, 4)]
    pay = FakePayClient(QueryResult("ok", payload(codes)))
    service, _, card = build(config(max_coupons=2), pay=pay)
    outcome = run(service.query(QUERY, GROUP))

    assert card.calls == codes[:2]
    assert "点歌券（3 张）：" in outcome.text
    assert "…还有 1 张未显示（只展示前 2 张）" in outcome.text


def test_card_only_coupons_skip_voicehub_lookup():
    """纯卡密（kind=card）没有 VoiceHub 券记录，不应回查站点。"""
    codes = (f"{QUERY}-001", f"{QUERY}-002")
    body = payload(codes)
    body["coupons"][0]["kind"] = "card"
    body["coupons"][1]["kind"] = "voicehub"
    pay = FakePayClient(QueryResult("ok", body))
    service, _, card = build(pay=pay)
    outcome = run(service.query(QUERY, GROUP))

    assert card.calls == [codes[1]]
    assert "卡密（未同步 VoiceHub）" in outcome.text
    assert "站点：已核销" in outcome.text


def test_voicehub_not_configured_degrades_without_error():
    """VoiceHub 未配置：订单照常回复，券状态位置给固定降级文案。"""
    service, _, card = build(config(voicehub_base_url="", voicehub_api_key=""))
    outcome = run(service.query(QUERY, GROUP))

    assert outcome.state == "ok"
    assert card.calls == []
    assert TEXT_CARD_DISABLED in outcome.text
    assert f"订单号：{QUERY}" in outcome.text
    assert "发货：已发货" in outcome.text


def test_direct_card_status_entries_mark_disabled_states():
    """未配置 VoiceHub 时状态映射仍带 state=disabled，渲染层据此降级。"""
    service, _, card = build(config(voicehub_api_key=""))
    outcome = run(service.query(QUERY, GROUP))
    assert outcome.state == "ok"
    assert card.calls == []
    assert TEXT_CARD_DISABLED in outcome.text


def test_card_failure_only_affects_that_coupon():
    codes = [f"{QUERY}-001", f"{QUERY}-002"]
    pay = FakePayClient(QueryResult("ok", payload(codes)))
    card = FakeCardClient(raise_for={codes[0]})
    service, _, _ = build(pay=pay, card=card)
    outcome = run(service.query(QUERY, GROUP))

    assert outcome.state == "ok"
    assert TEXT_CARD_ERROR in outcome.text
    assert "站点：已核销" in outcome.text


def test_inflight_duplicate_shares_one_upstream_request():
    async def scenario():
        pay = FakePayClient()
        pay.started = asyncio.Event()
        pay.release = asyncio.Event()
        service, _, card = build(pay=pay)

        first = asyncio.ensure_future(service.query(QUERY, GROUP))
        await pay.started.wait()
        second = asyncio.ensure_future(service.query(QUERY, GROUP))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        pay.release.set()
        results = await asyncio.gather(first, second)
        return pay, card, results

    pay, card, results = run(scenario())
    assert pay.calls == [QUERY]
    assert len(card.calls) == 1
    assert results[0].text == results[1].text


def test_group_is_throttled_for_two_seconds_but_private_is_not():
    async def scenario():
        clock = [1000.0]
        service, pay, _ = build(now=lambda: clock[0])

        first = await service.query(f"{QUERY}-001", GROUP)
        clock[0] += 1.0
        second = await service.query(f"{QUERY}-002", GROUP)
        clock[0] += 2.0
        third = await service.query(f"{QUERY}-003", GROUP)
        private_first = await service.query(f"{QUERY}-004", "")
        private_second = await service.query(f"{QUERY}-005", "")
        return pay, first, second, third, private_first, private_second

    pay, first, second, third, private_first, private_second = run(scenario())
    assert first.state == "ok"
    assert second.state == "throttled"
    assert second.text == TEXT_THROTTLED
    assert third.state == "ok"
    assert private_first.state == "ok"
    assert private_second.state == "ok"
    assert len(pay.calls) == 4


def test_throttle_is_per_group():
    async def scenario():
        clock = [2000.0]
        service, _, _ = build(now=lambda: clock[0])
        await service.query(f"{QUERY}-001", GROUP)
        return await service.query(f"{QUERY}-002", "987654321")

    outcome = run(scenario())
    assert outcome.state == "ok"


@pytest.mark.parametrize("text", ["", "   ", "two words", "/查券"])
def test_invalid_query_returns_usage_without_calling_upstream(text):
    service, pay, card = build()
    outcome = run(service.query(text, GROUP))

    assert outcome.state == "invalid"
    assert outcome.text == TEXT_USAGE
    assert pay.calls == []
    assert card.calls == []


def test_missing_voicehubpay_config_returns_hint_without_network():
    service, pay, card = build(config(voicehubpay_base_url="", voicehubpay_bot_token=""))
    outcome = run(service.query(QUERY, GROUP))

    assert outcome.state == "disabled"
    assert outcome.text == TEXT_PAY_NOT_CONFIGURED
    assert pay.calls == []
    assert card.calls == []


def test_pay_not_found_falls_back_to_voicehub_card_status():
    """VoiceHubPay 无此单、但站点有这张券：回「点歌券状态」并说明订单缺口。"""
    pay = FakePayClient(QueryResult("not_found"))
    service, _, card = build(pay=pay)
    outcome = run(service.query(CODE, GROUP))

    assert outcome.state == "ok"
    assert card.calls == [CODE]
    assert "【点歌券状态】" in outcome.text
    assert TEXT_NO_PAY_ORDER in outcome.text
    assert "状态：已核销" in outcome.text
    assert "核销时间：2026/11/22 18:00:00" in outcome.text
    assert CODE not in outcome.text
    assert "2026****01" in outcome.text


def test_pay_not_found_and_card_not_found_reports_not_found():
    pay = FakePayClient(QueryResult("not_found"))
    card = FakeCardClient(default=CardStatus("not_found"))
    service, _, _ = build(pay=pay, card=card)
    outcome = run(service.query(CODE, GROUP))

    assert outcome.state == "not_found"
    assert outcome.text == TEXT_NOT_FOUND
    assert card.calls == [CODE]


def test_pay_not_found_without_voicehub_explains_the_gap():
    pay = FakePayClient(QueryResult("not_found"))
    service, _, card = build(config(voicehub_base_url="", voicehub_api_key=""), pay=pay)
    outcome = run(service.query(CODE, GROUP))

    assert outcome.state == "not_found"
    assert outcome.text == TEXT_NOT_FOUND_NO_VOICEHUB
    assert card.calls == []


def test_pay_not_found_and_card_error_is_an_error():
    pay = FakePayClient(QueryResult("not_found"))
    card = FakeCardClient(default=CardStatus("error", message="boom"))
    service, _, _ = build(pay=pay, card=card)
    outcome = run(service.query(CODE, GROUP))

    assert outcome.state == "error"
    assert "查询失败：" in outcome.text
    assert "boom" in outcome.text


def test_pay_transport_error_does_not_query_voicehub():
    pay = FakePayClient(QueryResult("error", message="VoiceHubPay 返回状态码 502"))
    service, _, card = build(pay=pay)
    outcome = run(service.query(QUERY, GROUP))

    assert outcome.state == "error"
    assert "查询失败：VoiceHubPay 返回状态码 502" in outcome.text
    assert card.calls == []


def test_pay_invalid_query_maps_to_invalid_state():
    pay = FakePayClient(QueryResult("invalid", message="格式不对"))
    service, _, _ = build(pay=pay)
    outcome = run(service.query(QUERY, GROUP))

    assert outcome.state == "invalid"
    assert outcome.text == TEXT_INVALID_QUERY


def test_show_full_code_applies_to_order_reply():
    service, _, _ = build(config(show_full_code=True))
    outcome = run(service.query(QUERY, GROUP))

    assert outcome.state == "ok"
    assert CODE in outcome.text
    assert "2026****01" not in outcome.text


def test_show_full_code_applies_to_card_only_reply():
    pay = FakePayClient(QueryResult("not_found"))
    service, _, _ = build(config(show_full_code=True), pay=pay)
    outcome = run(service.query(CODE, GROUP))

    assert outcome.state == "ok"
    assert f"券码：{CODE}" in outcome.text
