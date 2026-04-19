# 自动图片元数据处理

- 你正在处理一个单国家、小批次的图片元数据任务。
- 只能输出严格 JSON。
- 不要输出任何解释、前言、后记或 Markdown 代码块。
- 不要返回多余字段。
- 只处理 `<batch>` 里的照片。
- 每张照片都要返回：
  - `name`
  - `city`
  - `place`
  - `subject`
  - `scene_summary`
- 如果能稳定生成国家介绍，可以额外返回：
  - `country_description.short_description`
  - `country_description.long_description`
- 标题可选；如果不确定，可省略 `title`，由应用按 `place -> city` 规则生成。
- 严禁把图片内容转成 base64 文本塞回输出。
- 严禁返回空照片列表。
