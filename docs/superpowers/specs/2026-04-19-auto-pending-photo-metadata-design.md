# 自动 Pending 照片元数据处理设计

## 背景

当前上传链路只负责把照片写入存储，并将新图标记为 `pending`。后续的地点识别、场景摘要、标题生成和国家简介补全，仍然依赖人工导出 `pending-batch`、在当前对话中逐批处理、再调用 `apply-batch` 回写。

这个流程虽然已经可以稳定工作，但它有两个明显问题：

1. 上传后的照片不会自动补全元数据，后台和公开页会短时间保留默认标题或空白地点字段。
2. 人工持续跟进 `pending` 队列会打断上传后的正常使用，也无法形成“上传后自动整理”的产品体验。

用户这次明确要求把 `pending` 照片自动识图并补元数据、改标题，同时仍然坚持两个硬约束：

- 上传必须立即返回，不能把识图塞进上传请求。
- “本机模型”指的是当前机器上的 Codex CLI 链路，而不是外部 API。

另外，历史上已经确认过一次 `413 Payload Too Large` 来自对话/代理层而非 Flask 上传接口，因此新的自动化必须继续遵守“小批次、短进程、极小上下文”的约束。

## 目标

- 上传新照片后，照片继续先进入 `pending` 队列。
- 本地常驻 worker 自动发现 `pending` 批次，并异步调用新的短 Codex 子进程处理。
- 自动补全每张照片的 `city/place/subject/scene_summary`，并生成标题。
- 在结果可信时同步更新国家 `short_description` / `long_description`。
- 后台可见当前自动处理状态，包括 `pending / processing / done / review` 的数量和最近错误摘要。
- 自动处理失败时支持重试与超时恢复，不让队列永久卡死。

## 非目标

- 不把识图逻辑直接塞进 Flask 上传请求或 Flask 进程内的后台线程。
- 不引入外部云端视觉 API。
- 不在第一阶段做复杂的任务中心、优先级系统或多 worker 并行调度器。
- 不改变当前人工 `pending-batch / apply-batch` 流程；人工流程仍然保留为回退手段。

## 方案比较

### 方案 A：Flask 上传后同步执行识图

上传接口在保存图片后直接调用本地模型处理，并等待全部结果返回再响应。

优点：

- 表面上最直接

缺点：

- 违背“上传必须秒回”的要求
- 上传时长完全受模型速度影响
- 一旦识图失败，上传体验也一起失败
- 更容易把长日志和图像处理链路塞进一次请求周期

### 方案 B：Flask 进程内后台线程异步跑识图

上传成功后，由 Flask 进程里的后台线程扫描 `pending` 并调用本地模型。

优点：

- 不需要额外守护进程

缺点：

- 进程重启、异常退出、开发模式重载和线程生命周期都不稳定
- 调试困难，恢复困难
- 应用进程和模型桥接逻辑耦合过深

### 方案 C：launchd 常驻 worker + 短 Codex 子进程

本地常驻 worker 轮询 `pending` 队列，原子认领“单国家、最多 5 张”的批次，启动一个新的短 Codex 子进程处理，结果经校验后再回写。

优点：

- 最符合上传秒回和短会话约束
- 认领、超时恢复、失败重试都可以在独立进程里完成
- 与现有 `pending-batch / apply-batch` 数据流天然兼容
- 一批一个新进程，最容易持续规避 413

缺点：

- 需要补一层 worker、认领和桥接逻辑

## 推荐方案

采用方案 C：`launchd` 常驻 worker + 短 Codex 子进程。

这是当前约束下最稳的方案。上传链路继续只做保存与入队，不承担模型处理；worker 只做队列调度、认领与回写；每个批次都交给全新的短 Codex 子进程处理，避免上下文越滚越大。

## 总体架构

系统拆成三层：

1. **上传层**
   `/api/upload` 继续只负责保存图片、写国家、标记 `pending`。

2. **调度层**
   新增本地常驻 worker，负责：
   - 发现和认领待处理批次
   - 检查超时 `processing` 批次并恢复
   - 启动短 Codex 子进程
   - 校验输出
   - 调用现有回写逻辑

3. **模型桥接层**
   每个批次启动一个全新的短 Codex 子进程。该子进程仅读取：
   - 工作流 prompt
   - 单批 JSON
   - 本地图片绝对路径

   并且只输出严格 JSON，不输出长解释。

## 数据流

上传后的完整链路如下：

`upload -> pending -> worker claim -> processing -> short codex subprocess -> validated JSON -> apply_manual_review_batch -> done/review`

具体步骤：

1. 用户从后台上传照片。
2. `storage.save_photo()` 保存图片，并将照片状态写成：
   - `processing_status = pending`
   - `processing_reason = upload`
3. worker 周期性扫描队列。
4. worker 在同一把元数据锁里认领一批：
   - 只取一个国家
   - 最多 `5` 张
   - 一次认领时把状态改成 `processing`
