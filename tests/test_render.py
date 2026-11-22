"""渲染纯函数：金额、时间、状态映射、掩码与缺失字段。"""

from __future__ import annotations

import copy

import pytest

from astrbot_plugin_voicehub_coupon.lib.render import (
    format_cents,
    mask_code,
    render_card_only,
    render_reply,
    to_beijing,
)
from astrbot_plugin_voicehub_coupon.lib.texts import (
    TEXT_CARD_DISABLED,
    TEXT_CARD_ERROR,
    TEXT_CARD_NOT_FOUND,
    TEXT_NO_PAY_ORDER,
)

CODE = "20261122153000001234-001"
MASKED = "2026****01"


def payload() -> dict:
    """一份契约里的商城订单样例（深拷贝后再改，避免测试互相污染）。"""
    return {
        "ok": True,
        "found_by": "shop_order",
        "source": "shop",
        "order": {
            "order_no": "20261122153000001234",
            "source": "shop",
            "amount_cents": 990,
            "amount_paid_cents": 990,
            "currency": "CNY",
            "payment_status": "paid",
            "order_status": "active",
            "fulfillment_status": "success",
            "created_at": "2026-11-22T07:30:00.000Z",
            "paid_at": "2026-11-22T07:31:00.000Z",
            "fulfilled_at": "2026-11-22T07:32:00.000Z",
            "expires_at": None,
            "items": [
                {
                    "name": "点歌券",
                    "quantity": 1,
                    "unit_price_cents": 990,
                    "delivery_mode": "voicehub",
                }
            ],
            "afdian": None,
        },
        "coupons": [
            {
                "code": CODE,
                "masked_code": MASKED,
                "unit_no": CODE,
                "kind": "voicehub",
                "unit_status": "success",
                "voicehub_status": "success",
                "voicehub_error": None,
                "delivered_at": "2026-11-22T07:32:00.000Z",
            }
        ],
    }


def used_card() -> dict:
    return {
        "state": "ok",
        "data": {
            "code": CODE,
            "status": "USED",
            "note": "voicehubpay | source=shop | order=20261122153000001234",
            "createdAt": "2026-11-22T07:30:00.000Z",
            "createdAtText": "2026/11/22 15:30:00",
            "updatedAtText": "2026/11/22 18:00:00",
            "assignedAtText": "2026/11/22 15:31:00",
            "assignment": {
                "status": "USED",
                "assignedAtText": "2026/11/22 15:31:00",
                "usedAtText": "2026/11/22 18:00:00",
                "recycledAtText": None,
                "recycleReason": None,
                "failureReason": None,
            },
            "redeem": {
                "redeemedAtText": "2026/11/22 18:00:00",
                "source": "SCHEDULE_AUTO",
                "songId": 12,
                "songTitle": "告白气球",
                "songArtist": "周杰伦",
            },
        },
    }


@pytest.mark.parametrize(
    "value, expected",
    [
        (990, "9.90 元"),
        (0, "0.00 元"),
        (1, "0.01 元"),
        (123456, "1234.56 元"),
        (None, "—"),
        ("abc", "—"),
        ("1200", "12.00 元"),
    ],
)
def test_amount_is_converted_from_cents(value, expected):
    assert format_cents(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-11-22T07:30:00.000Z", "2026-11-22 15:30:00"),
        ("2026-11-22T07:30:00Z", "2026-11-22 15:30:00"),
        ("2026-11-22 07:30:00", "2026-11-22 15:30:00"),
        ("2026-11-22T15:30:00+08:00", "2026-11-22 15:30:00"),
        ("2026-11-22T07:30:00", "2026-11-22 15:30:00"),
        ("", "—"),
        ("not-a-time", "—"),
        (None, "—"),
    ],
)
def test_times_are_converted_to_beijing(value, expected):
    assert to_beijing(value) == expected


@pytest.mark.parametrize(
    "code, expected",
    [
        (CODE, MASKED),
        ("abcd1234", "ab****34"),
        ("abc", "***"),
        ("", ""),
        (None, ""),
    ],
)
def test_codes_are_masked(code, expected):
    assert mask_code(code) == expected


def test_reply_masks_code_by_default():
    text = render_reply(payload(), {CODE: used_card()})
    assert CODE not in text
    assert MASKED in text


def test_reply_shows_full_code_when_enabled():
    text = render_reply(payload(), {CODE: used_card()}, show_full_code=True)
    assert CODE in text
    assert MASKED not in text


def test_reply_contains_order_summary():
    text = render_reply(payload(), {CODE: used_card()})

    assert "【订单查询结果】" in text
    assert "命中方式：商城订单号" in text
    assert "订单号：20261122153000001234" in text
    assert "来源：商城" in text
    assert "支付：已支付" in text
    assert "订单：有效" in text
    assert "发货：已发货" in text
    assert "金额：9.90 元" in text
    assert "下单：2026-11-22 15:30:00" in text
    assert "支付：2026-11-22 15:31:00" in text
    assert "发货：2026-11-22 15:32:00" in text
    assert "商品：点歌券 ×1（9.90 元，发货：voicehub）" in text


def test_reply_shows_paid_amount_only_when_it_differs():
    assert "实付" not in render_reply(payload(), {CODE: used_card()})

    discounted = payload()
    discounted["order"]["amount_paid_cents"] = 500
    text = render_reply(discounted, {CODE: used_card()})
    assert "金额：9.90 元" in text
    assert "实付：5.00 元" in text


def test_reply_merges_voicehub_coupon_status_and_redeem_details():
    text = render_reply(payload(), {CODE: used_card()})

    assert "发货成功" in text
    assert "站点：已核销" in text
    assert "核销时间 2026/11/22 18:00:00" in text
    assert "来源 排期自动核销" in text
    assert "歌曲 《告白气球》- 周杰伦" in text
    # 券码只在掩码形态下出现
    assert CODE not in text


