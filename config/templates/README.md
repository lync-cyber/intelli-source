# config/templates/ — 用户自定义 digest 模板（覆盖层）

把同名模板文件放进本目录，可**覆盖** `src/intellisource/distributor/templates/builtin/` 里的内置 digest 模板（`daily-brief` / `weekly-roundup` / `push-card` / `topic-deepdive`）。

- **优先级**：`render.py` 先查本目录（用户覆盖），未命中再用内置
- **生效**：`reload`
- 默认为空——不放任何文件即全部使用内置模板

完整说明见 [`../README.md`](../README.md)。
