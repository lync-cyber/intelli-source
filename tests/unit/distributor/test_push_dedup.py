"""Tests for BaseDistributor dedup hooks and per-channel PushRecord integration.

Covers AC-1 through AC-7 of T-090.
"""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_SRC_DIR = str(
    Path(__file__).parent.parent.parent.parent / "src" / "intellisource" / "distributor"
)


class _FakeContent:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.title = "Test Title"
        self.body_text = "Test body"
        self.summary = "Test summary"
        self.body = "Test body"
        self.url = "https://example.com"
        self.source_url = "https://example.com"


class _FakeSubscription:
    def __init__(self, channel_config: dict[str, Any] | None = None) -> None:
        self.id = uuid.uuid4()
        self.channel_config = channel_config or {}


def _make_push_repo(*, exists_return: bool = False) -> MagicMock:
    """Return a mock PushRepository with async exists() and create()."""
    repo = MagicMock()
    repo.exists = AsyncMock(return_value=exists_return)
    repo.create = AsyncMock(return_value=MagicMock())
    return repo


def _make_concrete_distributor() -> Any:
    """Return a minimal concrete BaseDistributor subclass instance."""
    from intellisource.distributor.base import BaseDistributor

    class _Concrete(BaseDistributor):
        async def distribute(self, content: Any, subscription: Any) -> Any:  # type: ignore[override]
            return {}

    return _Concrete()


# ---------------------------------------------------------------------------
# AC-1: BaseDistributor hook surface
# ---------------------------------------------------------------------------


