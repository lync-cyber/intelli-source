"""Tests for SchedulerStateBackend implementations (F-36)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from intellisource.scheduler.state_machine import (
    InMemoryStateBackend,
    SchedulerManager,
    SchedulerStateBackend,
)


class TestInMemoryStateBackend:
    def test_set_and_get(self) -> None:
        backend = InMemoryStateBackend()
        backend.set("s1", {"name": "s1", "cron_expr": "* * * * *"})
        result = backend.get("s1")
        assert result is not None
        assert result["name"] == "s1"

    def test_get_missing_returns_none(self) -> None:
        backend = InMemoryStateBackend()
        assert backend.get("nonexistent") is None

    def test_delete_removes_entry(self) -> None:
        backend = InMemoryStateBackend()
        backend.set("s1", {"name": "s1"})
        backend.delete("s1")
        assert backend.get("s1") is None

    def test_delete_missing_raises_key_error(self) -> None:
        backend = InMemoryStateBackend()
        with pytest.raises(KeyError):
            backend.delete("nonexistent")

    def test_all_returns_all_entries(self) -> None:
        backend = InMemoryStateBackend()
        backend.set("a", {"name": "a"})
        backend.set("b", {"name": "b"})
        names = {entry["name"] for entry in backend.all()}
        assert names == {"a", "b"}

    def test_exists(self) -> None:
        backend = InMemoryStateBackend()
        assert not backend.exists("x")
        backend.set("x", {"name": "x"})
        assert backend.exists("x")

    def test_is_subclass_of_abstract(self) -> None:
        assert issubclass(InMemoryStateBackend, SchedulerStateBackend)


class TestSchedulerManagerWithBackend:
    def test_default_backend_is_in_memory(self) -> None:
        mgr = SchedulerManager()
        assert isinstance(mgr._backend, InMemoryStateBackend)

    def test_register_schedule_calls_backend_set(self) -> None:
        backend = MagicMock(spec=SchedulerStateBackend)
        backend.exists.return_value = False
        mgr = SchedulerManager(backend=backend)
        mgr.register_schedule("s1", "* * * * *", "pipeline_a", {})
        backend.set.assert_called_once()
        call_args = backend.set.call_args
        assert call_args[0][0] == "s1"
        assert call_args[0][1]["name"] == "s1"

    def test_duplicate_register_raises(self) -> None:
        mgr = SchedulerManager()
        mgr.register_schedule("s1", "* * * * *", "pipeline_a", {})
        with pytest.raises(ValueError, match="already exists"):
            mgr.register_schedule("s1", "0 * * * *", "pipeline_b", {})
