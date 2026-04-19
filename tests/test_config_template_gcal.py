"""Tests that ``workspace/config.json.template`` carries a valid MCP entry.

Separate from ``test_setup_workspace.py`` so the GCal slice stays under
the 300-line cap and verifier tooling can hit the MCP checks in
isolation.
"""

import json
from pathlib import Path

import pytest

from gcal_setup import strip_gcal_mcp_server
from setup_workspace import OPTIONAL_ENV_VARS, resolve_config_template

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "workspace" / "config.json.template"


def _sample_env(**overrides: str) -> dict[str, str]:
    base: dict[str, str] = {
        "OPENROUTER_API_KEY": "sk-or-v1-test",
        "TELEGRAM_BOT_TOKEN": "999:XYZ",
        "TELEGRAM_USER_ID": "42",
        "ADHD_REPO_ROOT": "/tmp/repo",
        "GOOGLE_OAUTH_CREDENTIALS": "/tmp/keys.json",
        "GOOGLE_CALENDAR_MCP_TOKEN_PATH": "/tmp/tokens.json",
    }
    base.update(overrides)
    return base


class TestTemplateShape:
    def test_template_is_valid_json_when_resolved(self) -> None:
        config = resolve_config_template(TEMPLATE_PATH, _sample_env())
        assert isinstance(config, dict)
        tools = config["tools"]
        assert isinstance(tools, dict)
        assert "mcpServers" in tools

    def test_mcp_entry_has_command_and_args(self) -> None:
        config = resolve_config_template(TEMPLATE_PATH, _sample_env())
        tools = config["tools"]
        assert isinstance(tools, dict)
        mcp_servers = tools["mcpServers"]
        assert isinstance(mcp_servers, dict)
        gcal = mcp_servers["google-calendar"]
        assert isinstance(gcal, dict)
        assert gcal["command"] == "node"
        args = gcal["args"]
        assert isinstance(args, list)
        assert len(args) == 1
        assert args[0] == "/tmp/repo/mcp/google-calendar/build/index.js"

    def test_mcp_entry_passes_both_env_vars(self) -> None:
        config = resolve_config_template(TEMPLATE_PATH, _sample_env())
        tools = config["tools"]
        assert isinstance(tools, dict)
        mcp_servers = tools["mcpServers"]
        assert isinstance(mcp_servers, dict)
        gcal = mcp_servers["google-calendar"]
        assert isinstance(gcal, dict)
        env = gcal["env"]
        assert isinstance(env, dict)
        assert env["GOOGLE_OAUTH_CREDENTIALS"] == "/tmp/keys.json"
        assert env["GOOGLE_CALENDAR_MCP_TOKEN_PATH"] == "/tmp/tokens.json"


class TestOptionalDefaults:
    def test_adhd_repo_root_default_resolves_to_repo(self) -> None:
        env: dict[str, str] = {
            "OPENROUTER_API_KEY": "sk-or-v1-test",
            "TELEGRAM_BOT_TOKEN": "999:XYZ",
            "TELEGRAM_USER_ID": "42",
        }
        config = resolve_config_template(TEMPLATE_PATH, env)
        tools = config["tools"]
        assert isinstance(tools, dict)
        mcp_servers = tools["mcpServers"]
        assert isinstance(mcp_servers, dict)
        gcal = mcp_servers["google-calendar"]
        assert isinstance(gcal, dict)
        gcal_args = gcal["args"]
        assert isinstance(gcal_args, list)
        default_root = OPTIONAL_ENV_VARS["ADHD_REPO_ROOT"][1]
        expected = f"{default_root}/mcp/google-calendar/build/index.js"
        assert gcal_args[0] == expected

    def test_token_path_default_is_under_nanobot_data(self) -> None:
        default_token = OPTIONAL_ENV_VARS["GOOGLE_CALENDAR_MCP_TOKEN_PATH"][1]
        token_path = Path(default_token)
        # Relative to ~/.nanobot/data/google-calendar/tokens.json
        assert token_path.name == "tokens.json"
        assert token_path.parent.name == "google-calendar"
        assert token_path.parent.parent.name == "data"
        assert token_path.parent.parent.parent.name == ".nanobot"

    def test_credentials_default_is_empty(self) -> None:
        assert OPTIONAL_ENV_VARS["GOOGLE_OAUTH_CREDENTIALS"][1] == ""


class TestFeatureFlagInteraction:
    def test_strip_after_resolve_yields_empty_mcp_block(self) -> None:
        config = resolve_config_template(TEMPLATE_PATH, _sample_env())
        stripped = strip_gcal_mcp_server(config)
        tools = stripped["tools"]
        assert isinstance(tools, dict)
        assert "mcpServers" not in tools

    def test_resolved_config_roundtrips_to_json(self) -> None:
        config = resolve_config_template(TEMPLATE_PATH, _sample_env())
        encoded = json.dumps(config)
        decoded = json.loads(encoded)
        assert decoded == config


class TestTemplateNoSecrets:
    def test_no_hardcoded_credentials_in_template(self) -> None:
        raw = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "sk-or-" not in raw
        assert "sk-ant-" not in raw
        # Real OAuth client secrets follow patterns like GOCSPX- and
        # Google API keys start with AIza; never hard-code them here.
        assert "GOCSPX-" not in raw
        assert "AIza" not in raw

    def test_env_vars_use_placeholders(self) -> None:
        raw = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "${GOOGLE_OAUTH_CREDENTIALS}" in raw
        assert "${GOOGLE_CALENDAR_MCP_TOKEN_PATH}" in raw
        assert "${ADHD_REPO_ROOT}" in raw


def test_template_without_vendor_build_still_writes_valid_json(
    tmp_path: Path,
) -> None:
    """Template parses even when the vendored build output is absent.

    setup_workspace may be invoked with ``GOOGLE_CALENDAR_ENABLED=false``
    and no vendored tree yet — the JSON it produces must still be valid
    for nanobot to load. This mirrors what ``strip_gcal_mcp_server``
    guarantees when the flag is off.
    """
    config = resolve_config_template(TEMPLATE_PATH, _sample_env())
    stripped = strip_gcal_mcp_server(config)
    target = tmp_path / "config.json"
    target.write_text(json.dumps(stripped, indent=2), encoding="utf-8")
    reparsed = json.loads(target.read_text(encoding="utf-8"))
    tools = reparsed["tools"]
    assert "mcpServers" not in tools


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