class TestAC1:
    """check_dedup() and record_push() exist on BaseDistributor and delegate."""

    def test_check_dedup_method_exists(self) -> None:
        from intellisource.distributor.base import BaseDistributor

        assert hasattr(BaseDistributor, "check_dedup"), (
            "BaseDistributor must have check_dedup method"
        )

    def test_record_push_method_exists(self) -> None:
        from intellisource.distributor.base import BaseDistributor

        assert hasattr(BaseDistributor, "record_push"), (
            "BaseDistributor must have record_push method"
        )

    @pytest.mark.asyncio
    async def test_check_dedup_delegates_to_repo_exists(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        channel = "wechat"
        repo = _make_push_repo(exists_return=False)

        distributor = _make_concrete_distributor()
        result = await distributor.check_dedup(sub_id, content_id, channel, repo=repo)

        repo.exists.assert_awaited_once_with(sub_id, content_id, channel)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_dedup_delegates_to_repo_exists_true(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        channel = "wechat"
        repo = _make_push_repo(exists_return=True)

        distributor = _make_concrete_distributor()
        result = await distributor.check_dedup(sub_id, content_id, channel, repo=repo)

        repo.exists.assert_awaited_once_with(sub_id, content_id, channel)
        assert result is True

    @pytest.mark.asyncio
    async def test_record_push_delegates_to_repo_create(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        channel = "wechat"
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            channel,
            status="success",
            repo=repo,
        )

        repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_push_passes_status_to_create(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        channel = "wechat"
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            channel,
            status="failed",
            retry_count=2,
            error_message="timeout error",
            repo=repo,
        )

        repo.create.assert_awaited_once()
        _, kwargs = repo.create.call_args
        assert (
            kwargs.get("status") == "failed"
            or repo.create.await_args[1].get("status") == "failed"
        )

    @pytest.mark.asyncio
    async def test_record_push_passes_correct_ids_to_create(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        channel = "email"
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            channel,
            status="success",
            repo=repo,
        )

        repo.create.assert_awaited_once()
        # Verify subscription_id and content_id are passed to create
        create_args = repo.create.await_args
        assert create_args is not None
        # check positional or keyword args contain the IDs
        all_args = list(create_args.args) + list(create_args.kwargs.values())
        assert sub_id in all_args or create_args.kwargs.get("subscription_id") == sub_id


# ---------------------------------------------------------------------------
# AC-2: WeChatDistributor calls check_dedup + record_push
# ---------------------------------------------------------------------------


class TestAC2:
    """WeChatDistributor integrates check_dedup and record_push hooks."""

    def _make_wechat(self, repo: MagicMock) -> Any:
        from intellisource.distributor.channels.wechat import WeChatDistributor

        redis = MagicMock()
        redis.get = AsyncMock(return_value="fake_token")
        redis.set = AsyncMock()
        redis.exists = AsyncMock(return_value=False)
        http = MagicMock()
        http.post = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": "1"}
            )
        )
        http.get = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"access_token": "tok", "expires_in": 7200}
            )
        )
        dist = WeChatDistributor(
            redis=redis,
            http_client=http,
            app_id="app123",
            app_secret="secret",
            push_repo=repo,
        )
        return dist

    @pytest.mark.asyncio
    async def test_wechat_skips_send_when_dedup_returns_true(self) -> None:
        repo = _make_push_repo(exists_return=True)
        dist = self._make_wechat(repo)
        content = _FakeContent()
        sub = _FakeSubscription(
            {"openid": "openid_abc", "msg_type": "template", "template_id": "tpl1"}
        )

        result = await dist.distribute(content, sub)

        assert result["status"] in ("skipped", "duplicate", "deduplicated")
        repo.exists.assert_awaited_once()
        repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wechat_calls_record_push_success_after_send(self) -> None:
        repo = _make_push_repo(exists_return=False)
        dist = self._make_wechat(repo)
        content = _FakeContent()
        sub = _FakeSubscription(
            {"openid": "openid_abc", "msg_type": "template", "template_id": "tpl1"}
        )

        result = await dist.distribute(content, sub)

        assert result["status"] == "success"
        repo.exists.assert_awaited_once()
        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "success"

    @pytest.mark.asyncio
    async def test_wechat_calls_record_push_failed_on_exception(self) -> None:
        repo = _make_push_repo(exists_return=False)

        from intellisource.distributor.channels.wechat import WeChatDistributor

        redis = MagicMock()
        redis.get = AsyncMock(return_value="fake_token")
        redis.set = AsyncMock()
        redis.exists = AsyncMock(return_value=False)
        http = MagicMock()
        http.post = AsyncMock(side_effect=RuntimeError("network error"))
        http.get = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"access_token": "tok", "expires_in": 7200}
            )
        )
        dist = WeChatDistributor(
            redis=redis,
            http_client=http,
            app_id="app123",
            app_secret="secret",
            push_repo=repo,
        )
        content = _FakeContent()
        sub = _FakeSubscription(
            {"openid": "openid_abc", "msg_type": "template", "template_id": "tpl1"}
        )

        result = await dist.distribute(content, sub)

        assert result["status"] == "failed"
        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "failed"
        assert (
            create_kwargs.get("error_message") is not None
            and create_kwargs["error_message"] != ""
        )

    @pytest.mark.asyncio
    async def test_wechat_repo_exists_and_create_each_called_once(self) -> None:
        repo = _make_push_repo(exists_return=False)
        dist = self._make_wechat(repo)
        content = _FakeContent()
        sub = _FakeSubscription(
            {"openid": "openid_abc", "msg_type": "template", "template_id": "tpl1"}
        )

        await dist.distribute(content, sub)

        repo.exists.assert_awaited_once()
        repo.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# AC-3: WeWorkDistributor + grep for push:dedup patterns removed
# ---------------------------------------------------------------------------


