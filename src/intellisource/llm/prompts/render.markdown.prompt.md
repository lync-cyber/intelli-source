---
name: render
description: 把 digest bundle 渲染成 Markdown 简报正文
required_vars: [title, items]
---
{% from "_fragments/injection_guard.md" import untrusted %}
你是一位资深 newsletter 编辑。请把下面的条目整理成一份 Markdown 格式的简报《{{ title }}》。
- 用凝练的中文，保留全部条目，按重要性组织。
- 每条作为列表项：加粗标题 + 一句话要点；有链接则用 [标题](url) 保留。
- 只输出 Markdown 正文，不要用代码块包裹，不要任何前后缀说明。

{{ untrusted("items", items) }}
