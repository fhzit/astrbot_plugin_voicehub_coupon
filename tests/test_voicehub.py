"""VoiceHub 券状态客户端：请求形状、鉴权头与降级行为。"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from astrbot_plugin_voicehubpay.lib.config import CouponConfig
from astrbot_plugin_voicehubpay.lib.voicehub import VoiceHubCardClient

from support import FakeResponse, recorded, run, session_factory

CODE = "20261122153000001234-001"

CONFIG = CouponConfig.from_mapping(
    {
        "voicehub_base_url": "https://voicehub.example.com",
        "voicehub_api_key": "vh-key",
        "request_timeout_seconds": 5,
    }
)

OK_BODY = {
    "success": True,
    "data": {
        "code": CODE,
        "status": "AVAILABLE",
        "createdAt": "2026-11-22T07:30:00.000Z",
    },
}


def call(code: str = CODE, response=None, error=None, config=CONFIG):
    recorder: list = []
    client = VoiceHubCardClient(
        config, session_factory=session_factory(recorder, response, error)
    )
    return run(client.status(code)), recorder


def test_gets_the_contract_request():
    result, recorder = call(response=FakeResponse(200, OK_BODY))

    assert result.state == "ok"
    assert result.data["status"] == "AVAILABLE"
    assert len(recorder) == 1

    request = recorded(recorder)
    assert request["method"] == "GET"
    assert request["url"] == "https://voicehub.example.com/api/open/card-codes/status"
    assert request["params"] == {"code": CODE}
    assert request["headers"]["x-api-key"] == "vh-key"
    assert request["allow_redirects"] is False
    assert request["timeout"].total == 5


def test_missing_config_is_disabled_without_network():
    for config in (
        CouponConfig.from_mapping({}),
        CouponConfig.from_mapping({"voicehub_base_url": "https://voicehub.example.com"}),
        CouponConfig.from_mapping({"voicehub_api_key": "vh-key"}),
    ):
        result, recorder = call(config=config)
        assert result.state == "disabled"
        assert recorder == []


def test_not_found_is_distinct_from_error():
    result, _ = call(response=FakeResponse(404, {"success": False, "message": "点歌券不存在"}))
    assert result.state == "not_found"


@pytest.mark.parametrize(
    "status, needle",
    [
        (401, "card-codes:read"),
        (403, "card-codes:read"),
        (500, "500"),
        (302, "重定向"),
    ],
)
def test_error_mapping(status, needle):
    result, _ = call(response=FakeResponse(status, {}))
    assert result.state == "error"
    assert needle in result.message
    assert "vh-key" not in result.message


@pytest.mark.parametrize(
    "error, needle",
    [
        (asyncio.TimeoutError(), "超时"),
        (aiohttp.ClientConnectionError("boom"), "无法连接"),
    ],
)
def test_network_errors_are_readable(error, needle):
    result, recorder = call(error=error)
    assert result.state == "error"
    assert needle in result.message
    assert len(recorder) == 1


def test_success_without_data_is_an_error():
    result, _ = call(response=FakeResponse(200, {"success": True, "data": None}))
    assert result.state == "error"
    assert "空的状态数据" in result.message


def test_non_json_body_is_an_error():
    result, _ = call(response=FakeResponse(200, {}, json_error=True))
    assert result.state == "error"
    assert "无法识别" in result.message
