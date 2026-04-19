"""MagicMirror² vendor integrity + config template content tests."""

import hashlib
from pathlib import Path

import pytest

from magicmirror_setup import (
    MAGICMIRROR_CONFIG_VARS,
    MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES,
    MODULE_NAMES,
    render_magicmirror_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = (
    REPO_ROOT / "magicmirror" / "config" / "config.js.template"
)


class TestRenderMagicmirrorConfig:
    def _make_template_tree(self, tmp_path: Path, template: str) -> Path:
        repo_root = tmp_path / "repo"
        config_dir = repo_root / "magicmirror" / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "config.js.template").write_text(
            template, encoding="utf-8"
        )
        return repo_root

    def test_substitutes_all_three_placeholders(self, tmp_path: Path) -> None:
        template = (
            "address: ${MAGICMIRROR_HOST};\n"
            "port: ${MAGICMIRROR_PORT};\n"
            "whitelist: ${MAGICMIRROR_IP_WHITELIST_JSON};\n"
        )
        repo_root = self._make_template_tree(tmp_path, template)
        env = {
            "MAGICMIRROR_HOST": "10.0.0.5",
            "MAGICMIRROR_PORT": "9090",
            "MAGICMIRROR_IP_WHITELIST_JSON": '["10.0.0.0/8"]',
        }
        render_magicmirror_config(repo_root, env)
        rendered = (
            repo_root / "magicmirror" / "config" / "config.js"
        ).read_text(encoding="utf-8")
        assert "address: 10.0.0.5;" in rendered
        assert "port: 9090;" in rendered
        assert 'whitelist: ["10.0.0.0/8"];' in rendered
        assert "${" not in rendered

    def test_uses_defaults_when_env_omitted(self, tmp_path: Path) -> None:
        template = (
            "host=${MAGICMIRROR_HOST}\n"
            "port=${MAGICMIRROR_PORT}\n"
            "wl=${MAGICMIRROR_IP_WHITELIST_JSON}\n"
        )
        repo_root = self._make_template_tree(tmp_path, template)
        render_magicmirror_config(repo_root, {})
        rendered = (
            repo_root / "magicmirror" / "config" / "config.js"
        ).read_text(encoding="utf-8")
        assert f"host={MAGICMIRROR_CONFIG_VARS['MAGICMIRROR_HOST']}" in rendered
        assert f"port={MAGICMIRROR_CONFIG_VARS['MAGICMIRROR_PORT']}" in rendered
        assert (
            f"wl={MAGICMIRROR_CONFIG_VARS['MAGICMIRROR_IP_WHITELIST_JSON']}"
            in rendered
        )

    def test_raises_when_template_missing(self, tmp_path: Path) -> None:
        with pytest.raises(
            FileNotFoundError, match="MagicMirror config template missing"
        ):
            render_magicmirror_config(tmp_path, {})

    def test_does_not_modify_template_file(self, tmp_path: Path) -> None:
        template = "port=${MAGICMIRROR_PORT}\n"
        repo_root = self._make_template_tree(tmp_path, template)
        render_magicmirror_config(repo_root, {"MAGICMIRROR_PORT": "7777"})
        tpl = (
            repo_root / "magicmirror" / "config" / "config.js.template"
        ).read_text(encoding="utf-8")
        assert tpl == template


class TestVendorByteIdentity:
    """All four package.json files must match references/ byte-for-byte."""

    def test_magicmirror_core_matches_upstream(self) -> None:
        vendored = REPO_ROOT / "magicmirror" / "package.json"
        upstream = REPO_ROOT / "references" / "MagicMirror" / "package.json"
        assert vendored.exists() and upstream.exists()
        vendored_hash = hashlib.sha256(vendored.read_bytes()).hexdigest()
        upstream_hash = hashlib.sha256(upstream.read_bytes()).hexdigest()
        assert vendored_hash == upstream_hash

    @pytest.mark.parametrize("module_name", list(MODULE_NAMES))
    def test_module_package_json_matches_upstream(
        self, module_name: str
    ) -> None:
        vendored = (
            REPO_ROOT
            / "magicmirror"
            / "modules"
            / module_name
            / "package.json"
        )
        upstream = REPO_ROOT / "references" / module_name / "package.json"
        assert vendored.exists() and upstream.exists()
        vendored_hash = hashlib.sha256(vendored.read_bytes()).hexdigest()
        upstream_hash = hashlib.sha256(upstream.read_bytes()).hexdigest()
        assert vendored_hash == upstream_hash

    @pytest.mark.parametrize(
        "pin_path,commit,version,upstream_frag",
        [
            (
                "magicmirror/.vendor-source.md",
                "d05ea751d9b4dd106d02c7e1ed497bac3c77549e",
                "2.35.0",
                "github.com/MagicMirrorOrg/MagicMirror",
            ),
            (
                "magicmirror/modules/MMM-WebHookAlerts/.vendor-source.md",
                "9e56e572d16d5ee9d2a7b3f3cdc3d208250cfd9d",
                "1.1.0",
                "github.com/PJTewkesbury/MMM-WebHookAlerts",
            ),
            (
                "magicmirror/modules/MMM-Markdown/.vendor-source.md",
                "77a50bb089bd9d3b9d32c23be695e81856d43e1b",
                "1.0.0",
                "github.com/wilfullyapt/MMM-Markdown",
            ),
            (
                "magicmirror/modules/MMM-pages/.vendor-source.md",
                "df7fdce88823f885af4227d24fdfb95f1b99746a",
                "1.4.0",
                "github.com/edward-shen/MMM-pages",
            ),
        ],
    )
    def test_vendor_source_records_pin(
        self,
        pin_path: str,
        commit: str,
        version: str,
        upstream_frag: str,
    ) -> None:
        pin = REPO_ROOT / pin_path
        assert pin.exists()
        text = pin.read_text(encoding="utf-8")
        assert commit in text
        assert version in text
        assert upstream_frag in text

    @pytest.mark.parametrize(
        "vendor_root",
        [
            "magicmirror",
            "magicmirror/modules/MMM-WebHookAlerts",
            "magicmirror/modules/MMM-Markdown",
            "magicmirror/modules/MMM-pages",
        ],
    )
    def test_stripped_metadata_absent(self, vendor_root: str) -> None:
        root = REPO_ROOT / vendor_root
        for stripped in (".git", ".github", ".claude"):
            assert not (root / stripped).exists(), (
                f"Expected {stripped} to be stripped from {vendor_root}"
            )


