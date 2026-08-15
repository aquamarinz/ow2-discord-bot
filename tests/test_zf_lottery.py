"""Unit tests for /zfwins pure helpers (spec §4.2-§4.3, §7)."""
from __future__ import annotations

from cogs.zf_lottery import norm_ws, parse_win_text, sig_time_str

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