class TestAC3:
    """WeWorkDistributor uses check_dedup/record_push; no legacy redis dedup."""

    def _make_wework(self, repo: MagicMock) -> Any:
        from intellisource.distributor.channels.wework import WeWorkDistributor

        redis = MagicMock()
        redis.get = AsyncMock(return_value="fake_token")
        redis.set = AsyncMock()
        redis.expire = AsyncMock()
        redis.exists = AsyncMock(return_value=False)
        http = MagicMock()
        http.post = AsyncMock(
            return_value=MagicMock(json=lambda: {"errcode": 0, "errmsg": "ok"})
        )
        http.get = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"errcode": 0, "access_token": "tok", "expires_in": 7200}
            )
        )
        dist = WeWorkDistributor(
            redis=redis,
            http_client=http,
            corp_id="corp1",
            corp_secret="secret",
            agent_id=1,
            push_repo=repo,
        )
        return dist

    @pytest.mark.asyncio
    async def test_wework_skips_send_when_dedup_returns_true(self) -> None:
        repo = _make_push_repo(exists_return=True)
        dist = self._make_wework(repo)
        content = _FakeContent()
        sub = _FakeSubscription({"user_id": "user1", "msg_type": "text"})

        result = await dist.distribute(content, sub)

        assert result["status"] in ("duplicate", "skipped", "deduplicated")
        repo.exists.assert_awaited_once()
        repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wework_calls_record_push_success(self) -> None:
        repo = _make_push_repo(exists_return=False)
        dist = self._make_wework(repo)
        content = _FakeContent()
        sub = _FakeSubscription({"user_id": "user1", "msg_type": "text"})

        result = await dist.distribute(content, sub)

        assert result["status"] == "success"
        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "success"

    @pytest.mark.asyncio
    async def test_wework_calls_record_push_failed(self) -> None:
        repo = _make_push_repo(exists_return=False)

        from intellisource.distributor.channels.wework import WeWorkDistributor

        redis = MagicMock()
        redis.get = AsyncMock(return_value="fake_token")
        redis.set = AsyncMock()
        redis.expire = AsyncMock()
        http = MagicMock()
        http.post = AsyncMock(
            return_value=MagicMock(json=lambda: {"errcode": -1, "errmsg": "fail"})
        )
        http.get = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"errcode": 0, "access_token": "tok", "expires_in": 7200}
            )
        )
        dist = WeWorkDistributor(
            redis=redis,
            http_client=http,
            corp_id="corp1",
            corp_secret="secret",
            agent_id=1,
            push_repo=repo,
        )
        content = _FakeContent()
        sub = _FakeSubscription({"user_id": "user1", "msg_type": "text"})

        result = await dist.distribute(content, sub)

        assert result["status"] == "failed"
        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "failed"

    def test_no_push_dedup_redis_key_pattern_in_source(self) -> None:
        """Source code must not contain legacy 'push:dedup:' redis key patterns."""
        proc = subprocess.run(
            ["grep", "-rn", "push:dedup:", _SRC_DIR],
            capture_output=True,
            text=True,
        )
        assert proc.stdout == "", (
            f"Legacy 'push:dedup:' Redis key pattern found in source:\n{proc.stdout}"
        )

    def test_no_wework_dedup_redis_key_pattern_in_source(self) -> None:
        """Source code must not contain legacy 'wework:dedup:' redis key patterns."""
        proc = subprocess.run(
            ["grep", "-rn", "wework:dedup:", _SRC_DIR],
            capture_output=True,
            text=True,
        )
        assert proc.stdout == "", (
            f"Legacy 'wework:dedup:' Redis key pattern found in source:\n{proc.stdout}"
        )


# ---------------------------------------------------------------------------
# AC-4: EmailDistributor + grep for _sent_keys removed
# ---------------------------------------------------------------------------


class TestAC4:
    """EmailDistributor uses check_dedup/record_push; no _sent_keys set."""

    def _make_email(self, repo: MagicMock) -> Any:
        from intellisource.distributor.channels.email import EmailDistributor

        dist = EmailDistributor(
            smtp_host="localhost",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="pass",
            use_tls=False,
            push_repo=repo,
        )
        return dist

    @pytest.mark.asyncio
    async def test_email_skips_send_when_dedup_returns_true(self) -> None:
        repo = _make_push_repo(exists_return=True)
        dist = self._make_email(repo)
        content = _FakeContent()
        sub = _FakeSubscription({"to_addr": "recipient@example.com"})

        result = await dist.distribute(content, sub)

        assert result["status"] in ("deduplicated", "skipped", "duplicate")
        repo.exists.assert_awaited_once()
        repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_email_calls_record_push_success(self) -> None:
        repo = _make_push_repo(exists_return=False)
        dist = self._make_email(repo)
        content = _FakeContent()
        sub = _FakeSubscription({"to_addr": "recipient@example.com"})

        with patch(
            "intellisource.distributor.channels.email.aiosmtplib.send",
            new_callable=AsyncMock,
        ):
            result = await dist.distribute(content, sub)

        assert result["status"] in ("sent", "success")
        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") in ("sent", "success")

    @pytest.mark.asyncio
    async def test_email_calls_record_push_failed(self) -> None:
        repo = _make_push_repo(exists_return=False)
        dist = self._make_email(repo)
        content = _FakeContent()
        sub = _FakeSubscription({"to_addr": "recipient@example.com"})

        with patch(
            "intellisource.distributor.channels.email.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=OSError("SMTP connection refused"),
        ):
            result = await dist.distribute(content, sub)

        assert result["status"] == "failed"
        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "failed"

    def test_no_sent_keys_attribute_in_email_source(self) -> None:
        """EmailDistributor source must not use _sent_keys in-process set."""
        proc = subprocess.run(
            ["grep", "-rn", "_sent_keys", _SRC_DIR],
            capture_output=True,
            text=True,
        )
        assert proc.stdout == "", (
            f"Legacy '_sent_keys' in-process set found in source:\n{proc.stdout}"
        )


