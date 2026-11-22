"""把 VoiceHubPay / VoiceHub 的查询结果渲染成聊天纯文本。

设计约束：

- 纯函数：不读配置、不触网，输入即输出，便于单测；
- 金额统一由整数「分」转「元」；
- 时间统一转北京时间（Asia/Shanghai，固定 +08:00，无夏令时）；
- 券码默认掩码，只有调用方显式要求时才输出明文；
- 上游字段先清洗再拼接（去控制字符、折叠空白、截断），缺失用「—」占位，
  任何畸形字段都不得抛异常，也不得把内部 URL / 令牌带进文案。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from .texts import (
    TEXT_CARD_DISABLED,
    TEXT_CARD_ERROR,
    TEXT_CARD_NOT_FOUND,
    TEXT_NO_PAY_ORDER,
)

DEFAULT_COUPON_LIMIT = 10
EMPTY = "—"
MAX_FIELD_CHARS = 120

# 北京无夏令时，固定 +08:00 即可，不依赖容器里的 tzdata。
BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")

FOUND_BY = {
    "shop_order": "商城订单号",
    "afdian_order": "爱发电订单号",
    "coupon_code": "点歌券码",
}

ORDER_SOURCE = {
    "shop": "商城",
    "afdian": "爱发电",
}

PAYMENT_STATUS = {
    "paid": "已支付",
    "pending": "待支付",
    "unpaid": "待支付",
    "failed": "支付失败",
    "refunded": "已退款",
    "expired": "已过期",
    "closed": "已关闭",
    "cancelled": "已取消",
}

ORDER_STATUS = {
    "active": "有效",
    "pending": "待处理",
    "closed": "已关闭",
    "expired": "已过期",
    "cancelled": "已取消",
}

FULFILLMENT_STATUS = {
    "success": "已发货",
    "pending": "待发货",
    "processing": "发货中",
    "partial": "部分发货",
    "failed": "发货失败",
    "none": "未发货",
}

UNIT_STATUS = {
    "success": "成功",
    "pending": "处理中",
    "processing": "处理中",
    "failed": "失败",
    "skipped": "已跳过",
    "none": "未发货",
}

# 券状态（CardCode.status）与派发记录状态（assignment.status）共用一套映射。
COUPON_STATUS = {
    "AVAILABLE": "未使用",
    "ASSIGNED": "已派发",
    "LOCKED": "使用中",
    "REDEEMED": "已核销",
    "INVALID": "已作废",
    "USED": "已核销",
    "RECYCLED": "已回收",
    "FAILED": "派发失败",
}

REDEEM_SOURCE = {
    "SCHEDULE_AUTO": "排期自动核销",
    "SCHEDULE": "排期核销",
    "MANUAL": "人工核销",
    "API": "接口核销",
}

_WHITESPACE_RE = re.compile(r"\s+")


def _clean(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    """清洗单个字段：去掉控制/不可打印字符，折叠空白，超长截断。"""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    text = str(value)
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _field(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    """清洗字段，空值统一显示为「—」。"""
    return _clean(value, limit) or EMPTY


def _status(mapping: Mapping[str, str], value: Any) -> str:
    """把英文枚举翻成中文；未知取值原样展示（清洗后），空值给「—」。"""
    text = _clean(value, 40)
    if not text:
        return EMPTY
    return mapping.get(text, mapping.get(text.lower(), text))


def format_cents(value: Any) -> str:
    """整数分 → 「9.90 元」。

    非法/缺失返回「—」，绝不把 ``None`` 或浮点误差带进回复。
    """
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return EMPTY
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    return f"{sign}{amount // 100}.{amount % 100:02d} 元"


def to_beijing(value: Any) -> str:
    """ISO 8601 / SQLite 时间串 → 北京时间 ``YYYY-MM-DD HH:MM:SS``。

    - ``2026-11-22T07:30:00.000Z``（UTC）→ ``2026-11-22 15:30:00``
    - ``2026-11-22 07:30:00``（库内 naive 字符串，按 UTC 解释）→ 同上
    - 已带 ``+08:00`` 的串保持原时刻

    无法解析时返回「—」：宁可显示缺失，也不把原始字符串贴进聊天。
    """
    text = _clean(value, 64)
    if not text:
        return EMPTY
    normalized = text
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return EMPTY
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def mask_code(code: Any) -> str:
    """券码掩码：保留首 4 位与末 2 位，中间固定 4 个星号。

    ``20261122153000001234-001`` → ``2026****01``，与 VoiceHubPay 返回的
    ``masked_code`` 形状一致。
    """
    text = _clean(code, 128)
    if not text:
        return ""
    length = len(text)
    if length <= 4:
        return "*" * length
    if length <= 8:
        return text[:2] + "*" * (length - 4) + text[-2:]
    return f"{text[:4]}****{text[-2:]}"


def display_code(code: Any, show_full_code: bool = False, masked: Any = None) -> str:
    """按配置决定展示明文还是掩码；没有明文时回退服务端给的 masked_code。"""
    full = _clean(code, 128)
    if full:
        return full if show_full_code else mask_code(full)
    return _field(masked, 128)


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """只接受映射，其余形态一律当空映射处理（上游字段可能为 null）。"""
    return value if isinstance(value, Mapping) else {}


def _card_data(card: Any) -> Mapping[str, Any]:
    """取出券状态里的 ``data`` 段；形态不对时给空映射。"""
    if isinstance(card, Mapping):
        data = card.get("data")
        if isinstance(data, Mapping):
            return data
    return {}


def _card_time(data: Mapping[str, Any], iso_key: str, text_key: str) -> str:
    """优先把 ISO 时间转北京时间，缺失时用服务端已生成好的北京时间文本。"""
    converted = to_beijing(data.get(iso_key))
    if converted != EMPTY:
        return converted
    return _field(data.get(text_key))


def _song_text(redeem: Mapping[str, Any]) -> str:
    """核销歌曲：``《歌名》- 歌手``，缺项时只显示有的部分。"""
    title = _clean(redeem.get("songTitle"), 60)
    artist = _clean(redeem.get("songArtist"), 40)
    if not title and not artist:
        return EMPTY
    if not artist:
        return f"《{title}》"
    if not title:
        return artist
    return f"《{title}》- {artist}"


def _card_pairs(data: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """VoiceHub 券状态里可展示的字段（不含持有人等身份信息）。"""
    assignment = _as_mapping(data.get("assignment"))
    redeem = _as_mapping(data.get("redeem"))
    pairs: List[Tuple[str, str]] = [
        ("状态", _status(COUPON_STATUS, data.get("status") or assignment.get("status"))),
        ("派发时间", _field(assignment.get("assignedAtText") or data.get("assignedAtText"))),
        ("核销时间", _field(assignment.get("usedAtText") or redeem.get("redeemedAtText"))),
        ("回收时间", _field(assignment.get("recycledAtText"))),
        ("来源", _status(REDEEM_SOURCE, redeem.get("source"))),
        ("歌曲", _song_text(redeem)),
        ("回收原因", _field(assignment.get("recycleReason"), 80)),
        ("失败原因", _field(assignment.get("failureReason"), 80)),
        ("生成时间", _card_time(data, "createdAt", "createdAtText")),
        ("更新时间", _field(data.get("updatedAtText"))),
    ]
    return [(label, value) for label, value in pairs if value != EMPTY]


def _card_headline(card: Any) -> str:
    """券的站点状态短语，用于订单列表里的单行摘要。"""
    if not isinstance(card, Mapping):
        return ""
    state = _clean(card.get("state"), 20)
    if state == "disabled":
        return TEXT_CARD_DISABLED
    if state == "error":
        return TEXT_CARD_ERROR
    if state == "not_found":
        return TEXT_CARD_NOT_FOUND
    if state != "ok":
        return ""
    data = _card_data(card)
    status = _status(COUPON_STATUS, data.get("status"))
    if status == EMPTY:
        assignment = _as_mapping(data.get("assignment"))
        status = _status(COUPON_STATUS, assignment.get("status"))
    return "" if status == EMPTY else f"站点：{status}"


def _card_detail_text(card: Any) -> str:
    """券状态里可压缩进一行的字段。

    生成/更新时间只在与订单无关的「点歌券状态」视图里展示：订单列表已经给了
    订单时间线，再塞两个时间戳会把这一行拉到手机屏幕之外。
    """
    if not isinstance(card, Mapping) or _clean(card.get("state"), 20) != "ok":
        return ""
    hidden = {"状态", "生成时间", "更新时间"}
    pairs = [(label, value) for label, value in _card_pairs(_card_data(card)) if label not in hidden]
    return " · ".join(f"{label} {value}" for label, value in pairs)


def _items_text(items: Any) -> str:
    """订单商品摘要：``点歌券 ×1（9.90 元，发货：voicehub）``。"""
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return ""
    parts: List[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = _clean(item.get("name"), 40) or "商品"
        quantity = _positive_int(item.get("quantity"), 0)
        text = f"{name} ×{quantity}" if quantity > 0 else name
        extras: List[str] = []
        unit_price = format_cents(item.get("unit_price_cents"))
        if unit_price != EMPTY:
            extras.append(unit_price)
        mode = _clean(item.get("delivery_mode"), 20)
        if mode:
            extras.append(f"发货：{mode}")
        if extras:
            text += f"（{'，'.join(extras)}）"
        parts.append(text)
    return "；".join(parts)


def _afdian_text(value: Any) -> str:
    """爱发电订单附加信息。"""
    if not isinstance(value, Mapping):
        return ""
    parts: List[str] = []
    for label, key in (("交易号", "trade_no"), ("方案", "plan_id"), ("SKU", "sku_detail")):
        item = _clean(value.get(key), 60)
        if item:
            parts.append(f"{label} {item}")
    return " · ".join(parts)


def _coupon_block(
    index: int,
    coupon: Mapping[str, Any],
    card_statuses: Mapping[str, Any],
    show_full_code: bool,
) -> List[str]:
    """单张券的两行摘要：标题行 + 缩进的时间/核销详情行。"""
    code = _clean(coupon.get("code"), 128)
    shown = display_code(code, show_full_code, coupon.get("masked_code"))
    headline = [f"{index}. {shown}"]

    unit = _status(UNIT_STATUS, coupon.get("unit_status"))
    if unit != EMPTY:
        headline.append(f"发货{unit}")

    kind = _clean(coupon.get("kind"), 20).lower()
    if kind == "card":
        # 纯卡密没有 VoiceHub 点歌券记录，不能显示站点券状态。
        headline.append("卡密（未同步 VoiceHub）")
        card = None
    else:
        card = card_statuses.get(code) if code else None
        site = _card_headline(card)
        if site:
            headline.append(site)

    lines = [" · ".join(headline)]

    details: List[str] = []
    delivered = to_beijing(coupon.get("delivered_at"))
    if delivered != EMPTY:
        details.append(f"发货时间 {delivered}")
    card_details = _card_detail_text(card)
    if card_details:
        details.append(card_details)
    error = _clean(coupon.get("voicehub_error"), 80)
    if error:
        details.append(f"站点错误 {error}")
    if details:
        lines.append("   " + " · ".join(details))
    return lines


def render_reply(
    payload: Any,
    card_statuses: Optional[Mapping[str, Any]] = None,
    *,
    show_full_code: bool = False,
    max_coupons: int = DEFAULT_COUPON_LIMIT,
) -> str:
    """渲染 VoiceHubPay 查询结果（订单 + 逐张券的站点状态）。

    Args:
        payload: VoiceHubPay 200 响应体（``ok=true`` 的统一结构）。
        card_statuses: 券码明文 → ``{"state": ok|not_found|disabled|error, "data": {...}}``。
        show_full_code: True 时券码用明文，否则掩码。
        max_coupons: 最多展示多少张券（超出部分提示剩余数量）。

    Returns:
        可直接发送的纯文本；任何字段缺失都只影响该行，不会抛异常。
    """
    body = payload if isinstance(payload, Mapping) else {}
    cards = card_statuses if isinstance(card_statuses, Mapping) else {}
    order = _as_mapping(body.get("order"))

    raw_coupons = body.get("coupons")
    coupons = [
        item
        for item in (raw_coupons if isinstance(raw_coupons, Sequence) and not isinstance(raw_coupons, (str, bytes)) else [])
        if isinstance(item, Mapping)
    ]

    lines: List[str] = ["【订单查询结果】"]

    found_by = _status(FOUND_BY, body.get("found_by"))
    if found_by != EMPTY:
        lines.append(f"命中方式：{found_by}")

    order_no = _clean(order.get("order_no"), 128)
    if order_no:
        lines.append(f"订单号：{order_no}")

    summary = [
        ("来源", _status(ORDER_SOURCE, order.get("source") or body.get("source"))),
        ("支付", _status(PAYMENT_STATUS, order.get("payment_status"))),
        ("订单", _status(ORDER_STATUS, order.get("order_status"))),
        ("发货", _status(FULFILLMENT_STATUS, order.get("fulfillment_status"))),
    ]
    summary_text = " · ".join(f"{label}：{value}" for label, value in summary if value != EMPTY)
    if summary_text:
        lines.append(summary_text)

    amount = format_cents(order.get("amount_cents"))
    paid = format_cents(order.get("amount_paid_cents"))
    money: List[str] = []
    if amount != EMPTY:
        money.append(f"金额：{amount}")
    if paid != EMPTY and paid != amount:
        money.append(f"实付：{paid}")
    if money:
        lines.append(" · ".join(money))

    payment_status = _clean(order.get("payment_status"), 20)
    for label, value in (
        ("下单", to_beijing(order.get("created_at"))),
        ("支付", to_beijing(order.get("paid_at"))),
        ("发货", to_beijing(order.get("fulfilled_at"))),
        ("过期", to_beijing(order.get("expires_at"))),
    ):
        # 已支付订单的 expires_at 只是下单时的保留期限，再显示会被误读成订单过期。
        if label == "过期" and payment_status == "paid":
            continue
        if value != EMPTY:
            lines.append(f"{label}：{value}")

    items = _items_text(order.get("items"))
    if items:
        lines.append(f"商品：{items}")

    afdian = _afdian_text(order.get("afdian"))
    if afdian:
        lines.append(f"爱发电：{afdian}")

    lines.append("")
    if not coupons:
        lines.append("点歌券：暂无记录（可能尚未发货）")
        return "\n".join(lines)

    limit = _positive_int(max_coupons, DEFAULT_COUPON_LIMIT)
    lines.append(f"点歌券（{len(coupons)} 张）：")
    for index, coupon in enumerate(coupons[:limit], start=1):
        lines.extend(_coupon_block(index, coupon, cards, show_full_code))
    if len(coupons) > limit:
        lines.append(f"…还有 {len(coupons) - limit} 张未显示（只展示前 {limit} 张）")
    return "\n".join(lines)


def render_card_only(card: Any, query: str, *, show_full_code: bool = False) -> str:
    """渲染「VoiceHubPay 无此订单、但 VoiceHub 有这张券」的降级结果。

    场景：站点直接发放的点歌券没有 VoiceHubPay 订单号；此时仍应告诉用户券
    是否存在、是否已核销，而不是简单回「查不到」。

    Args:
        card: ``{"state": "ok", "data": {...}}``（VoiceHub 券状态响应）。
        query: 用户原始查询串，用于在响应缺 code 时兜底展示。
        show_full_code: True 时券码用明文，否则掩码。

    Returns:
        可直接发送的纯文本。
    """
    data = _card_data(card)
    code = _clean(data.get("code"), 128) or _clean(query, 128)
    lines: List[str] = [
        "【点歌券状态】",
        f"订单：{TEXT_NO_PAY_ORDER}",
        f"券码：{display_code(code, show_full_code)}",
    ]
    for label, value in _card_pairs(data):
        lines.append(f"{label}：{value}")
    return "\n".join(lines)
