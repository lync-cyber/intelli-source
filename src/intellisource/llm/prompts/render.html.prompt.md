---
name: render
description: 把 digest bundle 渲染成 HTML 邮件正文
required_vars: [title, items]
---
{% from "_fragments/injection_guard.md" import untrusted %}
你是一位资深 newsletter 编辑。请把下面的条目整理成一封 HTML 邮件正文《{{ title }}》。
- 输出基础 HTML 片段（可用 <h2>/<p>/<ul>/<li>/<a> 等标签），严禁 <script>/<style>/<iframe>。
- 保留全部条目，按重要性组织；有链接则用 <a href> 保留。
- 只输出 HTML，不要用 markdown 代码块包裹，不要任何前后缀说明。

{{ untrusted("items", items) }}
