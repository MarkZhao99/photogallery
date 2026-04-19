# 短会话边界提醒器设计

## 背景

当前工作流中，图片审阅、元数据补录和其他依赖视觉输入的任务会快速拉长上下文。一旦在同一条长线程里连续看很多图，经过当前代理 `https://crs.us.bestony.com/openai/responses` 时，就更容易触发请求体过大问题。前面已经确认，历史上的 `413 Payload Too Large` 并不是画廊应用上传接口本身导致的，而是会话上下文在代理层超过了限制。

现有手段已经包括 handoff 文档和仓库级约束，但仍然缺少一个“安全模式”的本地辅助工具：当我判断已经到达安全边界、应该切换到短新线程时，需要有一个稳定方式提醒用户，并把续跑指令放到用户手边，而不是继续在当前线程里硬顶。

## 目标

- 在本地实现一个“短会话边界提醒器”
- 当达到安全边界时，自动向用户发出系统通知
- 同时把下一条续跑指令复制到剪贴板
- 把相同内容落盘，方便找回
- 不直接操控聊天框，不模拟自动发送消息
- 保持实现简单、稳定、可控

## 非目标

- 不尝试直接向当前聊天线程自动发消息
- 不解析 Codex 内部私有日志来猜测边界
- 不依赖未经确认的官方 hook 事件
- 不替代 handoff 文档本身

## 用户偏好

用户已经确认选择安全模式，而不是激进模式。这里的安全模式指：

- 检测到边界后只做提醒与剪贴板复制
- 不进行自动聚焦窗口、自动粘贴或自动发送

## 方案比较

### 方案 A：boundary file + watcher

由当前仓库内的一个小脚本在“安全边界”到达时写入一个简短 JSON 文件。后台 watcher 进程监听这个文件变化，一旦变化就执行系统通知、复制到剪贴板，并同步写出一份纯文本续跑指令。

优点：

- 触发来源明确，不需要猜测
- 不依赖 Codex 内部日志格式
- 行为可预测，调试简单
- 最符合当前安全模式需求

缺点：

- 需要在达到边界时显式调用一次 emit 脚本

### 方案 B：handoff watcher

后台 watcher 直接监听 `docs/superpowers/handoffs/` 的文件修改，一旦 handoff 更新就弹通知并复制续跑指令。

优点：

- 少一个边界文件

缺点：

- 无法区分普通 handoff 更新和真正需要切线程的边界
- 更容易误触发

### 方案 C：session log watcher

后台 watcher 解析 `~/.codex/sessions/*.jsonl`，通过日志模式推断是否到了安全边界。

优点：

- 看起来更自动

缺点：

- 对内部日志结构耦合很强
- 非常脆弱
- 容易误判

## 推荐方案

采用方案 A：`boundary file + watcher`。

这是最小且最稳的实现。边界判定仍然由我在任务执行时显式决定，不把“该停了”的语义交给不可靠的日志推断。后台 watcher 只负责消费已经确认过的边界事件，并提供三个安全输出：系统通知、剪贴板、文本文件。

## 设计概览

实现由两个脚本组成：

1. `emit-short-session-boundary`
   负责写入 `.runtime/short-session-boundary.json`

2. `watch-short-session-boundary`
   常驻监听该文件变化并执行提醒动作

边界文件内容足够小，只包含必要信息：

- `created_at`
- `reason`
- `handoff_path`
- `resume_command`
- `resume_text_path`

watcher 只读取这个文件，不扫描整个仓库，不读取长日志，不接触图片内容，因此不会引入新的请求体风险。

## 行为流程

### 触发阶段

当我判断当前任务已经接近上下文安全边界时：

- 先更新 handoff
- 再调用 emit 脚本写入新的边界 JSON

### 消费阶段

watcher 检测到边界文件时间戳或内容变化后：

- 用 `osascript` 弹出 macOS 通知
- 用 `pbcopy` 将 `resume_command` 复制到剪贴板
- 将相同内容写入 `.runtime/last-resume-command.txt`

### 用户体验

用户看到通知后，可以直接：

- 新开线程
- 粘贴剪贴板里的续跑指令

这使得操作尽可能接近“自动继续”，但仍保持在安全模式范围内。

## 文件结构

计划新增以下文件：

- `scripts/emit_short_session_boundary.py`
- `scripts/watch_short_session_boundary.py`
- `tests/test_short_session_boundary.py`

计划使用以下运行时文件：

- `.runtime/short-session-boundary.json`
- `.runtime/last-resume-command.txt`
- 可选：`.runtime/short-session-boundary-watcher.pid`

## 边界文件格式

边界文件采用 JSON，对象结构如下：

```json
{
  "created_at": "2026-04-19T03:00:00+08:00",
  "reason": "image_batch_limit",
  "handoff_path": "/abs/path/to/handoff.md",
  "resume_command": "继续短会话：读取 ...",
  "resume_text_path": "/abs/path/to/.runtime/last-resume-command.txt"
}
```

字段约束：

- `created_at` 必须是 ISO 8601 字符串
- `reason` 是短标签，便于通知文案使用
- `handoff_path` 必须是绝对路径
- `resume_command` 必须是一行短文本
- `resume_text_path` 必须是绝对路径

## 通知与剪贴板策略

通知文案应尽量简短，示例：

- 标题：`Codex 短会话提醒`
- 正文：`已到安全边界，续跑指令已复制到剪贴板。`

剪贴板内容直接使用 `resume_command`，不拼接多余说明，保证用户可以直接粘贴。

## 错误处理

- 如果 `.runtime/` 不存在，脚本先创建
- 如果 watcher 没有通知权限，仍然要继续执行剪贴板和文本写盘
- 如果 `pbcopy` 失败，仍然写出 `last-resume-command.txt`
- 如果通知和剪贴板都失败，至少保证边界 JSON 和文本文件成功落盘

## 测试要求

至少覆盖以下内容：

- emit 脚本能正确创建边界 JSON
- emit 脚本会生成绝对路径字段
- watcher 在检测到新边界时会调用通知命令、剪贴板命令和文本写盘
- watcher 对重复内容不重复触发
- watcher 在通知失败时仍然写文本文件

## 风险与约束

- 这是仓库本地辅助工具，不是 Codex 官方原生能力
- watcher 需要在用户机器上单独启动
- 该工具不能自动创建新聊天线程，也不能自动发送消息
- 该工具只负责提醒和复制，不改变主任务执行逻辑

## 成功标准

- 用户运行 watcher 后，手动触发一次 emit
- 系统会弹通知
- 剪贴板会收到续跑指令
- `.runtime/last-resume-command.txt` 会被更新
- 不会尝试自动操作聊天输入框
