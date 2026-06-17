"""Tests for BaseDistributor dedup hooks and per-channel PushRecord integration.

Covers AC-1 through AC-7.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from source_scan import find_substring_in_tree

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_SRC_DIR = str(
    Path(__file__).parent.parent.parent.parent / "src" / "intellisource" / "distributor"
)


def _find_pattern_in_source(pattern: str, *, src_dir: str = _SRC_DIR) -> list[str]:
    """Cross-platform equivalent of ``grep -rn PATTERN src_dir``."""
    return find_substring_in_tree(src_dir, pattern)


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
            status="sent",
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
            status="sent",
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
        assert create_kwargs.get("status") == "sent"

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
        assert create_kwargs.get("status") == "sent"

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
        matches = _find_pattern_in_source("push:dedup:")
        assert not matches, (
            "Legacy 'push:dedup:' Redis key pattern found in source:\n"
            + "\n".join(matches)
        )

    def test_no_wework_dedup_redis_key_pattern_in_source(self) -> None:
        """Source code must not contain legacy 'wework:dedup:' redis key patterns."""
        matches = _find_pattern_in_source("wework:dedup:")
        assert not matches, (
            "Legacy 'wework:dedup:' Redis key pattern found in source:\n"
            + "\n".join(matches)
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
        matches = _find_pattern_in_source("_sent_keys")
        assert not matches, (
            "Legacy '_sent_keys' in-process set found in source:\n" + "\n".join(matches)
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
            status="sent",
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
            status="sent",
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
            status="sent",
            extra_recipient=phone,
            repo=repo,
        )

        create_kwargs = repo.create.await_args[1]
        # Verify raw phone is absent from all string values in persisted data
        all_string_values = [str(v) for v in create_kwargs.values()]
        assert phone not in all_string_values, (
            f"Raw phone '{phone}' must not appear in persisted record values"
        )


# ---------------------------------------------------------------------------
# AC-8: PII masking applied to error_message before persistence
# ---------------------------------------------------------------------------


class TestAC8PiiMasking:
    """error_message containing PII is masked before being written to DB."""

    @pytest.mark.asyncio
    async def test_error_message_email_is_masked_before_persist(self) -> None:
        """record_push masks email in error_message before calling repo.create."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo()
        raw_error = "SMTP error: recipient user@example.com rejected"

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            "email",
            status="failed",
            error_message=raw_error,
            repo=repo,
        )

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        stored_error = create_kwargs.get("error_message", "")
        assert "user@example.com" not in (stored_error or ""), (
            "Raw email address must not appear in persisted error_message"
        )
        assert stored_error is not None and stored_error != "", (
            "Masked error_message must still be non-empty"
        )

    @pytest.mark.asyncio
    async def test_error_message_phone_is_masked_before_persist(self) -> None:
        """record_push masks phone numbers in error_message before repo.create."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo()
        raw_error = "Delivery failed for +8613812345678: number not found"

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            "wechat",
            status="failed",
            error_message=raw_error,
            repo=repo,
        )

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        stored_error = create_kwargs.get("error_message", "")
        assert "+8613812345678" not in (stored_error or ""), (
            "Raw phone number must not appear in persisted error_message"
        )
        assert stored_error is not None and stored_error != "", (
            "Masked error_message must still be non-empty"
        )

    @pytest.mark.asyncio
    async def test_error_message_with_both_email_and_phone_masked(self) -> None:
        """When error_message contains both an email and a phone, both are masked."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo()
        raw_email = "alice@corp.com"
        raw_phone = "+8613987654321"
        raw_error = f"Error: contact {raw_email} or call {raw_phone} for support"

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            "wework",
            status="failed",
            error_message=raw_error,
            repo=repo,
        )

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        stored_error = create_kwargs.get("error_message", "")
        assert raw_email not in (stored_error or ""), (
            "Raw email must not appear in persisted error_message"
        )
        assert raw_phone not in (stored_error or ""), (
            "Raw phone must not appear in persisted error_message"
        )


# ---------------------------------------------------------------------------
# IntegrityError on concurrent dedup race is swallowed (idempotent)
# ---------------------------------------------------------------------------


class TestIntegrityErrorRace:
    """Concurrent duplicate INSERT raises IntegrityError; silently ignored."""

    @pytest.mark.asyncio
    async def test_integrity_error_on_create_does_not_propagate(self) -> None:
        """When repo.create raises IntegrityError, _record_push_if_repo swallows it."""
        from sqlalchemy.exc import IntegrityError

        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()

        repo = MagicMock()
        repo.exists = AsyncMock(return_value=False)
        repo.create = AsyncMock(
            side_effect=IntegrityError(
                "UniqueViolation",
                {},
                Exception("duplicate key value violates unique constraint"),
            )
        )

        distributor = _make_concrete_distributor()
        distributor._push_repo = repo

        # Should NOT raise — the IntegrityError must be swallowed
        await distributor._record_push_if_repo(
            sub_id, content_id, "wechat", status="sent"
        )

        repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifecycle_integrity_error_swallowed(self) -> None:
        """When _record_push_if_repo encounters IntegrityError, lifecycle completes."""
        from sqlalchemy.exc import IntegrityError

        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()

        repo = MagicMock()
        repo.exists = AsyncMock(return_value=False)
        repo.create = AsyncMock(
            side_effect=IntegrityError(
                "UniqueViolation",
                {},
                Exception("duplicate key value violates unique constraint"),
            )
        )

        distributor = _make_concrete_distributor()
        distributor._push_repo = repo

        async def _ok_attempt(attempt: int, is_last: bool) -> tuple[bool, None, dict]:
            return True, None, {}

        (
            was_deduped,
            succeeded,
            retry_count,
            error,
            raw,
        ) = await distributor._send_with_dedup_lifecycle(
            sub_id,
            content_id,
            "wechat",
            attempt_fn=_ok_attempt,
            max_retry=1,
        )

        assert not was_deduped
        assert succeeded
        assert error is None


