"""TaskChainRepository -- data access for TaskChain entities."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update

from intellisource.storage.models import TaskChain
from intellisource.storage.repositories.base import BaseRepository


class TaskChainRepository(BaseRepository[TaskChain]):
    """CRUD for :class:`TaskChain` entities."""

    _model_class = TaskChain

    async def create(
        self,
        task_chain: TaskChain | None = None,
        **kwargs: Any,
    ) -> TaskChain:
        """Persist a TaskChain.

        Callers in higher layers (api/routers) pass scalar kwargs so they do
        not need to import the ORM class — lint-imports keeps
        api.routers off storage.models. Internal callers (agent.runner,
        tests/unit/storage) can still pass a pre-built TaskChain instance.
        """
        if task_chain is None:
            task_chain = TaskChain(**kwargs)
        self._session.add(task_chain)
        await self._session.flush()
        await self._session.refresh(task_chain)
        return task_chain

    async def get(self, chain_id: str) -> TaskChain | None:
        """Return a TaskChain by string ID, or None if not found."""
        try:
            uid = uuid.UUID(chain_id)
        except ValueError:
            return None
        return await self._session.get(TaskChain, uid)

    async def update_status(
        self, chain_id: str, status: str, completed_steps: int | None = None
    ) -> None:
        """Update a TaskChain's status; silently no-ops if not found.

        ``completed_steps`` advances the progress counter in the same write —
        the terminal transition passes ``total_steps`` so a finished chain reads
        ``N/N`` instead of the ``0/N`` it carried from creation through to the
        run-level success/failure write.
        """
        try:
            uid = uuid.UUID(chain_id)
        except ValueError:
            return
        values: dict[str, Any] = {"status": status}
        if completed_steps is not None:
            values["completed_steps"] = completed_steps
        stmt = update(TaskChain).where(TaskChain.id == uid).values(**values)
        await self._session.execute(stmt)
