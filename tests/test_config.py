"""配置解析：默认值、群号规整、布尔/整数容错与就绪判定。"""

from __future__ import annotations

import pytest

from astrbot_plugin_voicehubpay.lib.config import (
    DEFAULT_MAX_COUPONS,
    DEFAULT_TIMEOUT,
    MAX_COUPONS_LIMIT,
    CouponConfig,
    dropped_group_values,
    normalize_group_ids,
)


def test_defaults_when_config_is_missing():
    config = CouponConfig.from_mapping(None)

    assert config.voicehubpay_base_url == ""
    assert config.voicehubpay_bot_token == ""
    assert config.voicehub_base_url == ""
    assert config.voicehub_api_key == ""
    assert config.group_ids == []
    assert config.auto_query is True
    assert config.allow_private is False
    assert config.show_full_code is False
    assert config.request_timeout_seconds == DEFAULT_TIMEOUT == 10
    assert config.max_coupons == DEFAULT_MAX_COUPONS == 10


def test_config_cannot_be_mutated():
    """配置以 frozen dataclass 暴露，运行期不会被意外改写。"""
    config = CouponConfig.from_mapping({"auto_query": True})
    with pytest.raises(Exception):
        config.auto_query = False  # type: ignore[misc]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("123456789, 987654321\n555555", ["123456789", "987654321", "555555"]),
        ("123456789,123456789, 123456789", ["123456789"]),
        ("  123456789  ", ["123456789"]),
        (["123456789", 987654321], ["123456789", "987654321"]),
        ("", []),
        (None, []),
        (123456789, []),
    ],
)
def test_group_ids_are_normalized(raw, expected):
    assert normalize_group_ids(raw) == expected


def test_group_ids_drop_session_strings_and_urls():
    raw = "123456789, default:GroupMessage:1, https://example.com/g, bad:group"
    assert normalize_group_ids(raw) == ["123456789"]
    assert dropped_group_values(raw) == [
        "default:GroupMessage:1",
        "https://example.com/g",
        "bad:group",
    ]


def test_group_ids_from_config_mapping():
    config = CouponConfig.from_mapping({"group_ids": "123456789\n987654321"})
    assert config.group_ids == ["123456789", "987654321"]
    assert config.is_group_allowed(123456789) is True
    assert config.is_group_allowed("987654321") is True
    assert config.is_group_allowed("000") is False
    assert config.is_group_allowed("") is False
    assert config.is_group_allowed(None) is False


@pytest.mark.parametrize(
    "value, expected",
    [(True, True), (False, False), ("true", True), ("on", True), ("1", True),
     ("false", False), ("off", False), ("0", False), ("bogus", True), (None, True)],
)
def test_auto_query_bool_parsing(value, expected):
    assert CouponConfig.from_mapping({"auto_query": value}).auto_query is expected


@pytest.mark.parametrize(
    "value, expected",
    [("true", True), ("yes", True), ("false", False), ("no", False), (1, False)],
)
def test_allow_private_default_is_false(value, expected):
    """非布尔字符串按默认值 false 处理，避免「随便写点啥就开了私聊」。"""
    assert CouponConfig.from_mapping({"allow_private": value}).allow_private is expected


@pytest.mark.parametrize(
    "value, expected",
    [(0, 1), (-5, 1), (999, 60), ("abc", 10), (None, 10), (20, 20), ("7", 7)],
)
def test_timeout_is_clamped(value, expected):
    assert CouponConfig.from_mapping({"request_timeout_seconds": value}).request_timeout_seconds == expected


@pytest.mark.parametrize(
    "value, expected",
    [(0, 1), (-3, 1), (100, MAX_COUPONS_LIMIT), ("x", 10), (None, 10), (3, 3)],
)
def test_max_coupons_is_clamped(value, expected):
    assert CouponConfig.from_mapping({"max_coupons": value}).max_coupons == expected


def test_urls_lose_trailing_slashes_and_spaces():
    config = CouponConfig.from_mapping(
        {
            "voicehubpay_base_url": "  https://pay.example.com/  ",
            "voicehub_base_url": "https://voicehub.example.com///",
        }
    )
    assert config.voicehubpay_base_url == "https://pay.example.com"
    assert config.voicehub_base_url == "https://voicehub.example.com"


def test_readiness_flags_and_missing_settings():
    pay_only = CouponConfig.from_mapping(
        {"voicehubpay_base_url": "https://pay.example.com", "voicehubpay_bot_token": "t"}
    )
    assert pay_only.pay_ready is True
    assert pay_only.voicehub_ready is False
    assert pay_only.missing_pay_settings() == []

    incomplete = CouponConfig.from_mapping({"voicehubpay_base_url": "https://pay.example.com"})
    assert incomplete.pay_ready is False
    assert incomplete.missing_pay_settings() == ["voicehubpay_bot_token"]

    empty = CouponConfig.from_mapping({})
    assert empty.missing_pay_settings() == ["voicehubpay_base_url", "voicehubpay_bot_token"]


def test_non_mapping_config_object_with_get_is_supported():
    class ConfigLike:
        data = {"group_ids": "123456789", "auto_query": "false", "max_coupons": "4"}

        def get(self, key, default=None):
            return self.data.get(key, default)

    config = CouponConfig.from_mapping(ConfigLike())
    assert config.group_ids == ["123456789"]
    assert config.auto_query is False
    assert config.max_coupons == 4
