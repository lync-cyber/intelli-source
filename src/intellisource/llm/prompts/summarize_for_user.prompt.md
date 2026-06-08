---
name: summarize_for_user
description: Summarize a single content item for a chat user.
required_vars: [content]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Summarize the following content:

{{ untrusted("content", content) }}
