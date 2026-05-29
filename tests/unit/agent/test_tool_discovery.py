"""Tests for AgentToolRegistry.auto_discover (T-066).

Covers:
- AC-T066-1: auto_discover() scans the tools/ directory.
- AC-T066-2: plugin files must export `TOOL_DEFINITION: ToolDefinition`.
- AC-T066-3: discovered tools merge into the same `list_tools()` namespace.
- AC-T066-4: manual register() wins over auto_discover when names collide.
- AC-T066-5: import errors / malformed plugins are logged but do not abort
             discovery or startup.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from intellisource.agent.tools import (
    AgentToolRegistry,
    PermissionLevel,
)


def _write_plugin(plugin_dir: Path, filename: str, body: str) -> Path:
    """Materialise a fixture plugin .py file under plugin_dir."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    path = plugin_dir / filename
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _valid_plugin_source(tool_name: str) -> str:
    return f'''
        from intellisource.agent.tools import ToolDefinition

        async def _execute(**kwargs):
            return {{"status": "ok", "tool": "{tool_name}"}}

        TOOL_DEFINITION = ToolDefinition(
            name="{tool_name}",
            description="discovered tool {tool_name}",
            parameters={{"type": "object", "properties": {{}}}},
            execute=_execute,
        )
    '''


# ---------------------------------------------------------------- AC-T066-1


class TestAutoDiscoverScansDir:
    def test_discovers_plugin_in_directory(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha.py", _valid_plugin_source("alpha"))

        registry = AgentToolRegistry()
        registry.auto_discover(str(tmp_path))

        assert "alpha" in registry.list_tools()

    def test_skips_dunder_prefixed_files(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "__init__.py", "")
        _write_plugin(tmp_path, "_private.py", _valid_plugin_source("private"))
        _write_plugin(tmp_path, "real.py", _valid_plugin_source("real"))

        registry = AgentToolRegistry()
        registry.auto_discover(str(tmp_path))

        listed = registry.list_tools()
        assert "real" in listed
        assert "private" not in listed

    def test_missing_dir_logs_warning_and_returns(self, tmp_path: Path) -> None:
        from structlog.testing import capture_logs

        missing = tmp_path / "does-not-exist"

        registry = AgentToolRegistry()
        with capture_logs() as logs:
            registry.auto_discover(str(missing))

        assert registry.list_tools() == []
        assert any("does not exist" in e["event"] for e in logs)


# ---------------------------------------------------------------- AC-T066-2


class TestToolDefinitionConstant:
    def test_plugin_without_tool_definition_is_silently_ignored(
        self, tmp_path: Path
    ) -> None:
        _write_plugin(
            tmp_path,
            "no_constant.py",
            """
            def _execute(**kwargs):
                return {}
            """,
        )

        registry = AgentToolRegistry()
        registry.auto_discover(str(tmp_path))

        assert registry.list_tools() == []

    def test_plugin_with_wrong_type_constant_is_warned_and_skipped(
        self, tmp_path: Path
    ) -> None:
        from structlog.testing import capture_logs

        _write_plugin(
            tmp_path,
            "bad_type.py",
            """
            TOOL_DEFINITION = "this is not a ToolDefinition"
            """,
        )

        registry = AgentToolRegistry()
        with capture_logs() as logs:
            registry.auto_discover(str(tmp_path))

        assert registry.list_tools() == []
        assert any("not a ToolDefinition" in e["event"] for e in logs)


# ---------------------------------------------------------------- AC-T066-3


class TestUnifiedListTools:
    def test_discovered_and_registered_tools_in_same_namespace(
        self, tmp_path: Path
    ) -> None:
        _write_plugin(tmp_path, "discovered.py", _valid_plugin_source("discovered"))

        async def _manual_exec(**kwargs: object) -> dict[str, object]:
            return {"status": "ok"}

        registry = AgentToolRegistry()
        registry.register(
            name="manual",
            description="manually registered",
            parameters={"type": "object", "properties": {}},
            execute_fn=_manual_exec,
        )
        registry.auto_discover(str(tmp_path))

        listed = set(registry.list_tools())
        assert {"manual", "discovered"}.issubset(listed)
        assert registry.get("discovered").name == "discovered"
        assert registry.get("manual").name == "manual"

    def test_discovered_tool_preserves_permission_level(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "sensitive.py",
            """
            from intellisource.agent.tools import PermissionLevel, ToolDefinition

            async def _execute(**kwargs):
                return {}

            TOOL_DEFINITION = ToolDefinition(
                name="sensitive",
                description="needs confirmation",
                parameters={"type": "object", "properties": {}},
                execute=_execute,
                permission_level=PermissionLevel.confirm,
            )
            """,
        )

        registry = AgentToolRegistry()
        registry.auto_discover(str(tmp_path))

        defn = registry.get("sensitive")
        assert defn is not None
        assert defn.permission_level == PermissionLevel.confirm


# ---------------------------------------------------------------- AC-T066-4


class TestManualRegistrationWins:
    def test_manual_register_takes_precedence_over_discovery(
        self, tmp_path: Path
    ) -> None:
        _write_plugin(tmp_path, "shared.py", _valid_plugin_source("shared"))

        async def _manual_exec(**kwargs: object) -> dict[str, object]:
            return {"origin": "manual"}

        registry = AgentToolRegistry()
        registry.register(
            name="shared",
            description="manual-shared",
            parameters={"type": "object", "properties": {}},
            execute_fn=_manual_exec,
        )
        registry.auto_discover(str(tmp_path))

        defn = registry.get("shared")
        assert defn is not None
        assert defn.description == "manual-shared"


# ---------------------------------------------------------------- AC-T066-5


class TestImportErrorTolerance:
    def test_import_error_in_one_plugin_does_not_abort_discovery(
        self, tmp_path: Path
    ) -> None:
        from structlog.testing import capture_logs

        _write_plugin(
            tmp_path,
            "broken.py",
            """
            raise RuntimeError("intentional plugin import failure")
            """,
        )
        _write_plugin(tmp_path, "healthy.py", _valid_plugin_source("healthy"))

        registry = AgentToolRegistry()
        with capture_logs() as logs:
            registry.auto_discover(str(tmp_path))

        assert "healthy" in registry.list_tools()
        assert any(
            "import failed" in e["event"] and "broken.py" in e["event"] for e in logs
        )

    def test_syntax_error_in_plugin_is_caught(self, tmp_path: Path) -> None:
        from structlog.testing import capture_logs

        _write_plugin(
            tmp_path,
            "syntaxbad.py",
            """
            def broken(
            """,
        )

        registry = AgentToolRegistry()
        with capture_logs() as logs:
            registry.auto_discover(str(tmp_path))

        assert registry.list_tools() == []
        assert any("import failed" in e["event"] for e in logs)


# ---------------------------------------------------------------- AC-T066-6 (mypy)
# Type contracts are enforced by mypy --strict; runtime smoke covered above.
