"""VoiceHubPay 客户端：请求形状、鉴权头与错误映射。"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from astrbot_plugin_voicehub_coupon.lib.config import CouponConfig
from astrbot_plugin_voicehub_coupon.lib.voicehubpay import VoiceHubPayClient

from support import FakeResponse, recorded, run, session_factory

QUERY = "20261122153000001234"

CONFIG = CouponConfig.from_mapping(
    {
        "voicehubpay_base_url": "https://pay.example.com",
        "voicehubpay_bot_token": "bot-secret",
        "request_timeout_seconds": 7,
    }
)

OK_BODY = {
    "ok": True,
    "found_by": "shop_order",
    "source": "shop",
    "order": {"order_no": QUERY, "amount_cents": 990},
    "coupons": [{"code": f"{QUERY}-001", "masked_code": "2026****01"}],
}


def call(text: str = QUERY, response=None, error=None, config=CONFIG):
    recorder: list = []
    client = VoiceHubPayClient(
        config, session_factory=session_factory(recorder, response, error)
    )
    return run(client.query(text)), recorder


def test_posts_the_contract_request():
    result, recorder = call(response=FakeResponse(200, OK_BODY))

    assert result.state == "ok"
    assert result.payload["found_by"] == "shop_order"
    assert len(recorder) == 1

    request = recorded(recorder)
    assert request["method"] == "POST"
    assert request["url"] == "https://pay.example.com/api/bot/coupon-query"
    assert request["headers"]["X-Bot-Token"] == "bot-secret"
    assert request["json"] == {"query": QUERY}
    assert request["allow_redirects"] is False
    assert request["timeout"].total == 7


@pytest.mark.parametrize(
    "status, body, state, needle",
    [
        (404, {"ok": False, "error": "NOT_FOUND"}, "not_found", ""),
        (400, {"ok": False, "error": "INVALID_QUERY"}, "invalid", ""),
        (401, {"ok": False, "error": "UNAUTHORIZED"}, "error", "令牌"),
        (403, {}, "error", "令牌"),
        (503, {"ok": False, "error": "BOT_QUERY_DISABLED"}, "error", "未开启"),
        (502, {}, "error", "502"),
        (200, {"ok": False, "error": "NOT_FOUND"}, "not_found", ""),
        (200, {"ok": False, "error": "UNAUTHORIZED"}, "error", "令牌"),
        (200, {"ok": False, "error": "BOT_QUERY_DISABLED"}, "error", "未开启"),
        (200, {"ok": False, "error": "WHATEVER"}, "error", "无法识别"),
    ],
)
def test_status_and_error_mapping(status, body, state, needle):
    result, _ = call(response=FakeResponse(status, body))
    assert result.state == state
    if needle:
        assert needle in result.message
    assert "bot-secret" not in result.message


def test_redirect_is_rejected_to_keep_the_token_home():
    result, _ = call(response=FakeResponse(302, {}))
    assert result.state == "error"
    assert "重定向" in result.message


def test_non_json_body_is_reported_as_unrecognised():
    result, _ = call(response=FakeResponse(200, {}, json_error=True))
    assert result.state == "error"
    assert "无法识别" in result.message


@pytest.mark.parametrize(
    "error, needle",
    [
        (asyncio.TimeoutError(), "超时"),
        (aiohttp.ClientConnectionError("boom"), "无法连接"),
        (RuntimeError("boom"), "请求查询服务失败"),
    ],
)
def test_network_errors_are_mapped_to_readable_text(error, needle):
    result, recorder = call(error=error)
    assert result.state == "error"
    assert needle in result.message
    assert "bot-secret" not in result.message
    assert len(recorder) == 1


def test_missing_config_returns_error_without_network():
    result, recorder = call(config=CouponConfig.from_mapping({}))
    assert result.state == "error"
    assert "未配置" in result.message
    assert recorder == []


def test_empty_payload_is_not_treated_as_success():
    result, _ = call(response=FakeResponse(200, {}))
    assert result.state == "error"
    assert result.payload == {}
