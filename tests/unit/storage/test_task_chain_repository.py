"""Tests for T-074: TaskChainRepository (AC-T074-1 through AC-T074-6).

Each test maps to a specific AC and is expected to FAIL (RED phase)
because TaskChainRepository does not exist yet.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from intellisource.storage.models import Base, TaskChain

# ---------------------------------------------------------------------------
# SQLite in-memory engine helpers (same pattern as test_repositories.py)
# ---------------------------------------------------------------------------

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _remove_pg_only_indexes(base: type) -> None:
    for table in base.metadata.tables.values():
        indexes_to_remove = []
        for idx in table.indexes:
            dialect_options = getattr(idx, "dialect_options", {})
            pg_opts = dialect_options.get("postgresql", {})
            if pg_opts.get("using") or pg_opts.get("ops"):
                indexes_to_remove.append(idx)
        for idx in indexes_to_remove:
            table.indexes.discard(idx)


def _set_sqlite_fk_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def engine():
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    _remove_pg_only_indexes(Base)

    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as sess:
        yield sess


def _make_task_chain(**overrides) -> TaskChain:
    defaults = dict(
        id=uuid.uuid4(),
        pipeline_name="test-pipeline",
        status="pending",
        trigger_type="manual",
        execution_mode="strict",
        total_steps=3,
        completed_steps=0,
    )
    defaults.update(overrides)
    return TaskChain(**defaults)


# ---------------------------------------------------------------------------
# AC-T074-1: create() persists a TaskChain and returns the same object
# ---------------------------------------------------------------------------


class TestTaskChainRepositoryCreate:
    """AC-T074-1: create(task_chain) persists to DB and returns same-ID object."""

    async def test_create_returns_task_chain_with_same_id(
        self, session: AsyncSession
    ) -> None:
        """create() must return a TaskChain whose id matches the input object."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        task_chain = _make_task_chain()
        original_id = task_chain.id

        result = await repo.create(task_chain)

        assert result.id == original_id

    async def test_create_persists_to_db_and_can_be_refetched(
        self, session: AsyncSession
    ) -> None:
        """After create(), the record must be retrievable from the DB session."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        task_chain = _make_task_chain(pipeline_name="persistence-check")

        await repo.create(task_chain)

        # Re-fetch directly via session to confirm DB write
        fetched = await session.get(TaskChain, task_chain.id)
        assert fetched is not None
        assert fetched.pipeline_name == "persistence-check"

    async def test_create_returns_task_chain_instance(
        self, session: AsyncSession
    ) -> None:
        """create() must return a TaskChain instance, not None or a raw dict."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        task_chain = _make_task_chain()

        result = await repo.create(task_chain)

        assert isinstance(result, TaskChain)


# ---------------------------------------------------------------------------
# AC-T074-2: get() returns TaskChain by ID or None if absent
# ---------------------------------------------------------------------------


class TestTaskChainRepositoryGet:
    """AC-T074-2: get(chain_id) returns full TaskChain or None."""

    async def test_get_returns_none_for_nonexistent_id(
        self, session: AsyncSession
    ) -> None:
        """get() must return None when no record matches chain_id."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        missing_id = str(uuid.uuid4())

        result = await repo.get(missing_id)

        assert result is None

    async def test_get_returns_task_chain_with_all_fields(
        self, session: AsyncSession
    ) -> None:
        """get() must return a TaskChain with all persisted field values intact."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        chain_id = uuid.uuid4()
        task_chain = _make_task_chain(
            id=chain_id,
            pipeline_name="full-field-check",
            trigger_type="scheduled",
            execution_mode="flexible",
            total_steps=5,
            completed_steps=2,
            status="running",
        )
        await repo.create(task_chain)

        result = await repo.get(str(chain_id))

        assert result is not None
        assert result.id == chain_id
        assert result.pipeline_name == "full-field-check"
        assert result.trigger_type == "scheduled"
        assert result.execution_mode == "flexible"
        assert result.total_steps == 5
        assert result.completed_steps == 2
        assert result.status == "running"

    async def test_get_accepts_string_id_and_converts_to_uuid(
        self, session: AsyncSession
    ) -> None:
        """get() must accept str chain_id and query by the UUID equivalent."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        chain_id = uuid.uuid4()
        task_chain = _make_task_chain(id=chain_id)
        await repo.create(task_chain)

        # Pass as string — must still find the record
        result = await repo.get(str(chain_id))

        assert result is not None
        assert result.id == chain_id


# ---------------------------------------------------------------------------
# AC-T074-3: update_status() updates status field; missing ID handled gracefully
# ---------------------------------------------------------------------------


class TestTaskChainRepositoryUpdateStatus:
    """AC-T074-3: update_status(chain_id, status) updates the status field."""

    async def test_update_status_changes_status_field(
        self, session: AsyncSession
    ) -> None:
        """update_status() must change the status of an existing TaskChain."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        chain_id = uuid.uuid4()
        task_chain = _make_task_chain(id=chain_id, status="pending")
        await repo.create(task_chain)

        await repo.update_status(str(chain_id), "running")

        result = await repo.get(str(chain_id))
        assert result is not None
        assert result.status == "running"

    async def test_update_status_nonexistent_id_does_not_raise(
        self, session: AsyncSession
    ) -> None:
        """update_status() on a missing chain_id must not raise nor mutate DB."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        # Create a real chain so we can verify it is not accidentally modified.
        existing_chain = _make_task_chain(status="pending")
        await repo.create(existing_chain)

        missing_id = str(uuid.uuid4())

        # Must complete without raising
        await repo.update_status(missing_id, "failed")

        # The missing id still returns None -- no phantom record created.
        assert await repo.get(missing_id) is None

        # The pre-existing chain is untouched.
        refetched = await repo.get(str(existing_chain.id))
        assert refetched is not None
        assert refetched.status == "pending"

    async def test_update_status_returns_none(self, session: AsyncSession) -> None:
        """update_status() return type must be None (fire-and-forget contract)."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(session)
        chain_id = uuid.uuid4()
        task_chain = _make_task_chain(id=chain_id)
        await repo.create(task_chain)

        result = await repo.update_status(str(chain_id), "success")

        assert result is None


