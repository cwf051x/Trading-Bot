# Trading-Bot Project Context

本文是新 Codex 对话的项目启动页，只记录当前 `main` 分支的稳定事实。详细开发硬规则见 `AGENTS.md`，PR 审查闭环见 `docs/ai-review-workflow.md`，运行和配置细节以 `README.md` 为准。

## 1. 项目定位

Trading-Bot 是 Python 3.11+ 的 Binance USDT-M Futures 行情雷达与模拟交易系统。当前阶段以行情监控、雷达信号、Telegram 通知、回测、paper 模拟盘、SQLite 记录和 FastAPI/Jinja2 Web Admin 为主。

默认不做真实交易。`live` 模式和真实下单能力不能被当作普通配置随手打开；任何涉及资金、仓位、下单、API key、服务器和网络暴露面的改动都必须保守处理。

## 2. 当前 main 已具备的关键能力

- 配置系统：`.env` 读取运行配置，模板在 `.env.example` / `.env.production.example`，真实密钥不提交。
- Binance 行情客户端：支持 K 线、ticker、资金费率、Open Interest、本地代理和生产直连配置。
- 行情雷达：`scanner` 负责候选池、缓存、并发、profiling 和指标构建；`rules` 插件式运行；`digest` 聚合 Telegram 热榜。
- Paper 模拟盘：支持多币种轮询、已完成 K 线 high/low 止损止盈、SQLite 记录、风控拦截和订单通知隔离。
- SQLite 存储：保存 alerts、orders、positions、trades、state 和 Web Admin 查询数据。
- Telegram：雷达提醒和订单/执行通知分离，单次外部接口抖动不应刷屏。
- Web Admin：FastAPI + Jinja2 + 原生 CSS 的暗色交易工具台。
- 回测与 replay：支持 CSV 回测、雷达历史数据回放和基础可信度验证。
- Docker/部署说明：已有 Docker Compose、Vultr 部署说明，但生产部署必须由用户明确要求。

## 3. 当前雷达体系

`config/radar_rules.yaml` 是当前雷达规则阈值和开关的主要来源。

- `volume_price_oi`：量价 OI 共振体系。
  - L0：早期观察层。价格涨幅是硬门槛，成交量或 OI 至少一个提供质量确认；默认不 auto paper、不单条强推 Telegram，可入库并进入 digest。
  - L1/L2/L3：量价 OI 共振拉升层级。
- `hourly_trend`：小时级单边趋势雷达。
  - T1/T2/T3/T4 分别表示趋势启动、趋势加速、回踩接多观察和高位过热风险。
- `pump_pullback_second_wave`：爆拉后健康回调 + 二波启动雷达。
  - P1/P2/P3/P4 分别表示健康回调观察、二波启动预警、二波确认突破和二波失败风险。

命名边界必须保持清晰：L0 不能写成 T0；T 系列只属于 `hourly_trend`；P 系列只属于 `pump_pullback_second_wave`。

## 4. 当前 Telegram Digest 行为

- `ALERT_DIGEST_INTERVAL_SECONDS=900`：控制发送频率，默认每 15 分钟最多一条。
- `ALERT_DIGEST_LOOKBACK_SECONDS=14400`：主热榜默认统计最近 4 小时。
- `ALERT_DIGEST_ACTIVE_SECONDS=3600`：用于活跃度加减分，不硬过滤旧 alert。
- `ALERT_DIGEST_NEWCOMER_SECONDS=900`：最近新晋异动窗口。
- `ALERT_DIGEST_NEWCOMER_TOP_N=5`：新晋异动默认最多展示 5 个。

Digest 是通用聚合能力，兼容 `volume_price_oi`、`hourly_trend`、`pump_pullback_second_wave` 和未来 alert type。它尊重每条 alert metadata 中的 `digest` 和 `min_score_to_digest`。当前文案使用“涨幅排名”，不要写成“成交额排名”，除非未来真正实现成交额排名。

## 5. 安全边界

- 默认不真实交易，禁止把真实交易当普通配置打开。
- 不提交 `.env`、API key、token、secret、chat id、代理地址或生产私有配置。
- 不部署生产，除非用户明确要求。
- 不修改 Docker、Nginx、端口、防火墙、证书，除非用户明确要求。
- 涉及交易、下单、资金、仓位、止损止盈、API key、缓存、定时任务、数据库、Docker、Nginx、端口、防火墙的改动必须保守、小步、可验证。

## 6. 新 Codex 对话启动规则

每个新功能、新 PR 或新阶段，建议新开 Codex 对话。新对话开始时，Codex 必须先阅读：

1. `PROJECT_CONTEXT.md`
2. `AGENTS.md`
3. `docs/ai-review-workflow.md`
4. `README.md`
5. 与本次任务相关的源码和配置文件

## 7. 标准开发流程

从最新 `main` 新建独立分支，小步修改，先跑相关窄测试，再按风险扩大验证。完成后提交 commit、创建或更新 PR，并输出修改摘要、测试结果、风险说明和可复制给 GPT 的审查提示词。若 GPT 要求返工，必须在同一 PR 分支追加 commit。是否合并和部署由用户决定。

详细流程见 `docs/ai-review-workflow.md`。

## 8. 常用测试命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall app scripts tests
.venv/bin/python scripts/check_no_real_trading_calls.py
docker compose config >/tmp/trading-bot-compose-config.txt
```

根据任务追加局部测试，例如：

```bash
.venv/bin/python -m pytest tests/test_config.py -q
```

## 9. 新任务提示词模板

```text
你现在在 Trading-Bot 项目的新 Codex 对话中工作。

请先阅读并遵守：
- PROJECT_CONTEXT.md
- AGENTS.md
- docs/ai-review-workflow.md
- README.md

本次任务：
<粘贴任务>

要求：
1. 从最新 main 新建独立分支。
2. 不直接修改 main/master。
3. 不直接合并 PR。
4. 不部署生产。
5. 不新增真实下单能力。
6. 不修改 API key/token/env secret。
7. 不修改 Docker/Nginx/端口/防火墙，除非本任务明确要求。
8. 不扩大修改范围。
9. 完成后创建 PR，并输出修改摘要、测试结果、风险说明和给 GPT 的审查提示词。
```
