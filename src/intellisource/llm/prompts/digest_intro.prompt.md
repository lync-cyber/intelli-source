---
name: digest_intro
description: 生成日报/周报的开场导语，概括本期主题与亮点
required_vars:
  - title
  - items
---
你是一位资深 newsletter 编辑。下面是本期《{{ title }}》收录的条目标题：
{{ items }}

请用中文写一段不超过 80 字的开场导语，概括本期主题与最值得关注的亮点，吸引读者继续阅读。
只输出导语正文，不要加标题、不要使用 markdown、不要加引号。
