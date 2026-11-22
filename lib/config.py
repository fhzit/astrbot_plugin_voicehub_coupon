"""插件配置读取与群号白名单规整。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

DEFAULT_TIMEOUT = 10
DEFAULT_MAX_COUPONS = 10
# 单条回复最多展示这么多张券：再多聊天里读不动，也会放大站点压力。
MAX_COUPONS_LIMIT = 20
# 同一群两次查询之间的最小间隔（秒），用于被动识别削峰。
MIN_INTERVAL_SECONDS = 2.0
# 超时的上下限，防止配置被填成 0（立刻超时）或几千秒（挂住整条消息）。
MIN_TIMEOUT = 1
MAX_TIMEOUT = 60
# 群标识：OneBot 是纯数字群号，QQ 官方适配器是字母数字 openid；
# 统一允许 3-64 位 [A-Za-z0-9_-]，URL/UMO（含冒号）仍会被丢弃。
_GROUP_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}")
_GROUP_SPLIT_RE = re.compile(r"[,\s、，；;]+")

CONFIG_KEYS = (
    "voicehubpay_base_url",
    "voicehubpay_bot_token",
    "voicehub_base_url",
    "voicehub_api_key",
    "group_ids",
    "auto_query",
    "allow_private",
    "show_full_code",
    "request_timeout_seconds",
    "max_coupons",
)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> List[str]:
    """把 WebUI 的 text 字段解析为去空、去重列表。"""
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    elif isinstance(value, str):
        items = _GROUP_SPLIT_RE.split(value)
    else:
        return []

    result: List[str] = []
    for item in items:
        stripped = item.strip().strip("\"'")
        if stripped and stripped not in result:
            result.append(stripped)
    return result


def normalize_group_ids(value: Any) -> List[str]:
    """解析群号白名单：逗号/换行/空白分隔，只保留形状合法的群标识。

    管理员在 WebUI 里常把会话串、带前缀的群号或说明文字一起粘进来；这些
    取值如果进入白名单会让「本群未开启」变成难以排查的谜题，因此这里直接
    丢弃 URL/会话串等非法项，并由 :func:`dropped_group_values` 在启动日志里点名。

    Args:
        value: 配置里的原始取值（text 或列表）。

    Returns:
        去重后的群标识列表，保持配置顺序。
    """
    return [item for item in _as_list(value) if _GROUP_ID_RE.fullmatch(item)]


def dropped_group_values(value: Any) -> List[str]:
    """返回白名单里因形状不合法而被忽略的取值，供启动日志提示。"""
    return [item for item in _as_list(value) if not _GROUP_ID_RE.fullmatch(item)]


@dataclass(frozen=True)
class CouponConfig:
    """插件运行配置。

    字段名与 ``_conf_schema.json`` 一一对应；测试会把两边的键集合钉在一起，
    避免文档、配置面板与代码三处漂移。
    """

    voicehubpay_base_url: str = ""
    voicehubpay_bot_token: str = ""
    voicehub_base_url: str = ""
    voicehub_api_key: str = ""
    group_ids: List[str] = field(default_factory=list)
    auto_query: bool = True
    allow_private: bool = False
    show_full_code: bool = False
    request_timeout_seconds: int = DEFAULT_TIMEOUT
    max_coupons: int = DEFAULT_MAX_COUPONS

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "CouponConfig":
        """从 AstrBot 注入的插件配置构造实例。

        Args:
            raw: 插件配置对象；``None``、非映射或字段类型异常时逐项回退默认值。

        Returns:
            归一化后的配置实例（URL 去掉尾部斜杠，群号只留合法群标识）。
        """
        data: Dict[str, Any] = {}
        if isinstance(raw, Mapping):
            data = dict(raw)
        else:
            getter = getattr(raw, "get", None)
            if callable(getter):
                for key in CONFIG_KEYS:
                    try:
                        data[key] = getter(key)
                    except Exception:  # noqa: BLE001 - 配置后端异常时按缺失处理
                        continue

        return cls(
            voicehubpay_base_url=str(data.get("voicehubpay_base_url") or "").strip().rstrip("/"),
            voicehubpay_bot_token=str(data.get("voicehubpay_bot_token") or "").strip(),
            voicehub_base_url=str(data.get("voicehub_base_url") or "").strip().rstrip("/"),
            voicehub_api_key=str(data.get("voicehub_api_key") or "").strip(),
            group_ids=normalize_group_ids(data.get("group_ids")),
            auto_query=_as_bool(data.get("auto_query"), True),
            allow_private=_as_bool(data.get("allow_private"), False),
            show_full_code=_as_bool(data.get("show_full_code"), False),
            request_timeout_seconds=min(
                MAX_TIMEOUT,
                max(MIN_TIMEOUT, _as_int(data.get("request_timeout_seconds"), DEFAULT_TIMEOUT)),
            ),
            max_coupons=min(
                MAX_COUPONS_LIMIT,
                max(1, _as_int(data.get("max_coupons"), DEFAULT_MAX_COUPONS)),
            ),
        )

    @property
    def pay_ready(self) -> bool:
        """VoiceHubPay 的地址与机器人令牌是否都已配置。"""
        return bool(self.voicehubpay_base_url and self.voicehubpay_bot_token)

    @property
    def voicehub_ready(self) -> bool:
        """VoiceHub 的地址与 API Key 是否都已配置（未配置属可接受的降级）。"""
        return bool(self.voicehub_base_url and self.voicehub_api_key)

    def missing_pay_settings(self) -> List[str]:
        """返回缺失的 VoiceHubPay 配置项名称，供启动日志与配置提示使用。"""
        missing = []
        if not self.voicehubpay_base_url:
            missing.append("voicehubpay_base_url")
        if not self.voicehubpay_bot_token:
            missing.append("voicehubpay_bot_token")
        return missing

    def is_group_allowed(self, group_id: Any) -> bool:
        """判断群号是否在白名单内（空白名单表示不授权任何群）。"""
        candidate = str(group_id if group_id is not None else "").strip()
        return bool(candidate) and candidate in self.group_ids
