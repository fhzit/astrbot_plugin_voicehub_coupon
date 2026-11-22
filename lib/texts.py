"""插件对外的用户可见文案。

集中在这里的目的：client / service / render 共用同一套措辞，测试可以直接
按常量断言，README 也能逐条对照，避免同一个提示在不同分支里说法不一致。
"""

from __future__ import annotations

# 指令用法
TEXT_USAGE = "用法：/查券 <订单号或点歌券码>，或 /查单 <订单号>。"
TEXT_INVALID_QUERY = "查询内容格式不正确，请只发送一个订单号或点歌券码。"

# 授权与配置
TEXT_GROUP_DENIED = "本群未开启点歌券查询。"
TEXT_PRIVATE_DENIED = "请在已授权的群聊中使用。"
TEXT_PAY_NOT_CONFIGURED = (
    "插件未配置 VoiceHubPay，暂时无法查询。"
    "请在 AstrBot 插件配置中填写 voicehubpay_base_url 与 voicehubpay_bot_token。"
)

# 查询结果
TEXT_NOT_FOUND = "未查询到对应的订单或点歌券，请核对订单号/券码后重试。"
TEXT_NOT_FOUND_NO_VOICEHUB = (
    "未查询到对应的 VoiceHubPay 订单；"
    "插件未配置 VoiceHub API Key，无法再按券码查询站点券状态。"
)
TEXT_THROTTLED = "查询过于频繁，请 2 秒后再试。"
TEXT_QUERY_FAILED = "查询失败，请稍后重试。"

# VoiceHub 券状态（也用于降级展示）
TEXT_CARD_NOT_FOUND = "VoiceHub 未收录（可能尚未发货）"
TEXT_CARD_DISABLED = "未配置 VoiceHub API Key，无法查询站点券状态"
TEXT_CARD_ERROR = "站点券状态查询失败，请稍后重试"

# 只有 VoiceHub 收录、VoiceHubPay 没有对应订单时的订单说明
TEXT_NO_PAY_ORDER = "未关联 VoiceHubPay 订单（可能由站点直接发放）"
