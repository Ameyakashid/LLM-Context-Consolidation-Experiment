"""Smoke tests proving the bot config loads into nanobot-ai and the bot can start.

Split into two groups:
- Always-run: config schema validation, provider resolution, workspace paths
- Credential-gated: Nanobot.from_config(), bot.run() round-trip
"""

import json
import os
from pathlib import Path
import pytest

from nanobot.config.loader import load_config
from nanobot.config.schema import Config
from setup_workspace import resolve_config_template

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_TEMPLATE = REPO_ROOT / "workspace" / "config.json.template"

FAKE_ENV = {
    "OPENROUTER_API_KEY": "sk-or-v1-test-fake-key",
    "TELEGRAM_BOT_TOKEN": "000000:FAKEtoken",
    "TELEGRAM_USER_ID": "99",
}


@pytest.fixture
def resolved_config_path(tmp_path: Path) -> Path:
    """Resolve config template with fake credentials and write to temp dir."""
    config_data = resolve_config_template(CONFIG_TEMPLATE, FAKE_ENV)
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(config_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return config_file


@pytest.fixture
def loaded_config(resolved_config_path: Path) -> Config:
    """Load resolved config through nanobot's loader."""
    return load_config(resolved_config_path)


has_openrouter_key = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)


class TestConfigSchemaValidation:
    """Config template loads into nanobot-ai's Pydantic schema without errors."""

    def test_config_loads_without_error(self, loaded_config: Config) -> None:
        assert isinstance(loaded_config, Config)

    def test_providers_section_populated(self, loaded_config: Config) -> None:
        assert loaded_config.providers.openrouter.api_key == "sk-or-v1-test-fake-key"

    def test_ollama_provider_present(self, loaded_config: Config) -> None:
        assert loaded_config.providers.ollama.api_key == "ollama"

    def test_agent_defaults_model(self, loaded_config: Config) -> None:
        assert loaded_config.agents.defaults.model == "x-ai/grok-4.1-fast"

    def test_agent_defaults_provider(self, loaded_config: Config) -> None:
        assert loaded_config.agents.defaults.provider == "openrouter"

    def test_agent_defaults_max_tokens(self, loaded_config: Config) -> None:
        assert loaded_config.agents.defaults.max_tokens == 4096

    def test_agent_defaults_temperature(self, loaded_config: Config) -> None:
        assert loaded_config.agents.defaults.temperature == pytest.approx(0.1)

    def test_telegram_channel_enabled(self, loaded_config: Config) -> None:
        telegram = loaded_config.channels.telegram
        assert telegram["enabled"] is True

    def test_telegram_channel_token(self, loaded_config: Config) -> None:
        telegram = loaded_config.channels.telegram
        assert telegram["token"] == "000000:FAKEtoken"

    def test_send_progress_disabled(self, loaded_config: Config) -> None:
        assert loaded_config.channels.send_progress is False

    def test_max_tool_iterations_value(self, loaded_config: Config) -> None:
        assert loaded_config.agents.defaults.max_tool_iterations == 10

    def test_timezone_configured(self, loaded_config: Config) -> None:
        assert loaded_config.agents.defaults.timezone == "America/New_York"


class TestProviderResolution:
    """Provider matching resolves openrouter correctly from config."""

    def test_get_provider_returns_openrouter(self, loaded_config: Config) -> None:
        provider = loaded_config.get_provider()
        assert provider is not None
        assert provider.api_key == "sk-or-v1-test-fake-key"

    def test_get_provider_name_is_openrouter(self, loaded_config: Config) -> None:
        name = loaded_config.get_provider_name()
        assert name == "openrouter"

    def test_get_api_key_returns_key(self, loaded_config: Config) -> None:
        api_key = loaded_config.get_api_key()
        assert api_key == "sk-or-v1-test-fake-key"


class TestWorkspacePath:
    """Workspace path in config resolves to a usable directory."""

    def test_workspace_path_is_absolute(self, loaded_config: Config) -> None:
        workspace = loaded_config.workspace_path
        assert workspace.is_absolute()

    def test_workspace_path_under_nanobot_home(self, loaded_config: Config) -> None:
        workspace = loaded_config.workspace_path
        assert ".nanobot" in str(workspace)


class TestToolsConfig:
    """Tools config section loads correctly."""

    def test_web_tools_enabled(self, loaded_config: Config) -> None:
        assert loaded_config.tools.web.enable is True

    def test_exec_tools_disabled(self, loaded_config: Config) -> None:
        assert loaded_config.tools.exec.enable is False


class TestLiveBot:
    """Credential-gated tests that exercise the real bot runtime."""

    @has_openrouter_key
    def test_nanobot_from_config_succeeds(self, tmp_path: Path) -> None:
        from nanobot import Nanobot

        config_data = resolve_config_template(
            CONFIG_TEMPLATE,
            {
                "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
                "TELEGRAM_BOT_TOKEN": "000000:FAKEtoken",
                "TELEGRAM_USER_ID": "99",
            },
        )
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        config_data["agents"]["defaults"]["workspace"] = str(workspace_dir)

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        bot = Nanobot.from_config(config_path=config_file)
        assert bot is not None

    @has_openrouter_key
    def test_bot_run_returns_response(self, tmp_path: Path) -> None:
        import asyncio

        from nanobot import Nanobot

        config_data = resolve_config_template(
            CONFIG_TEMPLATE,
            {
                "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
                "TELEGRAM_BOT_TOKEN": "000000:FAKEtoken",
                "TELEGRAM_USER_ID": "99",
            },
        )
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        config_data["agents"]["defaults"]["workspace"] = str(workspace_dir)

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        bot = Nanobot.from_config(config_path=config_file)

        async def run_bot() -> str:
            result = await bot.run(
                "Reply with exactly: PROOF_OF_LIFE",
                session_key="smoke-test",
            )
            return result.content

        content = asyncio.run(run_bot())
        assert "PROOF_OF_LIFE" in content
