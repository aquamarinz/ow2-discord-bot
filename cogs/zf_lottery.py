"""zFrontier 抽奖中奖查询 cog — /zfwins slash command.

只读 zfrontier-lottery 落盘账本（win_seen.json + participated.json），
纯函数解析/匹配/组装，无网络请求、无后台 loop。Spec:
raspberry_pi docs/superpowers/specs/2026-08-15-discord-zfwins-command-design.md
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TZ_CN = timezone(timedelta(hours=8))  # 站点显示时间为 UTC+8

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


_TRUNC_RX = re.compile(r"\s*(\.\.\.|…)+$")  # P-L4:兼容连写省略号
MIN_PREFIX = 6  # 截断分支防误配阈值;全等分支不受限(R2-L1)


def match_flow(activity: str, participated: dict) -> str | None:
    activity = norm_ws(activity)  # P-L2:入参与 title 同规格归一
    stripped = _TRUNC_RX.sub("", activity)
    truncated = stripped != activity
    if truncated and len(stripped) < MIN_PREFIX:
        return None
    hits = []
    for hash_id, entry in participated.items():
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not isinstance(title, str):
            continue
        t = norm_ws(title)
        if (t.startswith(stripped) if truncated else t == stripped):
            hits.append(hash_id)
    return hits[0] if len(hits) == 1 else None


@dataclass(frozen=True)
class WinEntry:
    parsed: bool
    prize: str
    activity: str
    raw_text: str
    time_str: str
    ts: float
    flow_hash: str | None


def sort_key(e: WinEntry) -> float:
    # R2-M1:统一返回 float 时间戳,勿混 datetime/int
    try:
        return datetime.strptime(e.time_str, "%Y/%m/%d %H:%M").replace(tzinfo=TZ_CN).timestamp()
    except ValueError:
        return e.ts


def build_wins(win_seen: dict, participated: dict) -> list[WinEntry]:
    out: list[WinEntry] = []
    for sig, rec in win_seen.items():
        if not isinstance(rec, dict):
            continue
        text = rec.get("text")
        if not isinstance(text, str):
            continue
        ts_raw = rec.get("ts")
        # P-L3:json.loads 接受 NaN 字面量,isfinite 一并挡掉(job-hub 非有限浮点前科)
        ts = (float(ts_raw)
              if isinstance(ts_raw, (int, float)) and not isinstance(ts_raw, bool)
              and math.isfinite(ts_raw) else 0.0)
        time_str = sig_time_str(sig) if isinstance(sig, str) else ""
        parsed = parse_win_text(text)
        # Task 2 review carryover:正则可产出全空白 group(如活动名退化成 " "),
        # 那不是一条能展示的中签记录 → 当解析失败走中性条目。
        if parsed and parsed[0].strip() and parsed[1].strip():
            activity, prize = parsed
            entry = WinEntry(True, prize, activity, norm_ws(text), time_str, ts,
                             match_flow(activity, participated))
        else:
            entry = WinEntry(False, "", "", norm_ws(text), time_str, ts, None)
        out.append(entry)
    out.sort(key=sort_key, reverse=True)
    return out


def read_account(base: Path, slug: str) -> list[WinEntry] | None:
    """None = 数据不可读(缺失/损坏/权限/形状);participated 坏只降级链接。

    P-M2:显式 utf-8(不依赖容器 locale) + ValueError 兜住 UnicodeDecodeError
    (ValueError 子类,JSONDecodeError 亦是),否则逃逸成整条指令 ❌ 破坏账号隔离。
    P-M3:降级路径留日志,operator 可区分 权限/损坏/形状。
    """
    try:
        win_raw = json.loads((base / slug / "win_seen.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("zfwins: %s win_seen unreadable: %r", slug, exc)
        return None
    if not isinstance(win_raw, dict):
        logger.info("zfwins: %s win_seen toplevel not dict", slug)
        return None
    try:
        part_raw = json.loads((base / slug / "participated.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("zfwins: %s participated unreadable (links degraded): %r", slug, exc)
        part_raw = {}
    if not isinstance(part_raw, dict):
        part_raw = {}
    return build_wins(win_raw, part_raw)
