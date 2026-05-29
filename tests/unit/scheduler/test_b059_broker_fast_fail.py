"""B-059: Celery broker fast-fail on dispatch.

When the broker (Redis) is unreachable, task dispatch must fail fast and raise a
typed BrokerUnavailableError instead of blocking on kombu reconnect. The publish
path uses retry=False and the broker transport carries bounded socket timeouts so
each connect attempt is capped.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from kombu.exceptions import OperationalError as KombuOperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from intellisource.observability.trace_context import reset_trace_id, set_trace_id


@pytest.fixture(autouse=True)
def _clear_trace_id():
    token = set_trace_id("")
    yield
    reset_trace_id(token)


class TestBrokerTransportTimeouts:
    """celery_app must bound broker connect/read so a dead broker can't hang."""

    def test_broker_transport_options_define_socket_timeouts(self) -> None:
        from intellisource.scheduler.celery_app import celery_app

        opts = celery_app.conf.broker_transport_options
        assert isinstance(opts, dict)
        for key in ("socket_connect_timeout", "socket_timeout"):
            assert key in opts, f"broker_transport_options missing {key!r}"
            assert isinstance(opts[key], (int, float))
            assert 0 < opts[key] <= 30, f"{key} must be a bounded positive timeout"

    def test_broker_connection_retry_on_startup_disabled(self) -> None:
        from intellisource.scheduler.celery_app import celery_app

        assert celery_app.conf.broker_connection_retry_on_startup is False

    def test_result_backend_fast_fail_configured(self) -> None:
        """The redis result store must also fast-fail (the dominant hang path)."""
        from intellisource.scheduler.celery_app import celery_app

        conf = celery_app.conf
        assert conf.result_backend_always_retry is False
        assert conf.result_backend_max_retries == 0
        assert isinstance(conf.redis_socket_connect_timeout, (int, float))
        assert 0 < conf.redis_socket_connect_timeout <= 30
        opts = conf.result_backend_transport_options
        assert isinstance(opts, dict)
        assert 0 < opts["socket_connect_timeout"] <= 30


class TestDispatchFastFail:
    """send_task_with_trace must fast-fail and wrap broker connection errors."""

    def test_publish_uses_retry_false(self) -> None:
        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.return_value = MagicMock()
            from intellisource.scheduler.dispatch import send_task_with_trace

            send_task_with_trace("run_pipeline")

        assert mock_celery.send_task.call_args.kwargs["retry"] is False

    def test_kombu_operational_error_wrapped(self) -> None:
        from intellisource.scheduler.dispatch import (
            BrokerUnavailableError,
            send_task_with_trace,
        )

        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.side_effect = KombuOperationalError("broker down")

            with pytest.raises(BrokerUnavailableError):
                send_task_with_trace("run_pipeline")

    def test_redis_connection_error_wrapped(self) -> None:
        from intellisource.scheduler.dispatch import (
            BrokerUnavailableError,
            send_task_with_trace,
        )

        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.side_effect = RedisConnectionError("refused")

            with pytest.raises(BrokerUnavailableError):
                send_task_with_trace("run_pipeline")

    def test_oserror_wrapped(self) -> None:
        from intellisource.scheduler.dispatch import (
            BrokerUnavailableError,
            send_task_with_trace,
        )

        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.side_effect = ConnectionRefusedError("no route")

            with pytest.raises(BrokerUnavailableError):
                send_task_with_trace("run_pipeline")

    def test_backend_reconnect_runtimeerror_wrapped(self) -> None:
        """Celery result-store reconnect exhaustion (bare RuntimeError) is wrapped."""
        from intellisource.scheduler.dispatch import (
            BrokerUnavailableError,
            send_task_with_trace,
        )

        msg = (
            "Retry limit exceeded while trying to reconnect to the Celery "
            "result store backend. The Celery application must be restarted."
        )
        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.side_effect = RuntimeError(msg)

            with pytest.raises(BrokerUnavailableError):
                send_task_with_trace("run_pipeline")

    def test_unrelated_runtimeerror_not_wrapped(self) -> None:
        """A RuntimeError unrelated to the backend must propagate unchanged."""
        from intellisource.scheduler.dispatch import (
            BrokerUnavailableError,
            send_task_with_trace,
        )

        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.side_effect = RuntimeError("something else broke")

            with pytest.raises(RuntimeError) as ei:
                send_task_with_trace("run_pipeline")
            assert not isinstance(ei.value, BrokerUnavailableError)

    def test_non_connection_error_not_wrapped(self) -> None:
        """A non-connection error (e.g. programming bug) must propagate as-is."""
        from intellisource.scheduler.dispatch import (
            BrokerUnavailableError,
            send_task_with_trace,
        )

        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.side_effect = ValueError("bad args")

            with pytest.raises(ValueError):
                send_task_with_trace("run_pipeline")
        assert not issubclass(ValueError, BrokerUnavailableError)

    def test_success_path_returns_async_result(self) -> None:
        mock_result = MagicMock(id="ok-123")
        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.return_value = mock_result
            from intellisource.scheduler.dispatch import send_task_with_trace

            assert send_task_with_trace("run_pipeline") is mock_result
