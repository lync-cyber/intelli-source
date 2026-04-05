"""Web page collector adapter."""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from intellisource.collector.base import BaseCollector, RawContent, compute_fingerprint

# Tags and CSS classes considered non-content noise
_NOISE_TAGS: list[str] = ["nav", "footer", "header", "aside"]
_NOISE_CLASSES: list[str] = ["sidebar", "advertisement"]


class WebCollector(BaseCollector):
    """Collects content from web pages using BeautifulSoup4 + lxml."""

    async def collect(self, source_config: dict[str, object]) -> list[RawContent]:
        """Fetch a web page and extract body content."""
        url = str(source_config["url"])

        try:
            response = await self.conditional_fetch(url)
        except (httpx.TimeoutException, httpx.ConnectError):
            return []

        if response is None:
            return []

        if response.status_code >= 400:
            return []

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # Extract title
        title: str | None = None
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Extract author from meta tag
        author: str | None = None
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author:
            author = meta_author.get("content")  # type: ignore[assignment]

        # Determine CSS selector from metadata
        metadata = source_config.get("metadata")
        css_selector: str | None = None
        if isinstance(metadata, dict):
            sel = metadata.get("css_selector")
            if isinstance(sel, str):
                css_selector = sel

        # Extract body content
        if css_selector:
            selected = soup.select(css_selector)
            body_html = "".join(str(el) for el in selected)
            body_text = " ".join(
                el.get_text(separator=" ", strip=True) for el in selected
            )
        else:
            # Remove noise elements
            for tag_name in _NOISE_TAGS:
                for el in soup.find_all(tag_name):
                    el.decompose()
            for cls in _NOISE_CLASSES:
                for el in soup.find_all(class_=cls):
                    el.decompose()

            body_tag = soup.find("body")
            if body_tag:
                body_html = str(body_tag)
                body_text = body_tag.get_text(separator=" ", strip=True)
            else:
                body_html = ""
                body_text = soup.get_text(separator=" ", strip=True)

        # Compute fingerprint (consistent with RSS/API collectors)
        fingerprint = compute_fingerprint(url, title, None)

        return [
            RawContent(
                source_url=url,
                fingerprint=fingerprint,
                title=title,
                author=author,
                body_html=body_html,
                body_text=body_text,
            )
        ]
