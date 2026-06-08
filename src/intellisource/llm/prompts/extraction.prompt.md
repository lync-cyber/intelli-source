---
name: extraction
description: Extract structured data from text as JSON matching a schema.
required_vars: [schema, body_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Extract structured data from the following text as JSON.
Schema: {{ schema }}

{{ untrusted("text", body_text) }}
Return only valid JSON. Do not include any explanation or markdown fences.
