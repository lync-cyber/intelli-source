---
name: summarizer
description: Produce a JSON digest for a cluster of documents.
required_vars: [docs_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Generate a JSON digest for the following clustered documents.
Output format: {"title": str, "summary": str, "timeline": [{"date": str, "event": str}], "key_points": [str]}

{{ untrusted("documents", docs_text) }}
