"""插件入口：指令闸门、被动识别的静默规则与降级分支。"""

from __future__ import annotations

import logging
import types

import pytest

from astrbot_plugin_voicehub_coupon.lib.service import Outcome
from astrbot_plugin_voicehub_coupon.lib.texts import (
    TEXT_CARD_DISABLED,
    TEXT_GROUP_DENIED,
    TEXT_NOT_FOUND,
    TEXT_PAY_NOT_CONFIGURED,
    TEXT_PRIVATE_DENIED,
    TEXT_USAGE,
)
from astrbot_plugin_voicehub_coupon.lib.voicehub import CardStatus
from astrbot_plugin_voicehub_coupon.lib.voicehubpay import QueryResult

from support import FakeEvent, collect, run

QUERY = "20261122153000001234"
CODE = f"{QUERY}-001"
GROUP = "123456789"


def payload() -> dict:
    return {
        "ok": True,
        "found_by": "shop_order",
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
            {"code": CODE, "masked_code": "2026****01", "unit_status": "success"}
        ],
    }


CARD_DATA = {
    "code": CODE,
    "status": "USED",
    "assignment": {"status": "USED", "usedAtText": "2026/11/22 18:00:00"},
    "redeem": {
        "redeemedAtText": "2026/11/22 18:00:00",
        "source": "SCHEDULE_AUTO",
        "songTitle": "告白气球",
        "songArtist": "周杰伦",
    },
}


class StubService:
    def __init__(self, outcome=None):
        self.outcome = outcome or Outcome("ok", "查询结果文本")
        self.calls: list = []

    async def query(self, text, group_id=""):
        self.calls.append((text, group_id))
        return self.outcome


class FakePay:
    def __init__(self, result):
        self.result = result
        self.calls: list = []

    async def query(self, text):
        self.calls.append(text)
        return self.result


class FakeCard:
    def __init__(self, result):
        self.result = result
        self.calls: list = []

    async def status(self, code):
        self.calls.append(code)
        return self.result


def make_plugin(plugin_module, **overrides):
    config = {
        "voicehubpay_base_url": "https://pay.example.com",
        "voicehubpay_bot_token": "bot-secret",
        "voicehub_base_url": "",
        "voicehub_api_key": "",
        "group_ids": GROUP,
        "auto_query": True,
        "allow_private": False,
        "show_full_code": False,
        "request_timeout_seconds": 10,
        "max_coupons": 10,
    }
    config.update(overrides)
    return plugin_module.VoiceHubCouponPlugin(types.SimpleNamespace(), config)


@pytest.mark.parametrize("handler", ["coupon_query", "order_query"])
def test_both_commands_query_the_whitelisted_group(plugin, handler):
    instance = make_plugin(plugin)
    instance.service = StubService()
    event = FakeEvent(f"/{handler} {QUERY}", group=GROUP)

    replies = run(collect(getattr(instance, handler)(event, QUERY)))

    assert replies == ["查询结果文本"]
    assert event.replies == ["查询结果文本"]
    assert instance.service.calls == [(QUERY, GROUP)]


def test_command_in_other_group_is_refused_without_query(plugin):
    instance = make_plugin(plugin)
    instance.service = StubService()
    event = FakeEvent(f"/查券 {QUERY}", group="999999999")

    replies = run(collect(instance.coupon_query(event, QUERY)))

    assert replies == [TEXT_GROUP_DENIED]
    assert instance.service.calls == []


def test_private_command_is_refused_by_default(plugin):
    instance = make_plugin(plugin)
    instance.service = StubService()
    event = FakeEvent(f"/查券 {QUERY}")

    replies = run(collect(instance.coupon_query(event, QUERY)))

    assert replies == [TEXT_PRIVATE_DENIED]
    assert instance.service.calls == []


def test_private_command_works_when_allowed(plugin):
    instance = make_plugin(plugin, allow_private=True)
    instance.service = StubService()
    event = FakeEvent(f"/查券 {QUERY}")

    replies = run(collect(instance.coupon_query(event, QUERY)))

    assert replies == ["查询结果文本"]
    assert instance.service.calls == [(QUERY, "")]


def test_missing_voicehubpay_config_returns_hint(plugin):
    instance = make_plugin(plugin, voicehubpay_base_url="", voicehubpay_bot_token="")
    instance.service.pay_client = FakePay(QueryResult("ok", payload()))
    event = FakeEvent(f"/查券 {QUERY}", group=GROUP)

    replies = run(collect(instance.coupon_query(event, QUERY)))

    assert replies == [TEXT_PAY_NOT_CONFIGURED]
    assert instance.service.pay_client.calls == []


def test_empty_command_argument_shows_usage(plugin):
    instance = make_plugin(plugin)
    instance.service.pay_client = FakePay(QueryResult("ok", payload()))
    event = FakeEvent("/查券", group=GROUP)

    replies = run(collect(instance.coupon_query(event, "")))

    assert replies == [TEXT_USAGE]
    assert instance.service.pay_client.calls == []


