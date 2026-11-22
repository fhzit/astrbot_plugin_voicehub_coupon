# 更新日志

本文件记录 astrbot_plugin_voicehub_coupon 的用户可感知变更。格式参照 Keep a Changelog，
版本号递增遵循语义化。

## [v0.1.0] - 2026-11-22

### 新增

- **群内查询**：`/查券 <订单号或点歌券码>`、`/查单 <订单号>` 两个指令，查询 VoiceHubPay 订单与点歌券状态。
- **被动识别**：授权群内单行发送订单号或券码（8-128 位、含数字，纯数字至少 16 位）自动查询；命中且有结果时回复并接管消息，查不到静默放行。
- **订单全景**：命中方式、订单号、来源、金额与实付、支付/订单/发货状态、下单/支付/发货/过期时间、商品明细、爱发电交易信息。
- **逐券状态**：每张券的发货结果与 VoiceHub 站点状态，已核销时附核销时间、来源与歌曲。
- **站点直发券兜底**：VoiceHubPay 返回 404 时仍按券码查询 VoiceHub，回复「点歌券状态」并说明未关联支付订单。
- **削峰保护**：同群同文本进行中复用结果，每群 2 秒最小查询间隔。
- **安全默认**：券码默认掩码，仅 `show_full_code` 开启时显示明文；回复不含令牌与站点内部字段。
- **可选降级**：未配置 VoiceHub API Key 时订单与发货状态照常回复，券状态显示固定提示。

### 配置

- 新增 `voicehubpay_base_url`、`voicehubpay_bot_token`、`voicehub_base_url`、`voicehub_api_key`、`group_ids`、`auto_query`、`allow_private`、`show_full_code`、`request_timeout_seconds`、`max_coupons` 十项配置。
