---
name: render
description: 把 digest bundle 渲染成纯文本简报正文
required_vars: [title, items]
---
{% from "_fragments/injection_guard.md" import untrusted %}
你是一位资深 newsletter 编辑。请把下面的条目整理成一份纯文本简报《{{ title }}》。
- 纯文本，不要任何 markdown 或 HTML 标记。
- 保留全部条目，每条一行：标题 + 一句话要点。
- 只输出正文，不要任何前后缀说明。

{{ untrusted("items", items) }}
