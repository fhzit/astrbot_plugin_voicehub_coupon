<div align="center">

# 🎟️ VoiceHub 点歌券查询

*在 QQ 群里自助查询订单与点歌券状态*

[![AstrBot](https://img.shields.io/badge/framework-AstrBot-ff6b6b?style=flat-square)](https://github.com/AstrBotDevs/AstrBot)
[![VoiceHub](https://img.shields.io/badge/service-VoiceHub-7c3aed?style=flat-square)](https://github.com/laoshuikaixue/VoiceHub)
[![VoiceHubPay](https://img.shields.io/badge/service-VoiceHubPay-0ea5e9?style=flat-square)](https://github.com/fhzit/VoiceHubPay)

</div>

## ✨ 简介

这是 [VoiceHub](https://github.com/laoshuikaixue/VoiceHub) 点歌券体系的 AstrBot 查询插件。用户在授权群里直接发送 VoiceHubPay 订单号、爱发电订单号或点歌券码，机器人就会回复订单金额、支付与发货状态，以及每张券在站点是否已派发、已核销、核销了哪首歌。

插件只做只读查询：不保存订单，不记录券码，不接触账号身份信息，回复里的券码默认掩码。

- 插件仓库：<https://github.com/fhzit/astrbot_plugin_voicehub_coupon>
- 适配器：`aiocqhttp`（OneBot v11）；`qq_official` / `qq_official_webhook` 亦可使用，实际表现取决于平台的群消息能力。
- Python 依赖见 [`requirements.txt`](./requirements.txt)，只有 `aiohttp`。

## ✨ 功能特性

- 🔎 **两种查询方式**：`/查券`、`/查单` 指令，或按配置在白名单群里直接发送订单号/券码自动识别。
- 🧾 **订单全景**：来源（商城/爱发电）、金额与实付、支付状态、订单状态、发货状态、各时间点、商品明细。
- 🎟️ **逐券状态**：每张券的发货结果 + VoiceHub 站点状态（未使用/已派发/已核销/已回收/派发失败），已核销时附核销时间与歌曲。
- 🛡️ **默认安全**：券码默认掩码（保留首 4 位与末 2 位），仅管理员显式开启 `show_full_code` 才显示明文；群号白名单之外不响应任何消息。
- 🧯 **可选降级**：未配置 VoiceHub API Key 时，订单与发货状态照常回复，券状态位置显示固定提示，不报错。
- 🤫 **静默兜底**：被动识别只在真正查到结果时回复并接管消息；查不到、网络错误、限流一律放行给其他插件与 AI。
- ⏱️ **削峰保护**：同群同文本进行中不重复请求，每群两次查询至少间隔 2 秒。

## 工作方式

```
群成员发送订单号 / 券码 / 指令
        │
        ├─ 群号白名单 + auto_query 判定（被动识别还要求单行、8-128 位、含数字，且纯数字至少 16 位）
        │
        ├─ POST VoiceHubPay /api/bot/coupon-query（X-Bot-Token）
        │        │
        │        ├─ 200：拿到订单 + 券列表（含券码明文与掩码）
        │        │        └─ GET VoiceHub /api/open/card-codes/status?code=…（x-api-key）
        │        │
        │        └─ 404：拿原文再查一次 VoiceHub 券状态，覆盖站点直接发券
        │
        └─ 纯文本回复（金额元、时间北京时间、券码掩码）
```

两个上游都是可降级的：VoiceHubPay 未配置时指令只回配置提示；VoiceHub 未配置时订单照常展示，券状态显示「未配置 VoiceHub API Key，无法查询站点券状态」。

## 服务端准备

插件依赖两个只读接口；服务端未部署对应版本时无法工作。

1. **VoiceHubPay**（`fhzit/voicehubpay`）：部署含 `/api/bot/coupon-query` 的版本，并给 `voicehubpay-ts` 的 server 容器设置环境变量 `BOT_QUERY_TOKEN`（随机长字符串，等同于查询凭证）。未设置时接口返回 `503 BOT_QUERY_DISABLED`。
2. **VoiceHub**（`laoshuikaixue/VoiceHub`）：部署含 `/api/open/card-codes/status` 的版本；在后台「API 密钥」创建一个勾选 `card-codes:read` 的密钥，填到插件 `voicehub_api_key`。
3. 把 VoiceHubPay 的 `BOT_QUERY_TOKEN` 填到插件 `voicehubpay_bot_token`。

VoiceHub 未配置时插件仍能展示订单与 VoiceHubPay 发货状态，只是没有站点券的核销/派发状态。

## 快速开始

### 1. 安装插件

将本目录放到 AstrBot 的插件目录：

```sh
cd AstrBot/data/plugins
git clone https://github.com/fhzit/astrbot_plugin_voicehub_coupon.git
```

也可以用 AstrBot 管理面板的 `插件市场` / `安装插件`（支持仓库地址或上传 zip），然后在面板中重载插件。

依赖会在插件加载时按 `requirements.txt` 安装；也可以手动装：

```sh
AstrBot/.venv/bin/pip install -r astrbot_plugin_voicehub_coupon/requirements.txt
```

### 2. 配置插件

在 AstrBot 管理面板 → `插件` → `VoiceHub 点歌券查询` 中填写：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `voicehubpay_base_url` | string | 空 | VoiceHubPay 站点地址，例如 `https://pay.example.com`，不带末尾斜杠。 |
| `voicehubpay_bot_token` | string | 空 | VoiceHubPay 服务端 `BOT_QUERY_TOKEN` 环境变量的值；未设置时接口返回 `BOT_QUERY_DISABLED`。 |
| `voicehub_base_url` | string | 空 | VoiceHub 站点地址，可选；留空时按降级方式展示券状态。 |
| `voicehub_api_key` | string | 空 | VoiceHub API Key，可选，必须勾选 `card-codes:read` 权限。 |
| `group_ids` | text | 空 | 授权 QQ 群号（或 QQ 官方适配器的群 openid），逗号或换行分隔；留空表示不授权任何群。 |
| `auto_query` | bool | `true` | 群内直接发订单号/券码时自动查询。 |
| `allow_private` | bool | `false` | 允许私聊使用指令查询；默认只允许授权群。 |
| `show_full_code` | bool | `false` | 回复中显示完整券码；默认掩码。 |
| `request_timeout_seconds` | int | `10` | 单次请求超时，允许 1-60 秒。 |
| `max_coupons` | int | `10` | 单次回复最多展示的券数，允许 1-20 张，超出部分只提示数量。 |

**最小可用配置**：`voicehubpay_base_url`、`voicehubpay_bot_token`、`group_ids` 三项。

## 指令与自动识别

| 用法 | 适用会话 | 说明 |
| --- | --- | --- |
| `/查券 <订单号或点歌券码>` | 授权群 / 私聊（需 `allow_private`） | 依次按商城订单号、爱发电订单号、券码查询。 |
| `/查单 <订单号>` | 授权群 / 私聊（需 `allow_private`） | 与 `/查券` 完全相同，只是语义更明确。 |
| 直接发送订单号或券码 | 授权群 | `auto_query` 开启时自动识别，命中后静默查询。 |

被动识别规则：消息必须是单行、整体匹配 `^[A-Za-z0-9][A-Za-z0-9_-]{5,127}$`、至少 8 个字符且至少含一个数字，并且不以 `/` 开头；纯数字且不足 16 位的消息按 QQ 号/手机号处理，不触发查询。普通聊天、多行文本、纯字母词不会触发。

英文别名与指令等价：`/coupon`、`/cq` 等同于 `/查券`，`/order`、`/dd` 等同于 `/查单`。

未授权的群使用指令会回复「本群未开启点歌券查询」，私聊默认回复「请在已授权的群聊中使用」。

## 回复示例

```text
【订单查询结果】
命中方式：商城订单号
订单号：20261122153000001234
来源：商城 · 支付：已支付 · 订单：有效 · 发货：已发货
金额：9.90 元
下单：2026-11-22 15:30:00
支付：2026-11-22 15:31:00
发货：2026-11-22 15:32:00
商品：点歌券 ×1（9.90 元，发货：voicehub）

点歌券（1 张）：
1. 2026****01 · 发货成功 · 站点：已核销
   发货时间 2026-11-22 15:32:00 · 派发时间 2026/11/22 15:31:00 · 核销时间 2026/11/22 18:00:00 · 来源 排期自动核销 · 歌曲 《告白气球》- 周杰伦
```

VoiceHubPay 查不到订单、但 VoiceHub 有这张券时（例如站点直接发券）：

```text
【点歌券状态】
订单：未关联 VoiceHubPay 订单（可能由站点直接发放）
券码：2026****01
状态：已核销
核销时间：2026/11/22 18:00:00
来源：排期自动核销
歌曲：《告白气球》- 周杰伦
```

两种情况都查不到时：被动消息不回复，指令回复「未查询到对应的订单或点歌券」。

## 降级与错误处理

| 场景 | 表现 |
| --- | --- |
| 未配置 `voicehubpay_base_url` / `voicehubpay_bot_token` | 指令回复配置提示；被动消息静默。 |
| 未配置 `voicehub_base_url` / `voicehub_api_key` | 订单与发货状态正常回复，券状态显示「未配置 VoiceHub API Key，无法查询站点券状态」。 |
| VoiceHub 未收录该券 | 券状态显示「VoiceHub 未收录（可能尚未发货）」。 |
| VoiceHubPay 返回 404 | 用原文再查一次 VoiceHub 券状态；查到则回复点歌券状态，两边都没有则按未找到处理。 |
| 令牌错误（401） | 指令回复「查询失败：VoiceHubPay 拒绝了机器人令牌…」，提示检查配置。 |
| 机器人查询未开启（503） | 指令回复「查询失败：VoiceHubPay 未开启机器人查询接口…」。 |
| 超时 / 网络失败 | 指令回复可读提示；被动消息静默，不打断聊天。 |
| 查询过于频繁 | 同群 2 秒内再次查询回复「查询过于频繁」，进行中的相同查询直接复用结果。 |

回复中不会出现任何令牌、完整请求 URL 或站点内部字段。

## 权限要求

- **VoiceHubPay**：把部署时设置的 `BOT_QUERY_TOKEN` 填到 `voicehubpay_bot_token`。服务端未设置该变量时返回 `BOT_QUERY_DISABLED`（HTTP 503）。
- **VoiceHub**：创建 API Key 时勾选 `card-codes:read`（点歌券只读）。缺少该权限时接口返回 401/403，插件显示「VoiceHub API Key 无效或缺少 card-codes:read 权限」。
- **AstrBot**：机器人需要在目标群里，且群号已写入 `group_ids`。插件不会主动加群，也不响应未授权群的消息。
- 两个服务端都需要插件所在网络可以出站访问。

## 安全说明

- **只读**：插件不创建、不修改订单与券，不写数据库。
- **令牌不出网**：`X-Bot-Token` 与 `x-api-key` 只放在请求头里，不写日志、不进回复；日志只记请求路径。
- **券码默认掩码**：回复只保留首 4 位与末 2 位，例如 `2026****01`。`show_full_code` 仅建议在私聊或内部群开启。
- **不展示身份信息**：只渲染订单与券状态字段，忽略上游可能附带的持有人姓名、学号等字段。
- **白名单是唯一入口**：群号不在 `group_ids` 内时，指令与被动识别都不工作；私聊默认关闭。
- **拒绝重定向**：所有请求 `allow_redirects=False`，避免鉴权头被转发到其他主机。
- **事件接管有边界**：被动识别只在真正查到结果时回复并 `stop_event()`，其他情况一律放行。

## 故障排查

| 现象 | 排查方向 |
| --- | --- |
| 群里发订单号没反应 | 确认该群号已写入 `group_ids`、`auto_query` 已开启、文本是单行且含数字；查不到时本插件按设计不回复。 |
| 指令回复「本群未开启点歌券查询」 | 群号不匹配。请填 QQ 群号或群 openid，不要填 UMO 会话串或适配器名。 |
| 指令回复配置提示 | 检查 `voicehubpay_base_url` 是否带 `http(s)://`、`voicehubpay_bot_token` 是否为空。 |
| 回复「VoiceHubPay 拒绝了机器人令牌」 | 令牌与 VoiceHubPay 后台不一致，或令牌已失效。 |
| 回复「VoiceHubPay 未开启机器人查询接口」 | VoiceHubPay 部署未设置 `BOT_QUERY_TOKEN`，补环境变量后重启服务。 |
| 券状态一直是「未配置 VoiceHub API Key」 | 补 `voicehub_base_url` 与 `voicehub_api_key`，并确认 Key 有 `card-codes:read`。 |
| 券状态「VoiceHub 未收录（可能尚未发货）」 | VoiceHubPay 已收款但站点尚未发货，稍后再查。 |
| 回复「查询过于频繁」 | 同一群 2 秒内重复触发，稍等即可。 |
| 日志出现「响应头超出 aiohttp 上限」 | 站点开启了 `nitro.timing` 等调试头，请站点管理员关闭。 |

## 开发与测试

```sh
python3 -m venv .venv
.venv/bin/pip install pytest aiohttp
.venv/bin/python -m pytest tests/ -q
```

测试用假 event 与假 aiohttp 会话驱动真实代码，不启动 AstrBot、不访问网络；覆盖配置解析、被动识别、渲染（金额/时间/状态/掩码/缺失字段）、两个客户端（URL、请求头、请求体、错误映射）、服务层去重与限流，以及指令和被动 handler 的全部分支。

## 许可

MIT
