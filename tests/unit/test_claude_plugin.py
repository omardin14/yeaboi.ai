"""Validation tests for the bundled Claude Code plugin (claude-plugin/)."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE_DIR = REPO_ROOT / "claude-plugin"
PLUGIN_DIR = MARKETPLACE_DIR / "yeaboi"

EXPECTED_SKILLS = {"plan-sprint", "standup", "delivery-report"}


def _frontmatter(text: str) -> dict:
    """Parse the simple key: value YAML frontmatter of a SKILL.md."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with --- frontmatter ---"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if _:
            fields[key.strip()] = value.strip().strip('"')
    return fields


class TestMarketplace:
    def test_marketplace_json(self):
        data = json.loads((MARKETPLACE_DIR / ".claude-plugin" / "marketplace.json").read_text())
        assert data["name"] == "yeaboi"
        assert data["owner"]["name"]
        [plugin] = data["plugins"]
        assert plugin["name"] == "yeaboi"
        # source must point at the plugin dir, relative to the marketplace root
        assert (MARKETPLACE_DIR / plugin["source"]).resolve() == PLUGIN_DIR.resolve()


class TestPluginManifest:
    def test_plugin_json(self):
        data = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
        assert data["name"] == "yeaboi"
        assert data["description"]
        # Version deliberately omitted — commit-SHA versioning means updates
        # ship without a second version number to maintain.
        assert "version" not in data

    def test_mcp_json_at_plugin_root(self):
        # .mcp.json must live at the plugin root, NOT inside .claude-plugin/
        # (a documented common mistake).
        path = PLUGIN_DIR / ".mcp.json"
        assert path.exists()
        assert not (PLUGIN_DIR / ".claude-plugin" / ".mcp.json").exists()
        data = json.loads(path.read_text())
        server = data["mcpServers"]["yeaboi"]
        assert server["command"] == "uvx"
        assert server["args"] == ["--from", "yeaboi[mcp]", "yeaboi-mcp"]


class TestSkills:
    def test_expected_skills_present(self):
        found = {p.parent.name for p in PLUGIN_DIR.glob("skills/*/SKILL.md")}
        assert found == EXPECTED_SKILLS

    def test_skill_frontmatter(self):
        for skill_md in PLUGIN_DIR.glob("skills/*/SKILL.md"):
            fields = _frontmatter(skill_md.read_text())
            assert fields.get("name") == skill_md.parent.name
            assert len(fields.get("description", "")) > 20, f"{skill_md}: description too thin"

    def test_skills_reference_real_tools(self):
        # Every `tool_name` a skill tells the agent to call must exist on the server.
        import anyio
        import pytest

        pytest.importorskip("mcp", reason="mcp extra not installed")
        from yeaboi.mcp.server import create_app

        app = create_app()
        server_tools = {tool.name for tool in anyio.run(app.list_tools)}

        referenced: set[str] = set()
        for skill_md in PLUGIN_DIR.glob("skills/*/SKILL.md"):
            body = skill_md.read_text()
            for name in re.findall(r"`([a-z][a-z0-9_]+)`", body):
                if name in server_tools or name.endswith(("_run", "_generate", "_history", "_report")):
                    referenced.add(name)
        assert referenced, "skills should reference at least some tools"
        unknown = referenced - server_tools
        assert not unknown, f"skills reference tools the server doesn't expose: {unknown}"

    def test_readme_present(self):
        assert (PLUGIN_DIR / "README.md").read_text().startswith("# yeaboi")
