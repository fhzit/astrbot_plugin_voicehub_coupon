"""被动识别：判断一条群消息是否像订单号 / 点歌券码。

规则（契约定死，不要放宽）：单行文本、整体匹配 ``^[A-Za-z0-9][A-Za-z0-9_-]{5,63}$``、
至少 8 个字符、至少含一个数字。放宽会误伤普通聊天（例如「哈哈哈哈哈哈」里
夹一个编号），收紧则漏掉 ``<orderNo>-001`` 这类券码。
"""

from __future__ import annotations

import re
from typing import Any

CANDIDATE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,127}")
# 指令参数也走同一长度上限：站点券码/订单号最长 128 字符。
MIN_LENGTH = 8
MAX_LENGTH = 128
MIN_QUERY_LENGTH = 6


def looks_like_coupon_query(text: Any) -> bool:
    """判断整条消息是否就是一个候选订单号 / 券码。

    Args:
        text: 消息正文（通常是 ``event.message_str``）。

    Returns:
        True 表示可以静默查询；False 表示与本插件无关，应放行给后续插件。
    """
    if not isinstance(text, str):
        return False
    candidate = text.strip()
    if len(candidate) < MIN_LENGTH or len(candidate) > MAX_LENGTH:
        return False
    if not re.search(r"[0-9]", candidate):
        return False
    # 纯数字 8-15 位更像 QQ 号/手机号/学号，不是订单号（商城单号 24 位、
    # 爱发电单号 20 位以上）。放行会让群里随便一串数字都触发上游查询。
    if candidate.isdigit() and len(candidate) < 16:
        return False
    return CANDIDATE_RE.fullmatch(candidate) is not None


def normalize_query(text: Any) -> str:
    """把指令参数规整成可直接上送的查询串。

    只做形状收敛（去首尾空白、拒绝多词/路径/控制字符、限制长度），不校验
    具体是订单号还是券码 —— 那由 VoiceHubPay 判定并返回 INVALID_QUERY。

    Args:
        text: 指令参数或被动识别命中的文本。

    Returns:
        合法查询串；为空字符串表示参数不可用（调用方给用法提示）。
    """
    if not isinstance(text, str):
        return ""
    candidate = text.strip()
    if len(candidate) < MIN_QUERY_LENGTH or len(candidate) > MAX_LENGTH:
        return ""
    if any(ch.isspace() for ch in candidate):
        return ""
    # 指令自身不应被当作查询串；券码自定义前缀里的「/」仍允许。
    if candidate.startswith("/"):
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        return ""
    return candidate
