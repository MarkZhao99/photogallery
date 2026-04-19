# 2026-04-19 GitHub 发布与 README 整理

## 目标

- 将本地仓库发布到 GitHub
- 补齐仓库 README、忽略规则和日常 Git 工作流说明
- 保持图片相关任务继续遵守短会话和小批量处理，避免请求体膨胀与 `413`

## 当前状态

- GitHub 远端已配置并已推送成功
- 本地 `main` 已成功推送并跟踪 `origin/main`
- 已重写 `README.md`，补充：
  - 项目能力总览
  - 自动 `pending` 图片元数据流程
  - `launchd` 后台 worker 用法
  - `413` / 上下文膨胀规避说明
  - 日常 `git status / add / commit / push` 工作流
- 已扩展 `.gitignore`，补充覆盖率、构建产物和常见 Python 开发缓存
- GitHub 仓库描述尚未确认是否已通过 API 写入

## 验证命令

```bash
cd /path/to/photogallery
git status -sb
git remote -v
git ls-remote --heads origin main
python3 -m unittest discover -s tests -v
```

## 风险和注意事项

- 如果再次进行 GitHub API 写操作，需要可用 PAT；不要把 PAT 明文贴到对话里
- 图片整理继续保持单批最多 5 张，并优先走 handoff + 短会话
- 如果后续需要重写历史，应单独确认是否允许 `force push`

## 最短恢复上下文

- 先看 `README.md`
- 再看本文件
- 若要继续图片自动元数据功能，读 `docs/superpowers/handoffs/2026-04-19-country-intro-and-413.md`
