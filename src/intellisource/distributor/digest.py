"""DigestAssembler — assemble a periodic (daily/weekly) digest for one subscription.

Pure orchestration over the existing matcher / frequency controller / template
engine: the caller supplies the candidate content rows for the delivery window
(the DB query lives in the beat task), and this class decides whether the
subscription is due, which rows actually match its rules, and renders a single
digest payload ready for the channel to send.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intellisource.distributor.digest_enhance import DigestEnhancer
from intellisource.distributor.frequency import FrequencyController
from intellisource.distributor.matcher import SubscriptionMatcher
from intellisource.distributor.templates import resolve_template_for
from intellisource.observability.logging import get_logger

_logger = get_logger(__name__)

# Channel → preferred render format. DigestTemplate.render falls back to the
# template's default_format when the preferred format is unsupported (e.g.
# weekly-roundup only renders html), so this is a best-effort preference.
_CHANNEL_FORMAT: dict[str, str] = {
    "email": "html",
    "wework": "markdown",
    "wechat": "markdown",
}

# Frequency → default digest template when channel_config["template"] is unset.
_FREQUENCY_TEMPLATE: dict[str, str] = {
    "daily": "daily-brief",
    "weekly": "weekly-roundup",
}


@dataclass
class DigestPayload:
    """A rendered periodic digest ready to be sent on one subscription's channel."""

    subscription: Any
    channel: str
    title: str
    body: str
    fmt: str
    content_ids: list[str] = field(default_factory=list)


class DigestAssembler:
    """Collect window content for a subscription, aggregate + render one digest."""

    def __init__(
        self,
        *,
        matcher: SubscriptionMatcher | None = None,
        frequency: FrequencyController | None = None,
        enhancer: DigestEnhancer | None = None,
    ) -> None:
        self._matcher = matcher or SubscriptionMatcher()
        self._frequency = frequency or FrequencyController()
        self._enhancer = enhancer

    async def assemble(
        self, subscription: Any, contents: list[Any]
    ) -> DigestPayload | None:
        """Build a digest payload, or return None when nothing should be sent.

        Returns None when the subscription is not due (frequency interval not
        elapsed or inside quiet hours) or when no candidate content matches its
        rules. When ``template_config["enhance"]`` is truthy and an enhancer is
        wired, the bundle's intro / per-item why_it_matters are filled by the LLM
        before rendering (best-effort; failures degrade silently).
        """
        if not self._frequency.should_send_now(subscription):
            return None

        matched = self._matched_contents(subscription, contents)
        if not matched:
            return None

        channel: str = getattr(subscription, "channel", "")
        frequency: str = getattr(subscription, "frequency", "")
        default_template = _FREQUENCY_TEMPLATE.get(frequency, "daily-brief")
        template, tmpl_cfg = resolve_template_for(
            getattr(subscription, "channel_config", {}),
            default=default_template,
        )
        bundle = template.aggregate(matched, tmpl_cfg)
        if self._enhancer is not None and tmpl_cfg.get("enhance"):
            await self._enhancer.enhance(bundle)
        fmt: str = _CHANNEL_FORMAT.get(channel) or template.default_format
        rendered = template.render(bundle, fmt)
        body = rendered if isinstance(rendered, str) else str(rendered)

        _logger.info(
            "assembled digest sub=%s channel=%s template=%s items=%d",
            getattr(subscription, "id", ""),
            channel,
            template.name,
            len(matched),
        )
        return DigestPayload(
            subscription=subscription,
            channel=channel,
            title=bundle.title,
            body=body,
            fmt=fmt,
            content_ids=[str(getattr(c, "id", "")) for c in matched],
        )

    def _matched_contents(self, subscription: Any, contents: list[Any]) -> list[Any]:
        """Filter + dedup contents matching the subscription's rules.

        Reuses SubscriptionMatcher so source_names / keyword / tag / min_score
        semantics stay identical to per-item push, then drops duplicate ids.
        """
        seen: set[str] = set()
        matched: list[Any] = []
        for content in contents:
            if not self._matcher.match(content, [subscription]):
                continue
            cid = str(getattr(content, "id", ""))
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            matched.append(content)
        return matched
