"""Loader for the packaged built-in topic catalog (``topic/builtin/*.yaml``)."""

from __future__ import annotations

from pathlib import Path

import yaml

from intellisource.observability.logging import get_logger
from intellisource.topic.models import Topic

logger = get_logger(__name__)

_BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"


class TopicLoader:
    """Reads and validates topic-pack YAML files shipped with the package."""

    def __init__(self, builtin_dir: Path | None = None) -> None:
        self._dir = builtin_dir if builtin_dir is not None else _BUILTIN_DIR

    def load_all(self) -> list[Topic]:
        """Return every valid topic pack, sorted by id. Bad files are skipped."""
        topics: dict[str, Topic] = {}
        if not self._dir.is_dir():
            logger.warning("topic builtin dir %s missing; no topics loaded", self._dir)
            return []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                topic = Topic.model_validate(data)
            except Exception:
                logger.exception("failed to load topic pack %s", path)
                continue
            if topic.id in topics:
                logger.warning(
                    "duplicate topic id %r in %s; keeping first", topic.id, path
                )
                continue
            topics[topic.id] = topic
        return sorted(topics.values(), key=lambda t: t.id)

    def load_by_id(self, topic_id: str) -> Topic | None:
        """Return the topic with the given id, or None when absent."""
        for topic in self.load_all():
            if topic.id == topic_id:
                return topic
        return None