@pytest.mark.parametrize(
    "status, label",
    [
        ("AVAILABLE", "未使用"),
        ("ASSIGNED", "已派发"),
        ("LOCKED", "使用中"),
        ("REDEEMED", "已核销"),
        ("INVALID", "已作废"),
    ],
)
def test_card_code_status_labels(status, label):
    """CardCode.status 枚举必须全部有中文，未映射会直接把英文贴进群。"""
    card = used_card()
    card["data"]["status"] = status
    card["data"]["assignment"]["status"] = status
    text = render_reply(payload(), {CODE: card})
    assert f"站点：{label}" in text


def test_paid_order_does_not_show_reservation_expiry():
    body = payload()
    body["order"]["expires_at"] = "2026-11-22T08:00:00.000Z"
    text = render_reply(body, {CODE: used_card()})
    assert "过期" not in text


def test_unpaid_order_shows_reservation_expiry():
    body = payload()
    body["order"]["payment_status"] = "unpaid"
    body["order"]["paid_at"] = None
    body["order"]["expires_at"] = "2026-11-22T08:00:00.000Z"
    text = render_reply(body, {CODE: used_card()})
    assert "过期：2026-11-22 16:00:00" in text


def test_reply_reports_card_not_found():
    text = render_reply(payload(), {CODE: {"state": "not_found"}})
    assert TEXT_CARD_NOT_FOUND in text


def test_reply_reports_voicehub_not_configured():
    text = render_reply(payload(), {CODE: {"state": "disabled"}})
    assert TEXT_CARD_DISABLED in text
    # 未配置 VoiceHub 时订单与发货状态仍照常输出
    assert "订单号：20261122153000001234" in text
    assert "发货：已发货" in text


def test_reply_reports_card_query_error():
    text = render_reply(payload(), {CODE: {"state": "error"}})
    assert TEXT_CARD_ERROR in text


def test_reply_survives_missing_fields():
    empty = {"ok": True}
    text = render_reply(empty, {})
    assert "【订单查询结果】" in text
    assert "点歌券：暂无记录（可能尚未发货）" in text

    bare = {"order": {"order_no": "X12345678", "items": None, "afdian": None}, "coupons": [{}]}
    text = render_reply(bare, {})
    assert "订单号：X12345678" in text
    assert "点歌券（1 张）：" in text
    assert "1. —" in text


def test_reply_truncates_coupon_list_and_reports_remainder():
    body = payload()
    body["coupons"] = [
        {
            "code": f"2026112215300000{i:04d}-001",
            "masked_code": f"2026****{i % 100:02d}",
            "unit_status": "success",
        }
        for i in range(14)
    ]
    text = render_reply(body, {}, max_coupons=10)
    assert "点歌券（14 张）：" in text
    assert "…还有 4 张未显示（只展示前 10 张）" in text
    assert text.count("发货成功") == 10


def test_reply_renders_afdian_order():
    body = payload()
    body["found_by"] = "afdian_order"
    body["source"] = "afdian"
    body["order"] = {
        "order_no": "202611220001",
        "source": "afdian",
        "amount_cents": 990,
        "amount_paid_cents": 990,
        "payment_status": "paid",
        "order_status": "active",
        "fulfillment_status": "success",
        "created_at": "2026-11-22 07:30:00",
        "paid_at": "2026-11-22 07:31:00",
        "items": [{"name": "点歌券（爱发电）", "quantity": 1, "unit_price_cents": 990}],
        "afdian": {"trade_no": "T202611220001", "plan_id": "plan-1", "sku_detail": "点歌券"},
    }
    body["coupons"] = [
        {"code": "202611220001", "masked_code": "2026****01", "unit_status": "success"}
    ]
    text = render_reply(body, {})
    assert "命中方式：爱发电订单号" in text
    assert "来源：爱发电" in text
    assert "爱发电：交易号 T202611220001 · 方案 plan-1 · SKU 点歌券" in text
    assert "2026-11-22 15:30:00" in text


def test_reply_cleans_control_characters_and_unknown_status():
    body = payload()
    body["order"]["payment_status"] = "weird_status"
    body["order"]["items"] = [{"name": "点歌\n券\x00", "quantity": 2, "unit_price_cents": 100}]
    text = render_reply(body, {})
    assert "支付：weird_status" in text
    assert "\x00" not in text
    assert "点歌 券 ×2" in text


def test_render_card_only_shows_order_gap_and_status():
    text = render_card_only(used_card(), CODE)

    assert "【点歌券状态】" in text
    assert f"订单：{TEXT_NO_PAY_ORDER}" in text
    assert f"券码：{MASKED}" in text
    assert "状态：已核销" in text
    assert "核销时间：2026/11/22 18:00:00" in text
    assert "歌曲：《告白气球》- 周杰伦" in text
    assert CODE not in text


def test_render_card_only_can_show_full_code():
    text = render_card_only(used_card(), CODE, show_full_code=True)
    assert f"券码：{CODE}" in text


def test_render_card_only_survives_empty_data():
    text = render_card_only({"state": "ok", "data": {}}, "ABCD1234")
    assert "券码：AB****34" in text
    assert TEXT_NO_PAY_ORDER in text


def test_render_does_not_copy_internal_note_or_identity_fields():
    card = used_card()
    card["data"]["holder"] = {"name": "张三", "student_id": "2026001"}
    text = render_reply(payload(), {CODE: card})
    assert "张三" not in text
    assert "2026001" not in text
    assert "voicehubpay | source=shop" not in text
