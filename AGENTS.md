# AGENTS.md

本文件是给 Codex/Agent 使用的项目级约束，不替代 README。只记录后续自动化编码、排障、测试和发布时必须稳定遵守的规则。

## Must Follow

- 本项目默认只运行行情监控、雷达信号、回测、模拟盘、SQLite 记录、Telegram 通知和 Web Admin。
- 禁止把真实交易当作普通配置改动开启。不要随手修改 `RUN_MODE=live` 或 `ENABLE_LIVE_TRADING=true`。
- 不要提交 `.env`、真实 API Key、Telegram Token、Chat ID、代理地址或生产机器私有配置。
- 修改代码时保持现有结构和命名风格，避免 unrelated refactor。
- 关键函数、复杂分支、异常兜底、外部接口调用需要补充简短中文注释，说明“这段负责什么”或“为什么这样做”。
- 不要给第三方依赖、标准库、显而易见的语法逐行加注释。

## GPT Review Workflow

- 本项目采用 GPT 审查闭环流程，详细流程见 `docs/ai-review-workflow.md`。
- 每次代码修改必须新建独立分支，禁止直接修改 `main` / `master`。
- 完成后提交 commit，并创建或更新 PR，按照 `.github/pull_request_template.md` 填写 PR 内容。
- PR 中必须如实填写：原始需求、修改摘要、修改文件、核心逻辑变化、影响范围、风险检查、已运行测试、未验证风险、回滚方案、部署说明、Codex 自检结果、GPT 审查状态。
- 不直接部署生产环境。
- 不直接合并 PR。
- 交付时输出修改摘要、测试结果、风险说明。
- 交付时生成一段可直接复制给 GPT 的审查提示词。
- 如果收到 GPT 审查意见，必须在当前 PR 分支继续返工，不要新建分支。
- 返工后追加 commit，并生成给 GPT 二审的提示词。
- 优先级：稳定性 > 可维护性 > 性能优化 > 代码优雅。
- 交易、下单、API key、缓存、定时任务、Docker、Nginx、端口、防火墙相关改动必须保守处理。

## Project Shape

- 后端主栈：Python 3.11+。
- Web Admin：FastAPI + Jinja2 模板 + 原生 CSS。
- 主要服务：
  - `trading-bot`：paper 模拟盘循环。
  - `alert-radar`：行情雷达扫描循环。
  - `admin-web`：Web 管理后台。
- 配置模板写入 `.env.example` 或 `.env.production.example`，真实环境值只放 `.env`。

## Network & Proxy

- 外部访问包括 Binance、Telegram、GitHub、pip/npm/Docker Hub、网页抓取等。
- 直连失败、超时、DNS 失败、TLS 失败、`ECONNRESET`、`ETIMEDOUT`、`fetch failed` 时，不要立刻判定代码失败；先判断是否是网络环境问题。
- 本地访问 Binance 通常需要代理；生产 Vultr 日本区通常直连。
- 代理配置只能来自环境变量或 `.env`，不要硬编码到业务代码。
- 本地推荐：

```env
EXCHANGE_NETWORK_MODE=proxy
EXCHANGE_PROXY=http://127.0.0.1:7890
TELEGRAM_PROXY=http://127.0.0.1:7890
TELEGRAM_ORDER_PROXY=http://127.0.0.1:7890
NO_PROXY=localhost,127.0.0.1,::1
```

- 生产推荐：

```env
EXCHANGE_NETWORK_MODE=direct
EXCHANGE_PROXY=
TELEGRAM_PROXY=
TELEGRAM_ORDER_PROXY=
```

- `EXCHANGE_NETWORK_MODE` 可选：`direct`、`proxy`、`direct_fallback`、`proxy_fallback`。

## Telegram

- 雷达信号和订单/执行通知必须隔离。
- 雷达通知使用 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`。
- 模拟下单、paper cycle 错误等执行类通知使用 `TELEGRAM_ORDER_ENABLED`、`TELEGRAM_ORDER_BOT_TOKEN`、`TELEGRAM_ORDER_CHAT_ID`、`TELEGRAM_ORDER_PROXY`。
- 单次 Binance 抖动不应频繁推送 Telegram；连续失败阈值由 `PAPER_ERROR_NOTIFY_CONSECUTIVE_FAILURES` 控制。

## Radar Rules

- 雷达规则采用插件式结构，优先在 `app/alerts/rules/` 中新增或修改。
- 规则阈值和开关优先放在 `config/radar_rules.yaml` 或 `.env`，不要写死在规则逻辑里。
- 新规则应声明所需 K 线周期、OI 周期和 funding 需求，让 scanner 合并请求。
- 不要把扫描逻辑退回到全市场全周期暴力轮询。
- 保持候选池、TTL 缓存、增量 K 线、受限并发、限流退避和 profiling 日志。
- 低命中率排查先看 `diagnostic_*` 日志，区分候选池覆盖不足、数据缺失、规则阈值过严。

## Web Admin

- 不引入 Ant Design、MUI、shadcn/ui 等重型组件库，除非项目已经深度依赖。
- UI 保持暗色交易工具台风格：背景 `#101318`、面板 `#171B22`、边框 `#2B313B`、买入/主操作 `#20C997`、风险/下跌 `#FF5C73`、警告 `#F2B84B`。
- 页面应像 SaaS/交易后台，不做营销 landing page。
- 表格默认需要分页、搜索、排序、行数选择；长数字和长文本要紧凑展示。
- 新页面应加入 `app/web/templates/base.html` 导航，并在 `app/web/server.py` 中保持鉴权依赖。

## Paper Trading

- `PaperTradingEngine` 只做模拟下单，不应触发真实交易。
- 修改下单逻辑时检查重复开仓、止损必填、订单/持仓/交易记录一致性、Telegram order bot 隔离。
- 模拟盘收益统计相关修改应同步覆盖 Orders / Positions / Trades 页面和 SQLite 聚合查询。

## Testing

- 常用全量测试：

```bash
.venv/bin/python -m pytest -q
```

- 局部测试示例：

```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_exchange.py tests/test_main.py -q
```

- 本地 Web 后台：

```bash
./scripts/start_web.sh
```

## Deployment Safety

- 生产目录通常是 `/home/vesper/apps/Trading-Bot`。
- 同步生产前先跑相关测试，并确认不会覆盖生产 `.env`、`data/`、`logs/`、`backtests/`、`reports/`。
- `rsync` 排除根目录运行数据时使用 `/data/`、`/logs/` 这种 anchored pattern，不要误排除 `app/data/` 代码模块。
- 发布后至少检查 `docker compose ps`、`admin-web` 可访问、`trading-bot` 网络模式、`alert-radar` 是否完成一轮 `[radar-loop]`。

## Git Hygiene

- 不要提交 `.env`、`.venv/`、`data/`、`logs/`、`backtests/`、`reports/`、`__pycache__/`、`.pytest_cache/`。
- 触及共享逻辑时跑全量测试。
- 若生产热修了代码，必须同步回本地并提交，保持本地、远端、生产一致。
