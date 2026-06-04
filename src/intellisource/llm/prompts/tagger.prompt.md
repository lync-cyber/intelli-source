---
name: tagger
description: Classify content into a JSON array of relevant tags.
required_vars: [title, body_text]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Analyze the following content and return a JSON array of relevant tags.
If the content cannot be classified, return ["未分类"].
{{ library_hint | default("") }}

Title: {{ title }}
{{ untrusted("content", body_text) }}
