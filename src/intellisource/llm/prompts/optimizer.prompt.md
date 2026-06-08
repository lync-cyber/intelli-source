---
name: optimizer
description: Rewrite a draft title/summary for a push notification, as JSON.
required_vars: [subscription_name, original_title, body_text, draft_title, draft_summary]
---
{% from "_fragments/injection_guard.md" import untrusted %}
Subscription: {{ subscription_name }}
Original title: {{ original_title }}
{{ untrusted("body", body_text) }}
Draft title: {{ draft_title }}
Draft summary: {{ draft_summary }}
Return JSON with keys title (max 80 chars) and summary (max 200 chars) optimized for a push notification.
