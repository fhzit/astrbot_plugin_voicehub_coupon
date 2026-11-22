"""README / 配置 / 元数据的一致性检查。

文档是操作者逐字照抄的东西：这里把 `_conf_schema.json`、`CouponConfig`、README、
metadata 与 CHANGELOG 绑在一起，任何一处漂移都会让测试失败。
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path

from astrbot_plugin_voicehubpay.lib.config import CONFIG_KEYS, CouponConfig
from astrbot_plugin_voicehubpay.lib.render import mask_code
from astrbot_plugin_voicehubpay.lib.texts import (
    TEXT_CARD_DISABLED,
    TEXT_CARD_NOT_FOUND,
    TEXT_GROUP_DENIED,
    TEXT_NO_PAY_ORDER,
    TEXT_PRIVATE_DENIED,
)

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SCHEMA = ROOT / "_conf_schema.json"
METADATA = ROOT / "metadata.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
REQUIREMENTS = ROOT / "requirements.txt"

EXPECTED_KEYS = [
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
]


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def metadata() -> dict:
    """解析扁平 key: value 的 metadata.yaml（不引入 PyYAML 依赖）。"""
    result = {}
    for line in METADATA.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("-"):
            continue
        key, sep, value = line.partition(":")
        if sep and key and not key.startswith(" "):
            result[key.strip()] = value.strip()
    return result


def test_schema_keys_match_config_dataclass():
    assert list(schema()) == EXPECTED_KEYS
    assert [item.name for item in fields(CouponConfig)] == EXPECTED_KEYS
    assert list(CONFIG_KEYS) == EXPECTED_KEYS


def test_schema_types_and_defaults_follow_the_contract():
    config = schema()

    assert config["auto_query"]["type"] == "bool"
    assert config["auto_query"]["default"] is True
    assert config["allow_private"]["type"] == "bool"
    assert config["allow_private"]["default"] is False
    assert config["show_full_code"]["type"] == "bool"
    assert config["show_full_code"]["default"] is False
    assert config["group_ids"]["type"] == "text"
    assert config["request_timeout_seconds"]["type"] == "int"
    assert config["request_timeout_seconds"]["default"] == 10
    assert config["max_coupons"]["type"] == "int"
    assert config["max_coupons"]["default"] == 10
    for key in ("voicehubpay_base_url", "voicehubpay_bot_token", "voicehub_base_url", "voicehub_api_key"):
        assert config[key]["type"] == "string"
        assert config[key]["default"] == ""

    for key, item in config.items():
        assert item.get("description"), f"{key} 缺少 description"
        assert item.get("hint"), f"{key} 缺少 hint"


def test_schema_hints_state_the_permission_requirements():
    text = SCHEMA.read_text(encoding="utf-8")
    assert "card-codes:read" in text
    assert "BOT_QUERY_TOKEN" in text
    assert "BOT_QUERY_DISABLED" in text


def test_readme_documents_every_config_option():
    text = readme_text()
    undocumented = [key for key in EXPECTED_KEYS if f"`{key}`" not in text]
    assert not undocumented, f"README 未说明这些配置项: {undocumented}"


def test_readme_documents_both_endpoints_and_headers():
    text = readme_text()
    assert "/api/bot/coupon-query" in text
    assert "/api/open/card-codes/status" in text
    assert "X-Bot-Token" in text
    assert "x-api-key" in text
    assert "card-codes:read" in text


def test_readme_documents_commands_and_passive_rules():
    text = readme_text()
    assert "/查券" in text
    assert "/查单" in text
    for alias in ("/coupon", "/cq", "/order", "/dd"):
        assert alias in text, f"README 未说明指令别名: {alias}"
    assert "auto_query" in text
    assert "8-64" in text or "8 个字符" in text
    assert "2 秒" in text


def test_readme_repeats_the_runtime_prompts():
    text = readme_text()
    for prompt in (TEXT_GROUP_DENIED, TEXT_PRIVATE_DENIED, TEXT_CARD_DISABLED, TEXT_CARD_NOT_FOUND, TEXT_NO_PAY_ORDER):
        # 文档引用文案时通常省略句末句号，按去掉句号的形态比对
        assert prompt.rstrip("。") in text, f"README 未给出实际文案: {prompt}"
    assert "未查询到对应的订单或点歌券" in text


def test_readme_example_uses_the_same_masking():
    text = readme_text()
    code = "20261122153000001234-001"
    masked = mask_code(code)
    assert masked == "2026****01"
    assert masked in text
    assert code not in text, "README 示例不应出现明文券码"


def test_readme_has_the_required_sections():
    text = readme_text()
    for heading in ("## ✨ 简介", "## ✨ 功能特性", "## 快速开始", "## 指令与自动识别", "## 故障排查", "## 安全说明"):
        assert heading in text, f"README 缺少章节: {heading}"


def test_metadata_contract():
    data = metadata()
    assert data["name"] == "astrbot_plugin_voicehubpay"
    assert data["display_name"] == "VoiceHubPay 点歌券查询"
    assert data["version"] == "v0.1.0"
    assert data["author"] == "fhzit"
    assert data["repo"] == "https://github.com/fhzit/astrbot_plugin_voicehubpay"
    assert "aiocqhttp" in METADATA.read_text(encoding="utf-8")


def test_requirements_stay_minimal():
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "aiohttp>=3.11" in text


def test_changelog_records_this_release():
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "## [v0.1.0] - 2026-11-22" in text
    assert "点歌券" in text


def test_readme_has_no_unbalanced_json_blocks():
    """README 里若出现 JSON 示例必须可解析（当前只有纯文本示例）。"""
    blocks = re.findall(r"```json\n(.*?)```", readme_text(), re.S)
    for block in blocks:
        json.loads(block)