class TestGitignoreProtections:
    def _gitignore_lines(self) -> list[str]:
        content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        return [line.strip() for line in content.splitlines()]

    def test_core_node_modules_ignored(self) -> None:
        assert "magicmirror/node_modules/" in self._gitignore_lines()

    def test_module_node_modules_ignored(self) -> None:
        assert (
            "magicmirror/modules/MMM-*/node_modules/"
            in self._gitignore_lines()
        )

    def test_rendered_config_ignored(self) -> None:
        assert "magicmirror/config/config.js" in self._gitignore_lines()


class TestEnvExampleEntries:
    def _env_example_text(self) -> str:
        return (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "key",
        [
            "MAGICMIRROR_ENABLED=",
            "MAGICMIRROR_HOST=",
            "MAGICMIRROR_PORT=",
            "MAGICMIRROR_IP_WHITELIST_JSON=",
            "MAGICMIRROR_WEBHOOK_HOST=",
            "MAGICMIRROR_WEBHOOK_PORT=",
        ],
    )
    def test_env_entry_documented(self, key: str) -> None:
        assert key in self._env_example_text()


class TestConfigTemplateContent:
    def _template_text(self) -> str:
        return TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_template_exists_and_is_tracked(self) -> None:
        assert TEMPLATE_PATH.is_file()

    @pytest.mark.parametrize(
        "placeholder",
        [
            "${MAGICMIRROR_HOST}",
            "${MAGICMIRROR_PORT}",
            "${MAGICMIRROR_IP_WHITELIST_JSON}",
        ],
    )
    def test_contains_env_placeholder(self, placeholder: str) -> None:
        assert placeholder in self._template_text()

    @pytest.mark.parametrize(
        "template_name", list(MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES)
    )
    def test_webhook_template_registered(self, template_name: str) -> None:
        text = self._template_text()
        assert f'templateName: "{template_name}"' in text

    @pytest.mark.parametrize(
        "feed", ["tasks.md", "state_buffers.md", "schedule.md"]
    )
    def test_markdown_feed_registered(self, feed: str) -> None:
        text = self._template_text()
        assert f'markdownFilename: "{feed}"' in text

    @pytest.mark.parametrize(
        "page_class", ["page0", "page1", "page2"]
    )
    def test_mmm_pages_class_registered(self, page_class: str) -> None:
        text = self._template_text()
        assert page_class in text

    def test_mmm_webhookalerts_fullscreen_above(self) -> None:
        text = self._template_text()
        assert 'module: "MMM-WebHookAlerts"' in text
        assert 'position: "fullscreen_above"' in text

    def test_mmm_pages_module_block_present(self) -> None:
        text = self._template_text()
        assert 'module: "MMM-pages"' in text

    def test_clock_fixed_no_newsfeed_no_weather(self) -> None:
        text = self._template_text()
        assert 'module: "clock"' in text
        assert "newsfeed" not in text
        assert "weather" not in text
        assert "compliments" not in text

    def test_no_hardcoded_credentials(self) -> None:
        text = self._template_text()
        assert "sk-or-" not in text
        assert "sk-ant-" not in text
        assert "GOCSPX-" not in text
        assert "AIza" not in text

    def test_rendered_config_has_no_placeholders_left(
        self, tmp_path: Path
    ) -> None:
        # Use the real template; render into tmp_path with sample env.
        repo_copy = tmp_path / "repo"
        (repo_copy / "magicmirror" / "config").mkdir(parents=True)
        (repo_copy / "magicmirror" / "config" / "config.js.template").write_text(
            self._template_text(), encoding="utf-8"
        )
        render_magicmirror_config(
            repo_copy,
            {
                "MAGICMIRROR_HOST": "0.0.0.0",
                "MAGICMIRROR_PORT": "8080",
                "MAGICMIRROR_IP_WHITELIST_JSON": '["127.0.0.1"]',
            },
        )
        rendered = (
            repo_copy / "magicmirror" / "config" / "config.js"
        ).read_text(encoding="utf-8")
        assert "${" not in rendered
        assert 'module.exports = config' in rendered
