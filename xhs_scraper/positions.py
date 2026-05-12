"""Position-tag detection by keyword match.

A note can carry multiple position tags (e.g. "前端 + 客户端").
Keywords are matched case-insensitively against title + content + tags.
"""
from __future__ import annotations

import re

POSITION_KEYWORDS: dict[str, list[str]] = {
    "后端": ["后端", "后台开发", "服务端", "java开发", "golang", "go开发", "python后端", "c\\+\\+开发"],
    "前端": ["前端", "web前端", "h5开发"],
    "客户端": ["客户端", "ios开发", "android开发", "移动端", "安卓", "苹果开发", "rn开发", "flutter"],
    "算法": ["算法", "机器学习", "深度学习", "ai工程师", "nlp", "cv工程师", "推荐算法", "搜推", "大模型", "llm"],
    "测试": ["测试开发", "测开", "qa工程师", "自动化测试", "测试岗"],
    "运维": ["运维", "sre", "devops", "网络工程师"],
    "数据": ["数据分析", "数据开发", "大数据", "数仓", "数据科学", "bi工程师"],
    "产品": ["产品经理", "pm岗", "产品岗", "产品实习"],
    "运营": ["运营岗", "用户运营", "内容运营", "新媒体运营", "活动运营"],
    "设计": ["ui设计", "ux", "视觉设计", "交互设计", "平面设计"],
    "安全": ["安全工程师", "渗透", "漏洞", "网络安全"],
    "硬件": ["硬件工程师", "芯片", "fpga", "嵌入式", "射频"],
}

POSITION_PATTERNS: dict[str, re.Pattern] = {
    label: re.compile("|".join(kws), re.IGNORECASE)
    for label, kws in POSITION_KEYWORDS.items()
}

ALL_POSITIONS = list(POSITION_KEYWORDS.keys())


def detect_positions(text_parts: list[str]) -> list[str]:
    blob = " ".join(p for p in text_parts if p).lower()
    if not blob:
        return []
    return [label for label, pat in POSITION_PATTERNS.items() if pat.search(blob)]