# ---------------------------------------------------------------------------
# AC-5: Failed-send path records retry_count >= 1 and non-empty error_message
# ---------------------------------------------------------------------------


class TestAC5:
    """record_push() called with retry_count>=1 + error_message on failure."""

    @pytest.mark.asyncio
    async def test_failed_wechat_send_records_retry_count_and_error(self) -> None:
        repo = _make_push_repo(exists_return=False)

        from intellisource.distributor.channels.wechat import WeChatDistributor

        redis = MagicMock()
        redis.get = AsyncMock(return_value="fake_token")
        redis.set = AsyncMock()
        http = MagicMock()
        http.post = AsyncMock(side_effect=RuntimeError("network timeout"))
        http.get = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"access_token": "tok", "expires_in": 7200}
            )
        )
        dist = WeChatDistributor(
            redis=redis,
            http_client=http,
            app_id="app123",
            app_secret="secret",
            push_repo=repo,
        )
        content = _FakeContent()
        sub = _FakeSubscription(
            {"openid": "openid_abc", "msg_type": "template", "template_id": "tpl1"}
        )

        await dist.distribute(content, sub)

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("retry_count", 0) >= 1
        error_msg = create_kwargs.get("error_message")
        assert error_msg is not None and error_msg != ""

    @pytest.mark.asyncio
    async def test_failed_wework_send_records_retry_count_and_error(self) -> None:
        repo = _make_push_repo(exists_return=False)

        from intellisource.distributor.channels.wework import WeWorkDistributor

        redis = MagicMock()
        redis.get = AsyncMock(return_value="fake_token")
        redis.set = AsyncMock()
        redis.expire = AsyncMock()
        http = MagicMock()
        http.post = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"errcode": -1, "errmsg": "network_timeout"}
            )
        )
        http.get = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"errcode": 0, "access_token": "tok", "expires_in": 7200}
            )
        )
        dist = WeWorkDistributor(
            redis=redis,
            http_client=http,
            corp_id="corp1",
            corp_secret="secret",
            agent_id=1,
            push_repo=repo,
        )
        content = _FakeContent()
        sub = _FakeSubscription({"user_id": "user1", "msg_type": "text"})

        await dist.distribute(content, sub)

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("retry_count", 0) >= 1
        error_msg = create_kwargs.get("error_message")
        assert error_msg is not None and error_msg != ""

    @pytest.mark.asyncio
    async def test_failed_email_send_records_retry_count_and_error(self) -> None:
        repo = _make_push_repo(exists_return=False)

        from intellisource.distributor.channels.email import EmailDistributor

        dist = EmailDistributor(
            smtp_host="localhost",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="pass",
            use_tls=False,
            push_repo=repo,
        )
        content = _FakeContent()
        sub = _FakeSubscription({"to_addr": "recipient@example.com"})

        with patch(
            "intellisource.distributor.channels.email.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=OSError("Connection refused"),
        ):
            await dist.distribute(content, sub)

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("retry_count", 0) >= 1
        error_msg = create_kwargs.get("error_message")
        assert error_msg is not None and error_msg != ""