5. worker 为该批次生成临时输入文件。
6. worker 启动新的短 Codex 子进程，让其只返回该批次的 JSON 结果。
7. worker 校验输出：
   - JSON 结构合法
   - 照片数量和名称完全匹配
   - 元数据字段可归一化
8. 校验通过后，调用现有 `apply_manual_review_batch()` 回写。
9. 校验失败或子进程失败时，整批回退或转 `review`。

## 状态模型

第一阶段继续沿用现有四种状态：

- `pending`
- `processing`
- `done`
- `review`

在此基础上，新增或正式使用以下运行态字段：

- `processing_attempts`
- `processing_reason`
- `processing_error`
- `processing_owner`
- `processing_batch_id`
- `processing_started_at`

语义约束：

- `pending`：等待 worker 认领
- `processing`：已被某个 worker 认领，正在执行
- `done`：元数据完整，标题已生成或更新
- `review`：连续失败达到阈值，暂停自动重试，等待人工处理

## 任务认领与并发控制

worker 不直接读取 `pending-batch` 后就假设这批还空闲，而是新增一个“原子认领”动作。

认领规则：

- 只认领当前排序最前面的一个国家
- 每批最多 `5` 张
- 认领动作和状态切换必须在同一把元数据锁里完成

认领时为每张照片写入：

- `processing_status = processing`
- `processing_reason = auto_worker`
- `processing_attempts += 1`
- `processing_owner = <worker_id>`
- `processing_batch_id = <uuid>`
- `processing_started_at = <iso timestamp>`

这样即使未来有多个 worker 实例，也只能有一个实例成功认领该批次。

## 失败重试与超时恢复

以下情况都视为整批失败：

- Codex 子进程启动失败
- Codex 子进程超时
- Codex 子进程退出码非 `0`
- 输出不是合法 JSON
- 返回的照片数量或照片名与认领批次不一致
- JSON 字段无法通过本地归一化/校验

失败后的处理：

- 若 `processing_attempts < AUTO_METADATA_MAX_ATTEMPTS`，整批恢复为 `pending`
- 若达到上限，则整批转为 `review`
- 始终保留 `processing_error`
- 同时清理 `processing_owner / processing_batch_id / processing_started_at`

为了避免崩溃导致队列永久卡死，worker 每轮开始前先检查超时 `processing`：

- 若超过 `AUTO_METADATA_PROCESSING_TIMEOUT_SECONDS`
  - 未达最大次数：退回 `pending`
  - 已达最大次数：转 `review`

## 413 规避策略

自动化必须把“规避 413”写成强约束，而不是使用建议。

每个批次都必须满足：

- 单国家
- 单批最多 `5` 张
- 不传整库元数据
- 不传长会话历史
- 不把图片 base64 大块嵌入 prompt
- 只传：
  - 本地绝对路径
  - 极小批次 JSON
  - 短 prompt

模型桥接输出只允许严格 JSON，禁止返回长解释。

## 后台可见性

第一阶段只做最小可见状态，不做复杂任务控制台。

后台新增一块轻量状态区，显示：

- `pending` 数量
- `processing` 数量
- `review` 数量
- 最近一次自动处理时间
- 最近一条错误摘要

同时保留两个简单控制动作：

- `立即扫描 pending`
- `重试 review`

这两个动作足以支持人工干预，而不需要额外引入完整任务系统。

## 保持人工流程可用

现有人工流程仍然保留：

- `python3 scripts/process_gallery_metadata.py pending-batch --limit 5`
- `python3 scripts/process_gallery_metadata.py apply-batch --input <json>`

自动 worker 与人工流程共享同一套元数据结构和回写逻辑。自动化失效时，人工仍然可以继续处理 `pending` 或 `review`。

## 测试要求

至少覆盖以下行为：

1. 上传接口仍然秒回，不等待自动识图。
2. 新上传照片保持 `pending`。
3. worker 能原子认领一个批次，并将其设为 `processing`。
4. 同一批不能被重复认领。
5. 子进程成功返回合法 JSON 时，能正确回写元数据、标题和国家简介。
6. 子进程失败、超时、坏 JSON、照片不匹配时，不会部分污染元数据。
7. 超时 `processing` 能被恢复。
8. 后台状态面板能显示自动处理队列状态。

## 风险与约束

- 这里说的“当前模型”并不是当前聊天线程本身，而是当前机器上的 Codex CLI 模型链路。
- 自动 worker 需要本机环境能启动 `codex` 短进程。
- 如果 Codex CLI 的非交互输出接口受限，需要通过受控脚本包装。
- 由于第一阶段不做复杂审计面板，深度问题排查仍然依赖日志文件。

## 成功标准

满足以下条件即可认为第一阶段成功：

- 用户上传新图后，请求立即返回成功。
- 新图先进入 `pending`。
- 本地 worker 会自动认领并处理 `pending` 批次。
- 成功处理后，照片自动获得元数据和标题，状态变为 `done`。
- 失败批次会自动重试，并在达到阈值后转为 `review`。
- 后台能看见当前自动处理队列状态。
