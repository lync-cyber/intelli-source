---
name: context_compress
description: Compress conversation history into a concise system prompt.
required_vars: [conversation]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Summarize the following conversation history into a concise system prompt.
Preserve key facts, decisions, and context needed for continuing the conversation.
Remove redundant details and focus on information relevant to future turns.

{{ untrusted("conversation", conversation) }}
