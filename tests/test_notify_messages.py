"""Unit tests for notifier message builders (spec §3.5, §3.3 budget)."""
from __future__ import annotations

from cogs.miner import (
    NOTIFY_CONTENT_BUDGET,
    build_claim_message,
    build_campaign_announce,
    _hd_box_art_url,
)


def _ev(cid="c1", campaign="Day 4", game="Overwatch", n=None, drops=(),
        box="https://static-cdn.jtvnw.net/ttv-boxart/515025-120x160.jpg"):
    drops = list(drops)
    return {"id": cid, "campaign": campaign, "game": game,
            "drop_count": n if n is not None else len(drops),
            "box_art_url": box, "drops": drops}


def _evd(name="Spray", mins=60, img="https://cdn.example/r1.png"):
    return {"name": name, "required_minutes": mins, "image_url": img}


def test_claim_message_single_group():
    content, img = build_claim_message("42", [{
        "campaign": "OWCS Day 3", "drops": ["Esports Loot Box"],
        "done": False, "image_url": "https://cdn.example/x.png"}])
    assert content == (
        "<@42> 🎉 已领取掉宝:**Esports Loot Box** _(OWCS Day 3)_")
    assert img == "https://cdn.example/x.png"


def test_claim_message_multi_group_done_marker():
    content, img = build_claim_message("42", [
        {"campaign": "A", "drops": ["D1", "D2"], "done": True, "image_url": None},
        {"campaign": "B", "drops": ["D3"], "done": False,
         "image_url": "https://cdn.example/b.png"},
    ])
    assert content == (
        "<@42> 🎉 已领取掉宝:**D1**、**D2** _(A)_ ✅ 全部领完\n"
        "**D3** _(B)_")
    assert img == "https://cdn.example/b.png"   # first non-None wins


def test_claim_message_truncated_at_budget():
    groups = [{"campaign": f"C{i}", "drops": [f"Drop-{i}-" + "x" * 40],
               "done": False, "image_url": None} for i in range(60)]
    content, _ = build_claim_message("42", groups)
    assert len(content) <= NOTIFY_CONTENT_BUDGET
    assert content.endswith("…等 60 个")


# ── _hd_box_art_url (spec test 5) ───────────────────────────────────

def test_hd_box_art_rewrites_size_suffix():
    assert _hd_box_art_url(
        "https://static-cdn.jtvnw.net/ttv-boxart/515025-120x160.jpg"
    ) == "https://static-cdn.jtvnw.net/ttv-boxart/515025-600x800.jpg"


def test_hd_box_art_no_suffix_passthrough():
    assert _hd_box_art_url("https://cdn.example/box.png") == "https://cdn.example/box.png"


def test_hd_box_art_invalid_is_none():
    assert _hd_box_art_url(None) is None
    assert _hd_box_art_url("not a url") is None
    assert _hd_box_art_url("https://bad url/x-1x1.jpg") is None


# ── build_campaign_announce (spec tests 2, 3, 4, 6) ─────────────────

def test_announce_gallery_shares_url_and_caps_at_four():
    drops = [_evd(name=f"D{i}", mins=(i + 1) * 10, img=f"https://cdn.example/r{i}.png")
             for i in range(6)]
    content, embeds = build_campaign_announce(["42"], _ev(drops=drops))
    assert content == "<@42> ⛏️ 开始挖新活动:**Day 4** _(Overwatch)_"
    assert len(embeds) == 4                                   # 6 可用图 → 前 4
    urls = {e.url for e in embeds}
    assert urls == {"https://www.twitch.tv/drops/campaigns?dropID=c1"}
    assert embeds[0].image.url == "https://cdn.example/r0.png"  # 升序第一张
    assert [e.image.url for e in embeds[1:]] == [
        "https://cdn.example/r1.png", "https://cdn.example/r2.png",
        "https://cdn.example/r3.png"]
    # 主 embed 独有 title/description/thumbnail;附属 embed 无
    assert embeds[0].title == "Day 4"
    assert embeds[0].thumbnail.url == (
        "https://static-cdn.jtvnw.net/ttv-boxart/515025-600x800.jpg")
    assert embeds[1].title is None and embeds[1].description is None
    # 文字列表:全部 6 个 drop 都在(预算内),升序
    desc = embeds[0].description
    assert desc.startswith("🎮 Overwatch · 6 个掉宝\n\n")
    assert desc.index("**D0** — 10 分钟") < desc.index("**D5** — 60 分钟")


