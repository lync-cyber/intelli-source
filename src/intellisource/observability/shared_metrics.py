"""Cross-process metric store backed by a shared Redis hash.

The worker runs as a prefork pool: each child process owns a separate
:class:`~intellisource.observability.metrics.MetricsCollector` singleton that is
never served over HTTP. To let the API ``/api/v1/metrics`` endpoint surface
worker-recorded families (``celery_tasks_total`` etc.), worker signal handlers
write counters into a Redis hash that the API process reads back at scrape time.

All Redis access is defensive: a write failure is a logged no-op and a read
failure yields an empty exposition, so a Redis outage can never break task
execution or the metrics endpoint.

Storage layout (Redis hashes, ``decode_responses=True``):
- ``is:metrics:meta`` — field ``<name>`` -> JSON ``{"type", "description"}``
- ``is:metrics:data:<name>`` — field ``<label_key>`` -> stringified float, where
  ``<label_key>`` is ``"k=v,k2=v2"`` (sorted) or ``""`` for an unlabeled series.
"""

from __future__ import annotations

from typing import Any

from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_PREFIX = "is:metrics:"
_META_KEY = _PREFIX + "meta"

_SOCKET_TIMEOUT_SECONDS = 2


def _data_key(name: str) -> str:
    return f"{_PREFIX}data:{name}"


def _labels_to_key(labels: dict[str, str]) -> str:
    """Stable sorted ``k=v`` join; empty mapping -> single unlabeled series."""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


class RedisMetricStore:
    """A Redis-backed counter/gauge sink shared across processes.

    The ``client`` is any object exposing the sync redis hash API
    (``hset`` / ``hincrbyfloat`` / ``hgetall``); ``None`` makes every operation
    a no-op so callers need no separate "metrics disabled" branch.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # -- registration -------------------------------------------------------
    def register_counter(self, name: str, description: str = "") -> None:
        self._register(name, "counter", description)

    def register_gauge(self, name: str, description: str = "") -> None:
        self._register(name, "gauge", description)

    def _register(self, name: str, mtype: str, description: str) -> None:
        if self._client is None:
            return
        import json

        try:
            self._client.hset(
                _META_KEY,
                name,
                json.dumps({"type": mtype, "description": description}),
            )
        except Exception:  # noqa: BLE001 — metrics must never break callers
            logger.debug("shared metric register failed", metric=name)

    def seed_counter(self, name: str, description: str = "") -> None:
        """Register *name* and ensure its unlabeled series exists at 0.

        Lets a family appear on the scrape endpoint before its first increment
        without clobbering a value another process already recorded.
        """
        self.register_counter(name, description)
        if self._client is None:
            return
        try:
            existing = self._client.hgetall(_data_key(name))
            if "" not in existing:
                self._client.hset(_data_key(name), "", 0)
        except Exception:  # noqa: BLE001
            logger.debug("shared metric seed failed", metric=name)

    # -- recording ----------------------------------------------------------
    def increment_counter(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        amount: float = 1.0,
        description: str = "",
    ) -> None:
        if self._client is None:
            return
        try:
            self.register_counter(name, description)
            self._client.hincrbyfloat(
                _data_key(name), _labels_to_key(labels or {}), amount
            )
        except Exception:  # noqa: BLE001
            logger.debug("shared metric increment failed", metric=name)

    def set_gauge(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        value: float = 0.0,
        description: str = "",
    ) -> None:
        if self._client is None:
            return
        try:
            self.register_gauge(name, description)
            self._client.hset(_data_key(name), _labels_to_key(labels or {}), value)
        except Exception:  # noqa: BLE001
            logger.debug("shared metric set_gauge failed", metric=name)

    # -- reading ------------------------------------------------------------
    def read_all(self) -> list[dict[str, Any]]:
        """Return ``[{name, type, description, series: {label_key: float}}]``."""
        if self._client is None:
            return []
        import json

        try:
            meta = self._client.hgetall(_META_KEY)
        except Exception:  # noqa: BLE001
            logger.debug("shared metric read failed")
            return []

        entries: list[dict[str, Any]] = []
        for name, raw in meta.items():
            try:
                m = json.loads(raw)
            except (ValueError, TypeError):
                m = {"type": "counter", "description": ""}
            try:
                data = self._client.hgetall(_data_key(name))
            except Exception:  # noqa: BLE001
                data = {}
            series: dict[str, float] = {}
            for label_key, value in data.items():
                try:
                    series[label_key] = float(value)
                except (ValueError, TypeError):
                    continue
            entries.append(
                {
                    "name": name,
                    "type": m.get("type", "counter"),
                    "description": m.get("description", ""),
                    "series": series,
                }
            )
        return entries


def render_shared_metrics_text(entries: list[dict[str, Any]]) -> str:
    """Render shared-store entries as Prometheus exposition text.

    Output shape matches ``api.routers.system._format_prometheus`` so the API
    endpoint can concatenate local-collector text with shared-store text.
    """
    lines: list[str] = []
    for entry in entries:
        name = entry["name"]
        mtype = entry.get("type", "counter")
        desc = entry.get("description", "")
        series: dict[str, float] = entry.get("series", {})
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} {mtype}")
        for label_key in sorted(series):
            value = series[label_key]
            if label_key == "":
                lines.append(f"{name} {value}")
            else:
                label_str = ",".join(
                    f'{k}="{v}"'
                    for pair in label_key.split(",")
                    for k, v in [pair.split("=", 1)]
                )
                lines.append(f"{name}{{{label_str}}} {value}")
    return "\n".join(lines) + ("\n" if lines else "")


_store_singleton: RedisMetricStore | None = None


def _build_sync_redis_client() -> Any:
    """Build a sync redis client from settings, or ``None`` when unavailable."""
    try:
        from intellisource.core.settings import get_settings

        url = get_settings().redis_url
        if not url:
            return None
        import redis

        return redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 — degrade to a no-op store
        logger.warning("shared metric store: redis client unavailable")
        return None


def get_shared_metric_store() -> RedisMetricStore:
    """Return the process-wide shared metric store (lazy singleton)."""
    global _store_singleton
    if _store_singleton is None:
        _store_singleton = RedisMetricStore(_build_sync_redis_client())
    return _store_singleton
