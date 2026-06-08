---
name: digest_why
description: 为单条收录内容生成一句"为什么值得关注"
required_vars:
  - title
  - summary
---
{% from "_fragments/injection_guard.md" import untrusted %}
{% include "_fragments/editor_persona.md" %}
下面是一条收录内容：
{{ untrusted("item_title", title) }}
{{ untrusted("item_summary", summary) }}
请用中文写一句不超过 40 字的"为什么值得关注"，点明它对读者的现实意义。
只输出这一句，不要加前缀、不要使用 markdown、不要加引号。
