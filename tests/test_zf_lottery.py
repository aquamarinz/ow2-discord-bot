"""Unit tests for /zfwins pure helpers (spec §4.2-§4.3, §7)."""
from __future__ import annotations

from cogs.zf_lottery import match_flow, norm_ws, parse_win_text, sig_time_str

SAMPLE_TRUNC = (
    "抽签助手 ： 恭喜您，在 【GB】御极 YUJI｜Magic& 结 ... 抽签活动中中签 "
    "随机结晶体验装4颗 ！ 快联系作者确认领奖信息。（本私信由系统自动发出）"
)
SAMPLE_COLON = (
    "抽签助手 ： 恭喜您，在 GB：非遗臻品-大漆荔枝纹手托 抽签活动中中签 "
    "大漆擦漆手托随机 ！ 快联系作者确认领奖信息。（本私信由系统自动发出）"
)
SAMPLE_LYN_IC = (
    "抽签助手 ： 恭喜您，在 【IC】繁花轴 抽签活动中中签 繁花轴打样版5颗 ！ "
    "快联系作者确认领奖信息。（本私信由系统自动发出）"
)
SAMPLE_LYN_CAP = (
    "抽签助手 ： 恭喜您，在 《芥末萌》个性键帽上新 抽签活动中中签 "
    "【芥末萌-甜辣咪】1颗 ！ 快联系作者确认领奖信息。（本私信由系统自动发出）"
)


def test_parse_lyn_real_samples():
    # P-M6:spec §7 要求 4 条真实样本全覆盖
    assert parse_win_text(SAMPLE_LYN_IC) == ("【IC】繁花轴", "繁花轴打样版5颗")
    assert parse_win_text(SAMPLE_LYN_CAP) == (
        "《芥末萌》个性键帽上新", "【芥末萌-甜辣咪】1颗")


def test_parse_truncated_activity():
    assert parse_win_text(SAMPLE_TRUNC) == (
        "【GB】御极 YUJI｜Magic& 结 ...", "随机结晶体验装4颗")


def test_parse_activity_with_fullwidth_colon():
    # 活动名自带「：」、奖品含「随机」均不得干扰
    assert parse_win_text(SAMPLE_COLON) == (
        "GB：非遗臻品-大漆荔枝纹手托", "大漆擦漆手托随机")


def test_parse_halfwidth_bang_and_messy_whitespace():
    assert parse_win_text("恭喜您，在  A轴体测试  抽签活动中中签  B奖品 !") == (
        "A轴体测试", "B奖品")


def test_parse_fail_returns_none():
    assert parse_win_text("抽签助手 ： 您的帖子已通过审核") is None
    assert parse_win_text("") is None


def test_sig_time_str_middle_segment():
    assert sig_time_str("thread:3265065:2026/8/8 12:05:6b9b0e29a14b") == "2026/8/8 12:05"


def test_sig_time_str_malformed_no_raise():
    assert sig_time_str("thread:::6b9b0e29a14b") == ""
    assert sig_time_str("garbage") == ""
    assert sig_time_str("") == ""


def test_norm_ws_collapses_whitespace():
    # Task 1 review minor:norm_ws 是解析/匹配两条链的共用前置,需直接断言
    assert norm_ws("  a\n\tb  ") == "a b"
    assert norm_ws("a   b") == "a b"
    assert norm_ws("") == ""


PART = {
    "yL3BNnWW1nd9": {"flow_id": 1, "title": "【GB】御极 YUJI｜Magic& 结晶 观火 陶瓷键帽二团", "ts": 100},
    "nnpanoWaVplv": {"flow_id": 2, "title": "【IC】繁花轴", "ts": 200},
    "OM99pkwRPGK1": {"flow_id": 3, "title": "《芥末萌》个性键帽上新", "ts": 300},
}


def test_match_truncated_prefix_hit():
    assert match_flow("【GB】御极 YUJI｜Magic& 结 ...", PART) == "yL3BNnWW1nd9"


def test_match_untruncated_equality_hit():
    assert match_flow("【IC】繁花轴", PART) == "nnpanoWaVplv"
    assert match_flow("《芥末萌》个性键帽上新", PART) == "OM99pkwRPGK1"


def test_match_untruncated_prefix_only_is_miss():
    # M8 语义:未截断必须全等,仅前缀相同不命中
    assert match_flow("【IC】繁花", PART) is None


def test_match_no_hit():
    assert match_flow("GB：非遗臻品-大漆荔枝纹手托", PART) is None


def test_match_multi_hit_returns_none():
    # R2-M3:同系列共享截断前缀 → 不猜,回 None
    part = {
        "aaa": {"title": "【GB】御极 YUJI｜Magic& 结晶 观火 一团", "ts": 1},
        "bbb": {"title": "【GB】御极 YUJI｜Magic& 结晶 观火 二团", "ts": 2},
    }
    assert match_flow("【GB】御极 YUJI｜Magic& 结 ...", part) is None


def test_match_short_truncated_prefix_blocked_but_short_equality_ok():
    # R2-L1:<6 字符门只挡截断分支;短活动名全等仍可命中
    part = {"ccc": {"title": "繁花轴", "ts": 1}, "ddd": {"title": "繁花轴打样", "ts": 2}}
    assert match_flow("繁花 ...", part) is None
    assert match_flow("繁花轴", part) == "ccc"


def test_match_poison_entries_skipped():
    part = {"eee": "not-a-dict", "fff": {"title": 123}, "ggg": {"title": "【IC】繁花轴", "ts": 1}}
    assert match_flow("【IC】繁花轴", part) == "ggg"
