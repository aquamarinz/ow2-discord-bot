"""Tests for TWITCH_MINERS env parsing."""
import pytest

from config import parse_twitch_miners


def test_parse_empty_returns_empty_dict():
    assert parse_twitch_miners("") == {}


def test_parse_whitespace_only_returns_empty_dict():
    assert parse_twitch_miners("   ") == {}


def test_parse_single_entry():
    result = parse_twitch_miners("alice=twitch-drops-miner-alice:8080")
    assert result == {"alice": ("twitch-drops-miner-alice", 8080)}


def test_parse_multiple_entries():
    result = parse_twitch_miners(
        "alice=twitch-drops-miner-alice:8080,bob=twitch-drops-miner-bob:8081"
    )
    assert result == {
        "alice": ("twitch-drops-miner-alice", 8080),
        "bob": ("twitch-drops-miner-bob", 8081),
    }


def test_parse_normalizes_uppercase_user():
    result = parse_twitch_miners("Alice=twitch-drops-miner-alice:8080")
    assert "alice" in result and "Alice" not in result


def test_parse_strips_whitespace():
    result = parse_twitch_miners("  alice  =  twitch-drops-miner-alice  :  8080  ")
    assert result == {"alice": ("twitch-drops-miner-alice", 8080)}


def test_parse_rejects_duplicate_canonical_keys():
    with pytest.raises(ValueError, match="duplicate"):
        parse_twitch_miners(
            "Alice=twitch-drops-miner-a:8080,alice=twitch-drops-miner-b:8081"
        )


def test_parse_rejects_invalid_user():
    with pytest.raises(ValueError, match="invalid"):
        parse_twitch_miners("bad@user=twitch-drops-miner:8080")


def test_parse_rejects_missing_port():
    with pytest.raises(ValueError, match="format"):
        parse_twitch_miners("alice=twitch-drops-miner-alice")


def test_parse_rejects_non_numeric_port():
    with pytest.raises(ValueError, match="port"):
        parse_twitch_miners("alice=twitch-drops-miner-alice:notaport")


def test_parse_rejects_missing_equals():
    with pytest.raises(ValueError, match="format"):
        parse_twitch_miners("alice:twitch-drops-miner-alice:8080")
