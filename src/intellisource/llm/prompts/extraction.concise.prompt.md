---
name: extraction
description: Concise variant — extract data as JSON, no explanation.
required_vars: [schema, body_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Extract data from the text as JSON. Schema: {{ schema }}

{{ untrusted("text", body_text) }}
JSON only, no explanation.
