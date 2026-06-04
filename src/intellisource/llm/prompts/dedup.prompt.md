---
name: dedup
description: Decide whether new content duplicates any candidate, as JSON.
required_vars: [title, body_text, candidate_info]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Determine if the following content is a duplicate of any candidate.

New content:
Title: {{ title }}
{{ untrusted("body", body_text) }}
Candidates:
{{ untrusted("candidates", candidate_info) }}
Respond with JSON: {"is_duplicate": bool, "confidence": float}
