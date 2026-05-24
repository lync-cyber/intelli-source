"""Tests for SchedulerStateBackend implementations (F-36)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from intellisource.scheduler.state_machine import (
    InMemoryStateBackend,
    RedisStateBackend,
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


class TestRedisStateBackend:
    @pytest.fixture()
    def redis_mock(self) -> MagicMock:
        return MagicMock()

    def test_set_serialises_to_json(self, redis_mock: MagicMock) -> None:
        backend = RedisStateBackend(redis_mock)
        entry = {"name": "s1", "cron_expr": "0 * * * *"}
        backend.set("s1", entry)
        redis_mock.set.assert_called_once_with("scheduler:state:s1", json.dumps(entry))

    def test_get_deserialises_from_json(self, redis_mock: MagicMock) -> None:
        entry = {"name": "s1", "cron_expr": "0 * * * *"}
        redis_mock.get.return_value = json.dumps(entry)
        backend = RedisStateBackend(redis_mock)
        result = backend.get("s1")
        redis_mock.get.assert_called_once_with("scheduler:state:s1")
        assert result == entry

    def test_get_missing_returns_none(self, redis_mock: MagicMock) -> None:
        redis_mock.get.return_value = None
        backend = RedisStateBackend(redis_mock)
        assert backend.get("nonexistent") is None

    def test_delete_calls_redis_delete(self, redis_mock: MagicMock) -> None:
        redis_mock.delete.return_value = 1
        backend = RedisStateBackend(redis_mock)
        backend.delete("s1")
        redis_mock.delete.assert_called_once_with("scheduler:state:s1")

    def test_delete_missing_raises_key_error(self, redis_mock: MagicMock) -> None:
        redis_mock.delete.return_value = 0
        backend = RedisStateBackend(redis_mock)
        with pytest.raises(KeyError):
            backend.delete("nonexistent")

    def test_exists_uses_correct_key(self, redis_mock: MagicMock) -> None:
        redis_mock.exists.return_value = 1
        backend = RedisStateBackend(redis_mock)
        assert backend.exists("s1") is True
        redis_mock.exists.assert_called_once_with("scheduler:state:s1")

    def test_all_deserialises_mget_results(self, redis_mock: MagicMock) -> None:
        entries = [{"name": "a"}, {"name": "b"}]
        redis_mock.keys.return_value = [b"scheduler:state:a", b"scheduler:state:b"]
        redis_mock.mget.return_value = [json.dumps(e) for e in entries]
        backend = RedisStateBackend(redis_mock)
        result = backend.all()
        assert {e["name"] for e in result} == {"a", "b"}

    def test_all_empty_when_no_keys(self, redis_mock: MagicMock) -> None:
        redis_mock.keys.return_value = []
        backend = RedisStateBackend(redis_mock)
        assert backend.all() == []

    def test_key_prefix(self, redis_mock: MagicMock) -> None:
        backend = RedisStateBackend(redis_mock)
        assert backend._KEY_PREFIX == "scheduler:state:"


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

    def test_remove_schedule_calls_backend_delete(self) -> None:
        backend = MagicMock(spec=SchedulerStateBackend)
        backend.exists.return_value = False
        mgr = SchedulerManager(backend=backend)
        mgr.register_schedule("s1", "* * * * *", "pipeline_a", {})
        mgr.remove_schedule("s1")
        backend.delete.assert_called_once_with("s1")

    def test_duplicate_register_raises(self) -> None:
        mgr = SchedulerManager()
        mgr.register_schedule("s1", "* * * * *", "pipeline_a", {})
        with pytest.raises(ValueError, match="already exists"):
            mgr.register_schedule("s1", "0 * * * *", "pipeline_b", {})

    def test_redis_backend_injected(self) -> None:
        redis_mock = MagicMock()
        backend = RedisStateBackend(redis_mock)
        mgr = SchedulerManager(backend=backend)
        assert isinstance(mgr._backend, RedisStateBackend)
