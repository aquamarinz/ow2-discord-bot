"""zFrontier 抽奖中奖查询 cog — /zfwins slash command.

只读 zfrontier-lottery 落盘账本（win_seen.json + participated.json），
纯函数解析/匹配/组装，无网络请求、无后台 loop。Spec:
raspberry_pi docs/superpowers/specs/2026-08-15-discord-zfwins-command-design.md
"""
from __future__ import annotations

import re

MAIL_LIST_URL = "https://www.zfrontier.com/my/mail/list"
FLOW_URL_BASE = "https://www.zfrontier.com/app/flow"

# 私信固定格式:恭喜您，在 <活动名> 抽签活动中中签 <奖品> ！
# 必须 re.search(text 以「抽签助手 ： 」开头);终止符兼容全半角叹号。
WIN_RX = re.compile(r"恭喜您，在\s*(.+?)\s*抽签活动中中签\s*(.+?)\s*[！!]")


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_win_text(text: str) -> tuple[str, str] | None:
    m = WIN_RX.search(norm_ws(text))
    return (m.group(1), m.group(2)) if m else None


def sig_time_str(signature: str) -> str:
    """签名格式 thread:{thread_id}:{time_str}:{hash12},time_str 自身含冒号:
    去前缀后首个 `:` 前是 thread_id、末个 `:` 后是 hash,中间整段是 time_str。"""
    if not signature.startswith("thread:"):
        return ""
    rest = signature[len("thread:"):]
    first = rest.find(":")
    last = rest.rfind(":")
    if first == -1 or last <= first:
        return ""
    return rest[first + 1:last].strip()
