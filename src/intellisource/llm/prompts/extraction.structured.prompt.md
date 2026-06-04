---
name: extraction
description: Structured variant — extract JSON conforming to a schema, strict.
required_vars: [schema, body_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Extract structured data from the text below and return it as JSON conforming to the provided schema.

<schema>
{{ schema }}
</schema>

{{ untrusted("document", body_text) }}
Return only valid JSON matching the schema. Do not include any explanation or markdown fences.