def test_passive_candidate_replies_and_stops_event(plugin):
    instance = make_plugin(plugin)
    instance.service = StubService()
    event = FakeEvent(QUERY, group=GROUP)

    replies = run(collect(instance.on_coupon_candidate(event)))

    assert replies == ["查询结果文本"]
    assert event.stopped is True
    assert instance.service.calls == [(QUERY, GROUP)]


@pytest.mark.parametrize(
    "outcome",
    [
        Outcome("not_found", TEXT_NOT_FOUND),
        Outcome("error", "查询失败：boom"),
        Outcome("throttled", "查询过于频繁"),
        Outcome("disabled", TEXT_PAY_NOT_CONFIGURED),
    ],
)
def test_passive_unhelpful_outcomes_stay_silent(plugin, outcome):
    instance = make_plugin(plugin)
    instance.service = StubService(outcome)
    event = FakeEvent(QUERY, group=GROUP)

    replies = run(collect(instance.on_coupon_candidate(event)))

    assert replies == []
    assert event.stopped is False


def test_passive_in_other_group_is_ignored(plugin):
    instance = make_plugin(plugin)
    instance.service = StubService()
    event = FakeEvent(QUERY, group="999999999")

    replies = run(collect(instance.on_coupon_candidate(event)))

    assert replies == []
    assert instance.service.calls == []


def test_passive_is_off_when_auto_query_disabled(plugin):
    instance = make_plugin(plugin, auto_query=False)
    instance.service = StubService()
    event = FakeEvent(QUERY, group=GROUP)

    replies = run(collect(instance.on_coupon_candidate(event)))

    assert replies == []
    assert instance.service.calls == []


def test_passive_filter_only_accepts_group_candidates(plugin):
    candidate_filter = plugin._CouponCandidateFilter()

    assert candidate_filter.filter(FakeEvent(QUERY, group=GROUP)) is True
    assert candidate_filter.filter(FakeEvent(f"/查券 {QUERY}", group=GROUP)) is False
    assert candidate_filter.filter(FakeEvent("大家晚上好", group=GROUP)) is False
    assert candidate_filter.filter(FakeEvent(QUERY)) is False
    assert candidate_filter.filter(FakeEvent("", group=GROUP)) is False


def test_passive_end_to_end_degrades_without_voicehub(plugin):
    """未配置 VoiceHub：群内发订单号仍回复订单与发货状态，券状态显示降级文案。"""
    instance = make_plugin(plugin)
    instance.service.pay_client = FakePay(QueryResult("ok", payload()))
    instance.service.card_client = FakeCard(CardStatus("ok", dict(CARD_DATA)))
    event = FakeEvent(QUERY, group=GROUP)

    replies = run(collect(instance.on_coupon_candidate(event)))

    assert len(replies) == 1
    text = replies[0]
    assert TEXT_CARD_DISABLED in text
    assert f"订单号：{QUERY}" in text
    assert "发货：已发货" in text
    assert instance.service.card_client.calls == []
    assert event.stopped is True


def test_passive_end_to_end_falls_back_to_card_status(plugin):
    """VoiceHubPay 404 但 VoiceHub 有券：回复点歌券状态并说明订单缺口。"""
    instance = make_plugin(
        plugin,
        voicehub_base_url="https://voicehub.example.com",
        voicehub_api_key="vh-key",
    )
    instance.service.pay_client = FakePay(QueryResult("not_found"))
    instance.service.card_client = FakeCard(CardStatus("ok", dict(CARD_DATA)))
    event = FakeEvent(CODE, group=GROUP)

    replies = run(collect(instance.on_coupon_candidate(event)))

    assert len(replies) == 1
    text = replies[0]
    assert "【点歌券状态】" in text
    assert "未关联 VoiceHubPay 订单（可能由站点直接发放）" in text
    assert "状态：已核销" in text
    assert CODE not in text
    assert event.stopped is True


def test_command_reply_never_contains_token_or_base_url(plugin):
    instance = make_plugin(plugin)
    instance.service.pay_client = FakePay(QueryResult("ok", payload()))
    event = FakeEvent(f"/查券 {QUERY}", group=GROUP)

    replies = run(collect(instance.coupon_query(event, QUERY)))

    text = replies[0]
    assert "bot-secret" not in text
    assert "pay.example.com" not in text
    assert "voicehub.example.com" not in text


def test_initialize_logs_missing_settings_and_bad_groups(plugin, caplog):
    instance = make_plugin(
        plugin,
        voicehubpay_base_url="",
        voicehubpay_bot_token="",
        group_ids="bad:group",
    )
    with caplog.at_level(logging.INFO, logger="test"):
        run(instance.initialize())

    messages = [record.getMessage() for record in caplog.records]
    assert any("voicehubpay_base_url" in message for message in messages)
    assert any("voicehub_api_key" in message for message in messages)
    assert any("bad:group" in message for message in messages)
