"""统一的 aiohttp 会话工厂与网络错误文案。

两个上游（VoiceHubPay、VoiceHub）都可能在反向代理后面并挂调试头；aiohttp 默认
把响应行/单个响应头的长度上限设为 8190 字节，``Server-Timing`` 之类的长头会
让客户端直接解析失败。插件里所有请求都走 :func:`make_session`，统一放大上限，
避免散落的 ``ClientSession`` 逐处遗漏。

聊天回复只用 :func:`describe_client_error` 给的可读文案；原始异常交给
:func:`log_network_error` 写日志，绝不把站点地址、令牌或响应片段回显给用户。
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp

# 64 KB 足够容纳超长调试头，同时不给恶意响应留下无上限的解析成本。
MAX_LINE_SIZE = 65536
MAX_FIELD_SIZE = 65536

TEXT_HEADER_TOO_LARGE = (
    "站点响应头过长，客户端无法解析（调试头超出 aiohttp 上限），"
    "请联系站点管理员关闭 nitro.timing 后重试"
)
TEXT_TIMEOUT = "查询超时，请稍后重试"
TEXT_CONNECTION = "无法连接查询服务，请检查网络或站点地址"
TEXT_REQUEST_FAILED = "请求查询服务失败"

_TIMEOUT_TYPES = (asyncio.TimeoutError, TimeoutError, aiohttp.ServerTimeoutError)


def make_session(
    timeout: Optional[aiohttp.ClientTimeout] = None, **kwargs: Any
) -> aiohttp.ClientSession:
    """创建带放大 header 上限的 aiohttp 会话。

    Args:
        timeout: 请求超时；默认沿用 aiohttp 自带的 5 分钟 total。
        **kwargs: 透传给 ``aiohttp.ClientSession``，显式传入的
            ``max_line_size`` / ``max_field_size`` 优先。

    Returns:
        新的 ``aiohttp.ClientSession``（调用方负责 ``async with`` 关闭）。
    """
    kwargs.setdefault("max_line_size", MAX_LINE_SIZE)
    kwargs.setdefault("max_field_size", MAX_FIELD_SIZE)
    return aiohttp.ClientSession(timeout=timeout, **kwargs)


def is_timeout_error(exc: BaseException) -> bool:
    """判断异常是否为请求超时（各版本 aiohttp 的超时类型不完全一致）。"""
    return isinstance(exc, _TIMEOUT_TYPES)


def is_header_limit_error(exc: BaseException) -> bool:
    """判断异常是否为「响应头超出客户端解析上限」（按文案识别，兼容各版本）。"""
    text = str(exc)
    return "Got more than" in text and "bytes when reading" in text


def describe_client_error(exc: BaseException) -> str:
    """把网络异常收敛成可直接回复用户的可读文案。

    Args:
        exc: 捕获到的异常。

    Returns:
        非空的中文提示；不含站点地址、令牌或原始响应片段。
    """
    if is_header_limit_error(exc):
        return TEXT_HEADER_TOO_LARGE
    if is_timeout_error(exc):
        return TEXT_TIMEOUT
    if isinstance(exc, aiohttp.ClientConnectionError):
        return TEXT_CONNECTION
    return TEXT_REQUEST_FAILED


def log_network_error(logger: Any, scope: str, exc: BaseException, context: str = "") -> None:
    """把完整异常写日志，供管理员排查。

    header 超限时原始报文里带长响应头片段，只保留前 400 字符并注明原因，
    避免日志刷屏。
    """
    where = f"{scope} {context}".strip()
    if is_header_limit_error(exc):
        logger.error("[VoiceHub券] %s 响应头超出 aiohttp 上限：%s", where, str(exc)[:400])
        return
    logger.warning("[VoiceHub券] %s 网络请求失败：%r", where, exc)


def redact_url(url: str) -> str:
    """只保留协议与主机名，日志里避免带出令牌化的查询串。"""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else url
