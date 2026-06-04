---
name: summarizer
description: Structured variant — JSON digest with an explicit output schema.
required_vars: [docs_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Generate a JSON digest for the following clustered documents using the structure below.

<output_format>
{"title": str, "summary": str, "timeline": [{"date": str, "event": str}], "key_points": [str]}
</output_format>

{{ untrusted("documents", docs_text) }}
Return only valid JSON. Do not include any explanation or markdown fences.
