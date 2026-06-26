# Trading-Bot 项目交接页

## 1. 项目基本信息

- 项目名称：Trading-Bot
- 本地路径：`/Users/chenweifeng/Documents/Trading-Bot`
- 项目类型：Python 加密货币永续合约交易系统
- 当前阶段：已建立项目骨架、模拟盘、回测、风控、Telegram 通知、部署相关流程；后续继续围绕策略、生产稳定性和 Web 面板推进。
- 安全边界：默认不真实交易，live 模式必须有额外显式开关。

## 2. 项目目标

第一阶段只接 Binance USDT-M Futures，先实现行情监控、策略信号、回测、模拟盘和 Telegram 通知。后续再逐步增加真实下单、风控增强、Web 面板和跟单能力。

## 3. 当前状态

已知已经推进过：

- Python 3.11+ 项目骨架。
- 配置系统和 `.env.example`。
- Binance 行情客户端。
- 策略接口和示例策略。
- 风控模块。
- 模拟盘和 SQLite 交易记录。
- 回测模块。
- Telegram 通知。
- Docker / Docker Compose 部署说明。
- GitHub 推送和 GitHub CLI 排障。
- 生产环境 Binance timeout、代理/直连差异、部署同步排除规则排障。

## 4. 网络与代理策略

本项目访问外部服务较多，网络失败不能直接判断为代码错误。

重点外部服务：

- Binance Futures API。
- Telegram Bot API。
- GitHub。
- Python 包源。
- Docker Hub。

建议配置矩阵：

| 环境 | 建议模式 | 说明 |
| --- | --- | --- |
| 本地开发 | `proxy` 或 `auto` | 外部 API 失败时先代理重试 |
| 生产服务器 | `direct` 优先 | 避免误用本地代理地址 |
| 排障临时状态 | `auto` | 直连失败后代理 fallback |

必须在 README / `.env.example` 中说明：

- 是否需要代理。
- 哪些请求可能走代理。
- 哪些本地地址不走代理。
- 如何验证代理是否生效。
- 生产环境是否禁止使用本地代理地址。

## 5. 部署注意事项

部署同步前必须 dry-run：

```bash
rsync -av --dry-run ./ user@host:/deploy/path/
```

重点检查排除规则：

- 排除运行数据时用 `/data/`，不要误伤 `app/data/`。
- 不同步 `.env`、数据库、日志、缓存、生成产物。
- 同步后检查服务状态和最近日志。

## 6. 常见坑

| 问题 | 表现 | 快速判断 | 处理办法 |
| --- | --- | --- | --- |
| Binance timeout | paper cycle 失败或 Telegram 噪音通知 | 直连偶发 timeout | 增加超时、重试、降噪；区分生产直连和本地代理 |
| GitHub CLI 不可用 | Codex 右侧 GitHub CLI 不可用 | `which gh` 找不到或未登录 | 安装 `gh`，执行 `gh auth login` 和 `gh auth setup-git` |
| HTTPS push 要密码 | GitHub 密码推送失败 | 终端提示 Password | 使用 PAT，不是 GitHub 登录密码 |
| rsync 排除误伤 | 远端缺少代码目录 | dry-run 可提前发现 | 用 `/data/` 这种根路径排除 |

## 7. Codex 使用提示

继续开发时：

```text
请先阅读 Trading-Bot 项目交接页和 README，确认默认不真实交易、当前网络模式、部署方式和测试命令。接下来只处理：<本次目标>。
```

排障时：

```text
请按网络排障 Runbook 处理。外部请求失败时，先直连，再代理重试，再判断 DNS、TLS、认证、限流、远端服务和代码逻辑。
```

## 8. 下一步建议

- [ ] 把本交接页同步到 `/Users/chenweifeng/Documents/Trading-Bot/PROJECT_CONTEXT.md`。
- [ ] 补齐当前真实测试命令和部署命令。
- [ ] 补齐生产服务器服务名、部署目录和健康检查命令。
- [ ] 更新 README 的代理策略章节。
