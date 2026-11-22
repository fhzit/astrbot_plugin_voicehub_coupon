"""被动识别与查询串规整。"""

from __future__ import annotations

import pytest

from astrbot_plugin_voicehub_coupon.lib.detect import looks_like_coupon_query, normalize_query


@pytest.mark.parametrize(
    "text",
    [
        "20261122153000001234",
        "20261122153000001234-001",
        "20261122_153000_1234",
        "ABCD1234",
        "abc-123456",
        "1234567890123456",
        " 20261122153000001234 ",
    ],
)
def test_accepts_order_numbers_and_codes(text):
    assert looks_like_coupon_query(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "    ",
        "abc1234",                 # 7 字符，短于下限
        "abcdefgh",                # 不含数字
        "1234567890",              # 纯数字 10 位，像 QQ 号而不是订单号
        "20261122 1530",           # 含空白，不是单行候选
        "查券12345",                # 含非 ASCII
        "/20261122153000001234",   # 指令形状
        "20261122\n1122",          # 多行
        "A" * 129,                 # 超过 128 字符
        "2026.11.22.1234",         # 含未允许的标点
    ],
)
def test_rejects_non_candidates(text):
    assert looks_like_coupon_query(text) is False


@pytest.mark.parametrize("value", [None, 20261122, 1234.5, ["20261122"], b"20261122"])
def test_rejects_non_string_values(value):
    assert looks_like_coupon_query(value) is False


@pytest.mark.parametrize(
    "text, expected",
    [
        (" 20261122153000001234 ", "20261122153000001234"),
        ("20261122153000001234-001", "20261122153000001234-001"),
        ("ABCD1234", "ABCD1234"),
        ("", ""),
        ("   ", ""),
        ("two words", ""),
        ("/查券", ""),
        ("2026/1122", "2026/1122"),
        ("2026\t1122", ""),
        ("2026\x001122", ""),
        ("A" * 65, "A" * 65),
        ("A" * 129, ""),
        (None, ""),
    ],
)
def test_normalize_query(text, expected):
    assert normalize_query(text) == expected
