---
name: cluster
description: Generate a short cluster topic label for a single content item.
required_vars: [title, body_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Generate a short cluster topic label for the following content.

Title: {{ title }}
{{ untrusted("body", body_text) }}
Respond with only the topic label.
