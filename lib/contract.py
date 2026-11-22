"""VoiceHub / VoiceHubPay 接口契约常量。

取值来自《VoiceHub 点歌券查询跨仓库契约（2026-11-22）》第 1、2 节，插件侧只读：
路径、请求头与错误码必须与两个服务端保持一致，任何一侧改动都要同步这里。
"""

from __future__ import annotations

# VoiceHubPay 机器人接口：按订单号 / 爱发电单号 / 券码查询
COUPON_QUERY_PATH = "/api/bot/coupon-query"
BOT_TOKEN_HEADER = "X-Bot-Token"
QUERY_FIELD = "query"

# VoiceHub 开放接口：按点歌券码精确查询状态（需要 card-codes:read）
CARD_CODE_STATUS_PATH = "/api/open/card-codes/status"
CARD_CODE_QUERY_FIELD = "code"
API_KEY_HEADER = "x-api-key"

# VoiceHubPay 响应体里的错误码
ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_INVALID_QUERY = "INVALID_QUERY"
ERROR_UNAUTHORIZED = "UNAUTHORIZED"
ERROR_BOT_QUERY_DISABLED = "BOT_QUERY_DISABLED"

# 查询结果状态（客户端与服务层共用）
STATE_OK = "ok"
STATE_NOT_FOUND = "not_found"
STATE_INVALID = "invalid"
STATE_ERROR = "error"
STATE_DISABLED = "disabled"
STATE_THROTTLED = "throttled"