def test_announce_dedupes_image_urls_and_sorts_none_last():
    drops = [
        _evd(name="Late", mins=None, img="https://cdn.example/z.png"),
        _evd(name="B", mins=120, img="https://cdn.example/same.png"),
        _evd(name="A", mins=30, img="https://cdn.example/same.png"),
        _evd(name="NoImg", mins=60, img=None),
    ]
    content, embeds = build_campaign_announce(["42"], _ev(drops=drops))
    # same.png 去重后只剩 2 张图 → 主 embed + 1 附属
    assert len(embeds) == 2
    assert embeds[0].image.url == "https://cdn.example/same.png"   # mins=30 最先
    assert embeds[1].image.url == "https://cdn.example/z.png"      # None 沉底
    desc = embeds[0].description
    # 升序 A(30) < NoImg(60) < B(120) < Late(None 沉底,无时长文案)
    assert desc.index("**A** — 30 分钟") < desc.index("**NoImg** — 60 分钟") \
        < desc.index("**B** — 120 分钟") < desc.index("**Late**")
    assert "**Late** —" not in desc                                # None 省略时长


def test_announce_no_reward_images_falls_back_to_box_art():
    content, embeds = build_campaign_announce(
        ["42"], _ev(drops=[_evd(img=None)]))
    assert len(embeds) == 1
    assert embeds[0].image.url == (
        "https://static-cdn.jtvnw.net/ttv-boxart/515025-600x800.jpg")
    assert embeds[0].thumbnail.url is None                         # 缩略图位空


def test_announce_no_images_at_all_is_textonly():
    content, embeds = build_campaign_announce(
        ["42"], _ev(drops=[_evd(img=None)], box=None))
    assert len(embeds) == 1
    assert embeds[0].image.url is None and embeds[0].thumbnail.url is None
    assert embeds[0].title == "Day 4"                              # 文字仍全


def test_announce_mentions_dedup_is_callers_job_order_kept_and_capped():
    ids = [str(i) for i in range(12)]
    content, _ = build_campaign_announce(ids, _ev(drops=[_evd()]))
    assert content.startswith("<@0> <@1>")
    assert "<@9> 等 12 人 ⛏️ 开始挖新活动:**Day 4** _(Overwatch)_" in content
    assert "<@10>" not in content                                  # cap 10
    # 活动名永远完整在尾部,不被任何截断吃掉
    assert content.endswith("**Day 4** _(Overwatch)_")


def test_announce_description_budget_clamped():
    drops = [_evd(name="D" + "x" * 60, mins=i, img=None) for i in range(80)]
    _, embeds = build_campaign_announce(["42"], _ev(drops=drops, n=80))
    desc = embeds[0].description
    assert len(desc) <= NOTIFY_CONTENT_BUDGET
    assert desc.endswith("…等 80 个")


def test_announce_campaign_id_quoted_in_url():
    _, embeds = build_campaign_announce(
        ["42"], _ev(cid="ab c&中/文", drops=[_evd()]))
    assert embeds[0].url == (
        "https://www.twitch.tv/drops/campaigns?dropID="
        "ab%20c%26%E4%B8%AD%2F%E6%96%87")


def test_announce_clamps_overlong_campaign_and_game_fields():
    """Discord hard-rejects embed title >256 and content >2000 with 50035,
    failing the WHOLE message. Since mining state is append-only and every
    link fails identically, an unclamped overlong name would lose the
    announcement permanently. Clamp per field — never slice content whole.
    """
    ids = [str(10 ** 19 + i) for i in range(12)]      # 12 x 20-digit snowflake
    content, embeds = build_campaign_announce(
        ids, _ev(campaign="C" * 500, game="G" * 300, drops=[_evd()]))
    assert embeds[0].title == "C" * 256
    assert len(embeds[0].title) == 256
    assert embeds[0].description.startswith("🎮 " + "G" * 100 + " · 1 个掉宝\n\n")
    # Worst case (mention cap + max-length names) is structurally bounded.
    assert len(content) < 2000
    # Campaign name still sits complete at the tail, at its clamped length.
    assert content.endswith("**" + "C" * 256 + "** _(" + "G" * 100 + ")_")