# ---------------------------------------------------------------------------
# AC-T074-4: scheduler/tasks.py must not have module-level TaskChainRepository:Any=None
# ---------------------------------------------------------------------------


class TestSchedulerTasksNoAnyPlaceholder:
    """AC-T074-4: `TaskChainRepository: Any = None` removed from scheduler/tasks.py."""

    def test_tasks_module_has_no_taskchainrepository_any_placeholder(self) -> None:
        """scheduler/tasks.py must not expose TaskChainRepository as module-level Any=None."""  # noqa: E501
        import intellisource.scheduler.tasks as tasks_module

        # The module-level name must either not exist at all, or when it exists
        # it must NOT be None (meaning it has been replaced with a real import).
        if hasattr(tasks_module, "TaskChainRepository"):
            value = tasks_module.TaskChainRepository
            assert value is not None, (
                "TaskChainRepository in scheduler/tasks.py is still set to None — "
                "the Any=None placeholder must be removed (AC-T074-4)"
            )

    def test_tasks_module_source_contains_no_any_none_placeholder(self) -> None:
        """Source must not contain literal `TaskChainRepository: Any = None` line."""
        import inspect

        import intellisource.scheduler.tasks as tasks_module

        source = inspect.getsource(tasks_module)
        assert "TaskChainRepository: Any = None" not in source, (
            "scheduler/tasks.py still contains 'TaskChainRepository: Any = None' — "
            "this placeholder must be replaced with runtime DI (AC-T074-4)"
        )


# ---------------------------------------------------------------------------
# AC-T074-5: agent/runner.py _persist() must call TaskChainRepository, not UUID fallback
# ---------------------------------------------------------------------------


class TestAgentRunnerPersistCallsRepo:
    """AC-T074-5: _persist() must invoke TaskChainRepository.create(), not UUID stub."""

    def test_runner_persist_source_has_no_assumption_comment(self) -> None:
        """runner.py must not still contain the [ASSUMPTION] placeholder comment."""
        import inspect

        import intellisource.agent.runner as runner_module

        source = inspect.getsource(runner_module)
        assert "[ASSUMPTION] Generates a local UUID" not in source, (
            "runner.py still has the [ASSUMPTION] placeholder comment — "
            "it must be replaced with real TaskChainRepository write (AC-T074-5)"
        )

    async def test_runner_persist_calls_repo_create_when_provided(self) -> None:
        """When a repo is passed, _persist() must call repo.create() at least once."""
        from intellisource.agent.runner import AgentRunner

        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

        tool_registry = MagicMock()
        runner = AgentRunner(tool_registry=tool_registry, llm_gateway=None)

        # Inject the repo — the new contract requires _persist to accept/use it
        await runner._persist(
            status="success",
            steps_executed=1,
            results=[],
            pipeline_name="test-pipeline",
            repo=mock_repo,
        )

        mock_repo.create.assert_called_once()

    async def test_runner_persist_with_upstream_task_chain_id_uses_it(self) -> None:
        """When task_chain_id is provided, _persist must use that ID, not a new one."""
        from intellisource.agent.runner import AgentRunner

        upstream_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(return_value=MagicMock(id=uuid.UUID(upstream_id)))

        tool_registry = MagicMock()
        runner = AgentRunner(tool_registry=tool_registry, llm_gateway=None)

        result = await runner._persist(
            status="success",
            steps_executed=1,
            results=[],
            pipeline_name="test-pipeline",
            task_chain_id=upstream_id,
            repo=mock_repo,
        )

        assert result["task_chain_id"] == upstream_id


# ---------------------------------------------------------------------------
# AC-T074-6: TaskChainRepository is importable from storage.repositories
# ---------------------------------------------------------------------------


class TestTaskChainRepositoryExport:
    """AC-T074-6: TaskChainRepository exported from storage.repositories.__init__."""

    def test_task_chain_repository_importable_from_repositories_package(self) -> None:
        """TaskChainRepository importable via the repositories package __init__."""
        from intellisource.storage import repositories

        assert hasattr(repositories, "TaskChainRepository"), (
            "TaskChainRepository not exported from intellisource.storage.repositories "
            "add it to __init__.py (AC-T074-6)"
        )

    def test_task_chain_repository_in_all(self) -> None:
        """TaskChainRepository must appear in repositories.__all__."""
        from intellisource.storage import repositories

        assert "TaskChainRepository" in repositories.__all__, (
            "'TaskChainRepository' missing from repositories.__all__ (AC-T074-6)"
        )

    def test_task_chain_repository_is_class(self) -> None:
        """The exported TaskChainRepository must be a class, not None or a sentinel."""
        from intellisource.storage.repositories import TaskChainRepository

        assert isinstance(TaskChainRepository, type), (
            "TaskChainRepository is not a class — import is broken (AC-T074-6)"
        )