# ---------------------------------------------------------------------------
# AC-6: Second check_dedup call for same tuple returns True
# ---------------------------------------------------------------------------


class TestAC6:
    """check_dedup() returns True when PushRepository.exists() returns True."""

    @pytest.mark.asyncio
    async def test_check_dedup_returns_false_first_call(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo(exists_return=False)

        result = await _make_concrete_distributor().check_dedup(
            sub_id, content_id, "email", repo=repo
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_check_dedup_returns_true_on_second_call(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        # Simulate: second call where the record already exists
        repo = _make_push_repo(exists_return=True)

        result = await _make_concrete_distributor().check_dedup(
            sub_id, content_id, "email", repo=repo
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_channel_distribute_skips_on_true_dedup(self) -> None:
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo(exists_return=True)

        distributor = _make_concrete_distributor()
        is_dup = await distributor.check_dedup(sub_id, content_id, "wework", repo=repo)
        assert is_dup is True
        repo.exists.assert_awaited_once_with(sub_id, content_id, "wework")

    @pytest.mark.asyncio
    async def test_unique_constraint_honored_via_dedup_check(self) -> None:
        """Same (sub_id, content_id, channel) second distribute call is skipped."""
        from intellisource.distributor.channels.wechat import WeChatDistributor

        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()

        # First call: exists=False; create succeeds
        # Second call: exists=True (record was created); create NOT called
        repo = MagicMock()
        repo.exists = AsyncMock(side_effect=[False, True])
        repo.create = AsyncMock(return_value=MagicMock())

        redis = MagicMock()
        redis.get = AsyncMock(return_value="fake_token")
        redis.set = AsyncMock()
        http = MagicMock()
        http.post = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": "1"}
            )
        )
        http.get = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"access_token": "tok", "expires_in": 7200}
            )
        )
        dist = WeChatDistributor(
            redis=redis,
            http_client=http,
            app_id="app123",
            app_secret="secret",
            push_repo=repo,
        )

        content = _FakeContent()
        content.id = content_id
        sub = _FakeSubscription(
            {"openid": "openid_abc", "msg_type": "template", "template_id": "tpl1"}
        )
        sub.id = sub_id

        first = await dist.distribute(content, sub)
        second = await dist.distribute(content, sub)

        assert first["status"] == "success"
        assert second["status"] in ("skipped", "duplicate", "deduplicated")
        # create called only once (first distribute)
        repo.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# AC-7 (security): recipient PII is SHA-256 hashed before persistence
# ---------------------------------------------------------------------------


class TestAC7:
    """Raw phone/email is hashed before being stored; raw value absent from record."""

    @pytest.mark.asyncio
    async def test_record_push_hashes_phone_recipient(self) -> None:
        """record_push with extra_recipient=phone stores SHA-256 hash, not raw value."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        phone = "+8613812345678"
        expected_hash = hashlib.sha256(phone.encode()).hexdigest()
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            "wechat",
            status="success",
            extra_recipient=phone,
            repo=repo,
        )

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        # The hashed value must be present; the raw phone must not be present as a value
        assert create_kwargs.get("recipient_hash") == expected_hash
        assert phone not in create_kwargs.values()

    @pytest.mark.asyncio
    async def test_record_push_hashes_email_recipient(self) -> None:
        """record_push with extra_recipient=email stores SHA-256 hash, not raw value."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        email = "alice@example.com"
        expected_hash = hashlib.sha256(email.encode()).hexdigest()
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            "email",
            status="success",
            extra_recipient=email,
            repo=repo,
        )

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("recipient_hash") == expected_hash
        assert email not in create_kwargs.values()

    @pytest.mark.asyncio
    async def test_raw_phone_not_in_persisted_record(self) -> None:
        """The raw phone string must not appear in any value passed to create()."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        phone = "+8613987654321"
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            "wechat",
            status="success",
            extra_recipient=phone,
            repo=repo,
        )

        create_kwargs = repo.create.await_args[1]
        # Verify raw phone is absent from all string values in persisted data
        all_string_values = [str(v) for v in create_kwargs.values()]
        assert phone not in all_string_values, (
            f"Raw phone '{phone}' must not appear in persisted record values"
        )
