"""VoiceHub 点歌券查询插件。

白名单群内的用户可以直接发送 VoiceHubPay 订单号 / 爱发电订单号 / 点歌券码，
插件静默查询后回复订单与券状态；也可以显式使用 `/查券`、`/查单` 指令。
所有查询都是只读的，插件不落库、不接触账号凭据，回复里默认掩码券码。
"""

from __future__ import annotations

from typing import Any, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import CustomFilter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .lib.config import CouponConfig, dropped_group_values
from .lib.contract import STATE_OK
from .lib.detect import looks_like_coupon_query
from .lib.service import CouponQueryService
from .lib.texts import (
    TEXT_CARD_DISABLED,
    TEXT_GROUP_DENIED,
    TEXT_PRIVATE_DENIED,
    TEXT_QUERY_FAILED,
)


def _group_id(event: AstrMessageEvent) -> str:
    """取当前会话的群号；私聊返回空字符串。"""
    getter = getattr(event, "get_group_id", None)
    value = getter() if callable(getter) else ""
    return str(value).strip() if value else ""


class _CouponCandidateFilter(CustomFilter):
    """群聊里发来「像订单号 / 券码」的单行文本时才激活 handler。

    白名单开关属于运行期配置，过滤器只在导入期构造一次，读不到最新值；
    这里只做零成本的形状判断，群号白名单与 auto_query 由 handler 每次现读。
    """

    def filter(self, event: AstrMessageEvent, cfg: Any = None) -> bool:  # noqa: ANN401 - 框架签名
        del cfg  # 未使用；保留参数以匹配 CustomFilter.filter 的约定
        if not _group_id(event):
            return False
        text = str(getattr(event, "message_str", "") or "").strip()
        if not text or text.startswith("/"):
            return False
        return looks_like_coupon_query(text)


@register(
    "astrbot_plugin_voicehub_coupon",
    "fhzit",
    "在授权群内按订单号或点歌券码查询 VoiceHubPay 订单与券状态",
    "v0.1.0",
)
class VoiceHubCouponPlugin(Star):
    """VoiceHub 点歌券查询插件。"""

    def __init__(self, context: Context, config: Optional[Any] = None):
        super().__init__(context)
        self.raw_config = config
        self.plugin_config = CouponConfig.from_mapping(config)
        self.service = CouponQueryService(self.plugin_config)

    async def initialize(self):
        """记录配置状态：缺项要能一眼看出来，但不阻止插件加载。"""
        missing = self.plugin_config.missing_pay_settings()
        if missing:
            logger.warning(
                "[VoiceHub券] 未配置 %s，/查券 与 /查单 只会回复配置提示。",
                "、".join(missing),
            )
        if not self.plugin_config.voicehub_ready:
            logger.info(
                "[VoiceHub券] 未配置 voicehub_base_url 或 voicehub_api_key："
                "订单仍可查询，站点券状态显示为「%s」。",
                TEXT_CARD_DISABLED,
            )
        if not self.plugin_config.group_ids:
            logger.warning(
                "[VoiceHub券] 群号白名单为空：群内指令与被动识别都不会生效；"
                "需要私聊查询时请开启 allow_private。"
            )
        else:
            logger.info(
                "[VoiceHub券] 已授权 %d 个群，被动识别%s。",
                len(self.plugin_config.group_ids),
                "已开启" if self.plugin_config.auto_query else "已关闭",
            )

        getter = getattr(self.raw_config, "get", None)
        dropped: list[str] = []
        if callable(getter):
            try:
                dropped = dropped_group_values(getter("group_ids"))
            except Exception:  # noqa: BLE001 - 配置后端异常不应阻止加载
                dropped = []
        if dropped:
            logger.warning(
                "[VoiceHub券] 以下取值不是合法群号/群 openid，已忽略：%s", dropped
            )

    # ------------------------------------------------------------------
    # 指令
    # ------------------------------------------------------------------

    async def _handle_command(self, event: AstrMessageEvent, raw_query: Any) -> str:
        """指令共用逻辑：先过群/私聊闸门，再查一次。"""
        group_id = _group_id(event)
        if group_id:
            if not self.plugin_config.is_group_allowed(group_id):
                return TEXT_GROUP_DENIED
        elif not self.plugin_config.allow_private:
            return TEXT_PRIVATE_DENIED

        outcome = await self.service.query(str(raw_query or ""), group_id)
        return outcome.text or TEXT_QUERY_FAILED

    @filter.command("查券", alias={"coupon", "cq"})
    async def coupon_query(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """查询订单与点歌券状态：/查券 <订单号或点歌券码>"""
        yield event.plain_result(await self._handle_command(event, query))

    @filter.command("查单", alias={"order", "dd"})
    async def order_query(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """按订单号查询：/查单 <商城订单号 / 爱发电订单号>"""
        yield event.plain_result(await self._handle_command(event, query))

    # ------------------------------------------------------------------
    # 被动识别
    # ------------------------------------------------------------------

    @filter.custom_filter(_CouponCandidateFilter, priority=100)
    async def on_coupon_candidate(self, event: AstrMessageEvent):
        """群内直接发订单号/券码即静默查询。

        只有真正查到结果才回复并终结事件传播；404、未配置、网络错误、
        限流一律不回复，消息照常交给其他插件与 AI 处理。
        """
        group_id = _group_id(event)
        if not group_id or not self.plugin_config.auto_query:
            return
        if not self.plugin_config.is_group_allowed(group_id):
            return

        text = str(getattr(event, "message_str", "") or "").strip()
        if not looks_like_coupon_query(text):
            return

        outcome = await self.service.query(text, group_id)
        if outcome.state != STATE_OK or not outcome.text:
            return

        yield event.plain_result(outcome.text)
        event.stop_event()
