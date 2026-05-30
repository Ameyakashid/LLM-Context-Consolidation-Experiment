"""Pure-function tests for cabinet_server: env, path, and IP-whitelist helpers."""

from __future__ import annotations

from pathlib import Path

from cabinet_server import (
    DEFAULT_IP_WHITELIST_JSON,
    _cabinet_env,
    client_ip_allowed,
    is_cabinet_autostart_enabled,
    is_cabinet_enabled,
    parse_ip_whitelist,
    resolve_cabinet_dir,
    resolve_cabinet_feed_dir,
    resolve_wallpaper_dir,
)


class TestCabinetEnv:
    def test_prefers_primary_key(self) -> None:
        assert _cabinet_env({"A": "x", "B": "y"}, "A", "B", default="z") == "x"

    def test_falls_back_when_primary_blank(self) -> None:
        assert _cabinet_env({"A": "  ", "B": "y"}, "A", "B", default="z") == "y"

    def test_falls_back_when_primary_absent(self) -> None:
        assert _cabinet_env({"B": "y"}, "A", "B", default="z") == "y"

    def test_default_when_all_absent(self) -> None:
        assert _cabinet_env({}, "A", "B", default="z") == "z"


class TestEnabledFlags:
    def test_cabinet_enabled_true(self) -> None:
        assert is_cabinet_enabled({"CABINET_ENABLED": "true"}) is True

    def test_cabinet_enabled_case_insensitive(self) -> None:
        assert is_cabinet_enabled({"CABINET_ENABLED": "True"}) is True

    def test_falls_back_to_magicmirror_enabled(self) -> None:
        assert is_cabinet_enabled({"MAGICMIRROR_ENABLED": "true"}) is True

    def test_cabinet_overrides_legacy(self) -> None:
        env = {"CABINET_ENABLED": "false", "MAGICMIRROR_ENABLED": "true"}
        assert is_cabinet_enabled(env) is False

    def test_default_false(self) -> None:
        assert is_cabinet_enabled({}) is False

    def test_autostart_fallback(self) -> None:
        env = {"MAGICMIRROR_AUTOSTART_ENABLED": "true"}
        assert is_cabinet_autostart_enabled(env) is True


class TestResolvers:
    def test_cabinet_dir(self, tmp_path: Path) -> None:
        assert resolve_cabinet_dir(tmp_path) == tmp_path / "cabinet"

    def test_feed_dir(self, tmp_path: Path) -> None:
        assert resolve_cabinet_feed_dir(tmp_path) == tmp_path / "cabinet" / "feeds"

    def test_wallpaper_default(self, tmp_path: Path) -> None:
        got = resolve_wallpaper_dir(tmp_path, {})
        assert got == tmp_path / "cabinet" / "wallpapers"

    def test_wallpaper_override(self, tmp_path: Path) -> None:
        custom = tmp_path / "my_pics"
        got = resolve_wallpaper_dir(tmp_path, {"CABINET_WALLPAPER_DIR": str(custom)})
        assert got == custom

    def test_repo_tree_has_cabinet_index(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        assert (resolve_cabinet_dir(repo_root) / "index.html").is_file()


class TestParseIpWhitelist:
    def test_default_parses_six_networks(self) -> None:
        nets = parse_ip_whitelist(DEFAULT_IP_WHITELIST_JSON)
        assert len(nets) == 6

    def test_bare_ip_becomes_host_network(self) -> None:
        nets = parse_ip_whitelist('["127.0.0.1"]')
        assert str(nets[0]) == "127.0.0.1/32"

    def test_invalid_json_returns_empty(self) -> None:
        assert parse_ip_whitelist("not json") == []

    def test_non_list_returns_empty(self) -> None:
        assert parse_ip_whitelist('{"a": 1}') == []

    def test_skips_invalid_entries(self) -> None:
        nets = parse_ip_whitelist('["192.168.0.0/16", "garbage", 42]')
        assert len(nets) == 1
        assert str(nets[0]) == "192.168.0.0/16"


class TestClientIpAllowed:
    def test_empty_whitelist_allows_all(self) -> None:
        assert client_ip_allowed("8.8.8.8", []) is True

    def test_loopback_in_loopback_net(self) -> None:
        nets = parse_ip_whitelist('["127.0.0.1"]')
        assert client_ip_allowed("127.0.0.1", nets) is True

    def test_out_of_range_rejected(self) -> None:
        nets = parse_ip_whitelist('["127.0.0.1", "192.168.0.0/16"]')
        assert client_ip_allowed("8.8.8.8", nets) is False

    def test_lan_address_in_rfc1918(self) -> None:
        nets = parse_ip_whitelist('["192.168.0.0/16"]')
        assert client_ip_allowed("192.168.1.50", nets) is True

    def test_ipv6_loopback(self) -> None:
        nets = parse_ip_whitelist('["::1"]')
        assert client_ip_allowed("::1", nets) is True

    def test_ipv4_mapped_ipv6_unwrapped_to_match_ipv4_cidr(self) -> None:
        nets = parse_ip_whitelist('["192.168.0.0/16"]')
        assert client_ip_allowed("::ffff:192.168.1.5", nets) is True

    def test_garbage_host_rejected(self) -> None:
        nets = parse_ip_whitelist('["127.0.0.1"]')
        assert client_ip_allowed("not-an-ip", nets) is False
