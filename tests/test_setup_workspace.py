"""Tests for workspace setup script."""

import json
from pathlib import Path
from typing import Generator

import pytest

from setup_workspace import (
    copy_workspace_files,
    load_env_file,
    resolve_config_template,
    validate_env_vars,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    """Create a temporary .env file with valid test values."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENROUTER_API_KEY=sk-or-v1-test-key-abc123\n"
        "TELEGRAM_BOT_TOKEN=999999:ABCtest\n"
        "TELEGRAM_USER_ID=42\n",
        encoding="utf-8",
    )
    return env_file


@pytest.fixture
def tmp_workspace_target(tmp_path: Path) -> Path:
    """Provide a temp directory for workspace file copies."""
    target = tmp_path / "workspace"
    target.mkdir()
    return target


class TestLoadEnvFile:
    def test_parses_valid_env(self, tmp_env_file: Path) -> None:
        result = load_env_file(tmp_env_file)
        assert result["OPENROUTER_API_KEY"] == "sk-or-v1-test-key-abc123"
        assert result["TELEGRAM_BOT_TOKEN"] == "999999:ABCtest"
        assert result["TELEGRAM_USER_ID"] == "42"

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# This is a comment\n"
            "\n"
            "KEY=value\n"
            "  # indented comment\n",
            encoding="utf-8",
        )
        result = load_env_file(env_file)
        assert result == {"KEY": "value"}

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match=".env file not found"):
            load_env_file(tmp_path / "nonexistent.env")


class TestValidateEnvVars:
    def test_passes_with_valid_vars(self) -> None:
        env = {
            "OPENROUTER_API_KEY": "sk-or-v1-real-key",
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_USER_ID": "42",
        }
        validate_env_vars(env)

    def test_rejects_placeholder_api_key(self) -> None:
        env = {
            "OPENROUTER_API_KEY": "sk-or-v1-your-key-here",
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_USER_ID": "42",
        }
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            validate_env_vars(env)

    def test_rejects_placeholder_user_id(self) -> None:
        env = {
            "OPENROUTER_API_KEY": "sk-or-v1-real-key",
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_USER_ID": "123456789",
        }
        with pytest.raises(ValueError, match="TELEGRAM_USER_ID"):
            validate_env_vars(env)

    def test_rejects_missing_vars(self) -> None:
        with pytest.raises(ValueError, match="Missing or placeholder"):
            validate_env_vars({})


class TestResolveConfigTemplate:
    def test_resolves_placeholders(self, tmp_path: Path) -> None:
        template = tmp_path / "config.json.template"
        template.write_text(
            json.dumps(
                {
                    "providers": {"openrouter": {"apiKey": "${OPENROUTER_API_KEY}"}},
                    "channels": {
                        "telegram": {
                            "token": "${TELEGRAM_BOT_TOKEN}",
                            "allowFrom": ["${TELEGRAM_USER_ID}"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        env = {
            "OPENROUTER_API_KEY": "sk-test",
            "TELEGRAM_BOT_TOKEN": "999:XYZ",
            "TELEGRAM_USER_ID": "55",
        }
        result = resolve_config_template(template, env)
        assert result["providers"]["openrouter"]["apiKey"] == "sk-test"
        assert result["channels"]["telegram"]["token"] == "999:XYZ"
        assert result["channels"]["telegram"]["allowFrom"] == ["55"]


class TestResolveOptionalTimezone:
    """Verify NANOBOT_TIMEZONE optional env var resolution."""

    def test_resolves_timezone_with_default(self, tmp_path: Path) -> None:
        template = tmp_path / "config.json.template"
        template.write_text(
            json.dumps(
                {
                    "agents": {"defaults": {"timezone": "${NANOBOT_TIMEZONE}"}},
                    "providers": {"openrouter": {"apiKey": "${OPENROUTER_API_KEY}"}},
                    "channels": {
                        "telegram": {
                            "token": "${TELEGRAM_BOT_TOKEN}",
                            "allowFrom": ["${TELEGRAM_USER_ID}"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        env = {
            "OPENROUTER_API_KEY": "sk-test",
            "TELEGRAM_BOT_TOKEN": "999:XYZ",
            "TELEGRAM_USER_ID": "55",
        }
        result = resolve_config_template(template, env)
        assert result["agents"]["defaults"]["timezone"] == "America/New_York"

    def test_resolves_timezone_with_override(self, tmp_path: Path) -> None:
        template = tmp_path / "config.json.template"
        template.write_text(
            json.dumps(
                {
                    "agents": {"defaults": {"timezone": "${NANOBOT_TIMEZONE}"}},
                    "providers": {"openrouter": {"apiKey": "${OPENROUTER_API_KEY}"}},
                    "channels": {
                        "telegram": {
                            "token": "${TELEGRAM_BOT_TOKEN}",
                            "allowFrom": ["${TELEGRAM_USER_ID}"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        env = {
            "OPENROUTER_API_KEY": "sk-test",
            "TELEGRAM_BOT_TOKEN": "999:XYZ",
            "TELEGRAM_USER_ID": "55",
            "NANOBOT_TIMEZONE": "Europe/London",
        }
        result = resolve_config_template(template, env)
        assert result["agents"]["defaults"]["timezone"] == "Europe/London"


class TestCopyWorkspaceFiles:
    def test_copies_all_template_files(self, tmp_workspace_target: Path) -> None:
        copied = copy_workspace_files(tmp_workspace_target)
        assert "SOUL.md" in copied
        assert "USER.md" in copied
        assert "HEARTBEAT.md" in copied
        for filename in copied:
            assert (tmp_workspace_target / filename).exists()

    def test_copied_content_matches_source(self, tmp_workspace_target: Path) -> None:
        copy_workspace_files(tmp_workspace_target)
        src_soul = REPO_ROOT / "workspace" / "SOUL.md"
        dst_soul = tmp_workspace_target / "SOUL.md"
        assert src_soul.read_text(encoding="utf-8") == dst_soul.read_text(
            encoding="utf-8"
        )

    def test_copies_nested_memory_seed(self, tmp_workspace_target: Path) -> None:
        copied = copy_workspace_files(tmp_workspace_target)
        assert "memory/MEMORY.md" in copied
        dst_memory = tmp_workspace_target / "memory" / "MEMORY.md"
        assert dst_memory.exists()
        assert dst_memory.is_file()

    def test_nested_memory_bytes_match_source(
        self, tmp_workspace_target: Path
    ) -> None:
        copy_workspace_files(tmp_workspace_target)
        src_memory = REPO_ROOT / "workspace" / "memory" / "MEMORY.md"
        dst_memory = tmp_workspace_target / "memory" / "MEMORY.md"
        assert src_memory.read_bytes() == dst_memory.read_bytes()


class TestWorkspaceTemplateFiles:
    """Verify the workspace template files themselves are well-formed."""

    def test_soul_md_exists_and_nonempty(self) -> None:
        soul = REPO_ROOT / "workspace" / "SOUL.md"
        assert soul.exists()
        content = soul.read_text(encoding="utf-8")
        assert len(content) > 50

    def test_user_md_exists_and_nonempty(self) -> None:
        user = REPO_ROOT / "workspace" / "USER.md"
        assert user.exists()
        content = user.read_text(encoding="utf-8")
        assert len(content) > 50

    def test_heartbeat_md_exists_and_nonempty(self) -> None:
        heartbeat = REPO_ROOT / "workspace" / "HEARTBEAT.md"
        assert heartbeat.exists()
        content = heartbeat.read_text(encoding="utf-8")
        assert len(content) > 20

    def test_config_template_is_valid_json(self) -> None:
        config = REPO_ROOT / "workspace" / "config.json.template"
        assert config.exists()
        raw = config.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert "providers" in parsed
        assert "channels" in parsed
        assert "agents" in parsed

    def test_config_template_has_no_hardcoded_secrets(self) -> None:
        config = REPO_ROOT / "workspace" / "config.json.template"
        raw = config.read_text(encoding="utf-8")
        assert "sk-or-" not in raw
        assert "sk-ant-" not in raw
        assert "${OPENROUTER_API_KEY}" in raw
        assert "${TELEGRAM_BOT_TOKEN}" in raw

    def test_config_template_uses_openrouter_provider(self) -> None:
        config = REPO_ROOT / "workspace" / "config.json.template"
        parsed = json.loads(config.read_text(encoding="utf-8"))
        assert "openrouter" in parsed["providers"]
        assert parsed["agents"]["defaults"]["provider"] == "openrouter"

    def test_config_template_has_ollama_fallback(self) -> None:
        config = REPO_ROOT / "workspace" / "config.json.template"
        parsed = json.loads(config.read_text(encoding="utf-8"))
        assert "ollama" in parsed["providers"]

    def test_config_template_has_telegram_channel(self) -> None:
        config = REPO_ROOT / "workspace" / "config.json.template"
        parsed = json.loads(config.read_text(encoding="utf-8"))
        telegram = parsed["channels"]["telegram"]
        assert telegram["enabled"] is True
        assert "${TELEGRAM_BOT_TOKEN}" in telegram["token"]

    def test_config_template_uses_pinned_model(self) -> None:
        config = REPO_ROOT / "workspace" / "config.json.template"
        parsed = json.loads(config.read_text(encoding="utf-8"))
        assert parsed["agents"]["defaults"]["model"] == "x-ai/grok-4.1-fast"


class TestNanobotInstallation:
    """Verify nanobot-ai is importable and correct version."""

    def test_nanobot_importable(self) -> None:
        import nanobot  # noqa: F401

    def test_nanobot_version(self) -> None:
        from importlib.metadata import version

        assert version("nanobot-ai") == "0.1.5"


class TestNoHardcodedPaths:
    """Verify setup script uses pathlib, not hardcoded OS paths."""

    def test_setup_script_uses_pathlib(self) -> None:
        script = REPO_ROOT / "setup_workspace.py"
        content = script.read_text(encoding="utf-8")
        assert "Path.home()" in content
        assert "C:\\" not in content
        assert "/Users/" not in content
