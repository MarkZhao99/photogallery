# Git Pre-Push Secret Scan Design

**目标**

在这个仓库里增加一个可随仓库分发的 Git `pre-push` 保护层，在代码真正推送到远端前自动扫描常见密钥、敏感配置和本机环境痕迹，并在命中时阻止 `git push`。

**范围**

- 使用仓库内版本化的 `.githooks/pre-push`
- 提供一个安装脚本，把 `core.hooksPath` 指向仓库内 `.githooks`
- 把核心扫描逻辑放到可单独执行的脚本里，便于测试和手动运行
- 默认扫描“即将推送的提交差异”，而不是整个磁盘
- 对 `.env.example`、测试假值和常见模板做少量白名单，降低误报

**不做的事**

- 不引入额外第三方依赖
- 不做 `pre-commit` 双重拦截
- 不尝试覆盖所有可能的 secret 格式
- 不重写 Git 历史

**推荐方案**

采用“三段式”结构：

1. `scripts/check_repo_secrets.py`
   负责计算要扫描的提交范围、读取 diff、匹配规则、输出问题清单、返回退出码
2. `.githooks/pre-push`
   作为 Git hook 入口，只做最薄的一层转发
3. `scripts/install_git_hooks.sh`
   负责把当前仓库配置为使用 `.githooks`

这样做的原因：

- 核心逻辑放在 Python 中更容易测试
- hook 本身保持很薄，出问题时更容易定位
- 安装动作显式可重复，不依赖手工拷贝到 `.git/hooks`

**检测策略**

分三类规则：

1. 高危 token / 私钥模式
   - `ghp_`
   - `github_pat_`
   - `sk-`
   - `-----BEGIN ... PRIVATE KEY-----`

2. 常见敏感配置键
   - 带有 `API_KEY` 的配置赋值
   - 带有 `TOKEN` 的配置赋值
   - 带有 `SECRET` 的配置赋值
   - 带有 `PASSWORD` 的配置赋值
   - `Authorization` 头里的 `Bearer` 令牌写法

3. 环境泄露痕迹
   - `/Users/`
   - `.cloudflared/`

默认行为：

- 命中任何规则都阻止 push
- 输出文件路径、行号、规则名和简短修复建议
- 对 `.env.example`、测试目录和明显的假值做白名单豁免

**白名单原则**

白名单必须尽量窄，只豁免已知模板和测试假值：

- `.env.example`
- `tests/`
- 包含 `your-password`、`change-this-...`、`test-...`、`REPLACE_WITH_...` 的示例值

如果一个命中既在白名单文件里，又是明显真密钥格式，仍然应拦截。

**用户体验**

安装后：

- 平时开发无感
- 执行 `git push` 时自动检查
- 命中问题时打印：
  - 规则类别
  - 文件路径
  - 行号
  - 匹配片段
  - 建议改法

**测试策略**

至少验证：

- 正常模板内容可通过
- 高危 token 会被拦截
- 本机绝对路径会被拦截
- `.env.example` 中的示例密码不会误报
- 安装脚本能把 `core.hooksPath` 指向 `.githooks`

**验收标准**

- 执行 `./scripts/install_git_hooks.sh` 后，`git config --get core.hooksPath` 返回 `.githooks`
- 含有高危 secret 的提交无法 `git push`
- 普通提交不受影响
- 测试覆盖扫描逻辑和安装流程
