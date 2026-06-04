---
name: optimizer
description: Rewrite content for a target distribution channel, as JSON.
required_vars: [channel, title, body_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Optimize the following content for distribution on the '{{ channel }}' channel.
Adjust tone, length, and format for the channel's constraints.
Return JSON: {"title": str, "summary": str}

Title: {{ title }}
{{ untrusted("content", body_text) }}