# ---------------------------------------------------------------------------
# status enum — "sent" on success, "failed" on failure; invalid raises
# ---------------------------------------------------------------------------


class TestStatusEnum:
    """PushRecord.status aligns with arch E-010 allowed values."""

    @pytest.mark.asyncio
    async def test_success_path_uses_sent_status(self) -> None:
        """_send_with_dedup_lifecycle writes status='sent' on the success path."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo(exists_return=False)

        distributor = _make_concrete_distributor()
        distributor._push_repo = repo

        async def _ok_attempt(attempt: int, is_last: bool) -> tuple[bool, None, dict]:
            return True, None, {}

        await distributor._send_with_dedup_lifecycle(
            sub_id,
            content_id,
            "wechat",
            attempt_fn=_ok_attempt,
            max_retry=1,
        )

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "sent"

    @pytest.mark.asyncio
    async def test_failure_path_uses_failed_status(self) -> None:
        """_send_with_dedup_lifecycle writes status='failed' on the failure path."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo(exists_return=False)

        distributor = _make_concrete_distributor()
        distributor._push_repo = repo

        async def _fail_attempt(attempt: int, is_last: bool) -> tuple[bool, str, dict]:
            return False, "error", {}

        await distributor._send_with_dedup_lifecycle(
            sub_id,
            content_id,
            "wechat",
            attempt_fn=_fail_attempt,
            max_retry=1,
        )

        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "failed"

    @pytest.mark.asyncio
    async def test_invalid_status_raises_value_error(self) -> None:
        """record_push raises ValueError for status values not in the allowed enum."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        with pytest.raises(ValueError, match="Invalid push record status"):
            await distributor.record_push(
                sub_id,
                content_id,
                "wechat",
                status="success",
                repo=repo,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_status", ["success", "error", "ok", "done", ""])
    async def test_invalid_status_values_raise(self, invalid_status: str) -> None:
        """Parametrized check: non-enum status values all raise ValueError."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        with pytest.raises(ValueError):
            await distributor.record_push(
                sub_id,
                content_id,
                "wechat",
                status=invalid_status,
                repo=repo,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valid_status", ["pending", "sent", "delivered", "failed"])
    async def test_valid_status_values_accepted(self, valid_status: str) -> None:
        """All arch E-010 allowed status values are accepted without error."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo()

        distributor = _make_concrete_distributor()
        await distributor.record_push(
            sub_id,
            content_id,
            "wechat",
            status=valid_status,
            repo=repo,
        )
        repo.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# retry_count reflects actual attempt index on success
# ---------------------------------------------------------------------------


class TestRetryCountTracking:
    """retry_count written to PushRecord equals the winning attempt index."""

    @pytest.mark.asyncio
    async def test_first_attempt_success_retry_count_zero(self) -> None:
        """When the first attempt succeeds, retry_count=0 is written."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo(exists_return=False)

        distributor = _make_concrete_distributor()
        distributor._push_repo = repo

        async def _ok_attempt(attempt: int, is_last: bool) -> tuple[bool, None, dict]:
            return True, None, {}

        await distributor._send_with_dedup_lifecycle(
            sub_id, content_id, "wechat", attempt_fn=_ok_attempt, max_retry=3
        )

        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("retry_count") == 0

    @pytest.mark.asyncio
    async def test_third_attempt_success_retry_count_two(self) -> None:
        """When attempt 2 succeeds (0,1 fail), retry_count=2 is written."""
        sub_id = uuid.uuid4()
        content_id = uuid.uuid4()
        repo = _make_push_repo(exists_return=False)

        distributor = _make_concrete_distributor()
        distributor._push_repo = repo

        call_count = 0

        async def _fail_then_succeed(
            attempt: int, is_last: bool
        ) -> tuple[bool, str | None, dict]:
            nonlocal call_count
            call_count += 1
            if attempt < 2:
                return False, "transient error", {}
            return True, None, {}

        await distributor._send_with_dedup_lifecycle(
            sub_id, content_id, "wechat", attempt_fn=_fail_then_succeed, max_retry=3
        )

        assert call_count == 3
        repo.create.assert_awaited_once()
        create_kwargs = repo.create.await_args[1]
        assert create_kwargs.get("status") == "sent"
        assert create_kwargs.get("retry_count") == 2
