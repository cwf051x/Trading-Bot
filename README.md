# Crypto USDT-M Futures Trading Bot

Python >=3.11,<3.13 加密货币 USDT-M 永续合约交易系统骨架。第一阶段只接 Binance USDT-M Futures，默认只做行情监控、策略信号、回测、模拟盘、SQLite 记录和 Telegram 通知。

**重要提示：默认不进行真实交易。** `live` 模式在 v1 中仍会被阻止，所有下单相关代码默认处于模拟模式。

## 功能

- 配置从 `.env` 读取，不硬编码 API Key。
- Binance USDT-M 行情：K 线、现价、24h 涨跌幅榜、资金费率、Open Interest 预留接口。
- 标准策略接口和 `MomentumOIStrategy` 示例策略。
- 风控：止损必填、单笔 1% 风险、单币 5% 仓位上限、连续亏损冷却、BTC 急跌禁止开多。
- 模拟盘：多币种轮询、模拟开仓、止损、止盈、账户余额/保证金/盈亏统计、SQLite 交易记录。
- 回测：CSV K 线输入，输出胜率、盈亏比、最大回撤、交易次数、收益曲线。
- Telegram：启动、策略信号、模拟下单、风控拦截、异常错误通知。
- Market Alert Radar：扫描 Binance USDT-M 涨幅榜、短周期异动、连续突破、强势回调、回调二启和高位风险，只提醒不下单。
- Minute Runner Radar：跟踪 5m/15m/1h 分钟级单边上涨池，统一推送池榜；早期确信池可选邮件强提醒，默认关闭。

## 安装

```bash
python3.11 --version
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 配置

```bash
cp .env.example .env
```

编辑 `.env`：

```dotenv
# Python runtime: >=3.11,<3.13
BINANCE_API_KEY=
BINANCE_API_SECRET=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_PROXY=
TELEGRAM_ORDER_ENABLED=true
TELEGRAM_ORDER_BOT_TOKEN=
TELEGRAM_ORDER_CHAT_ID=
TELEGRAM_ORDER_PROXY=
DATABASE_PATH=data/trading_bot.sqlite
RUN_MODE=paper
ENABLE_LIVE_TRADING=false
BTC_DROP_THRESHOLD_15M=0.03
ACCOUNT_EQUITY=10000
DEFAULT_SYMBOL=BTC/USDT:USDT
WATCH_SYMBOLS=BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT
DEFAULT_TIMEFRAME=15m
EXCHANGE_NETWORK_MODE=direct
EXCHANGE_PROXY=
EXCHANGE_REQUEST_RETRIES=2
EXCHANGE_RETRY_DELAY_SECONDS=1
POLL_INTERVAL_SECONDS=60
PAPER_ERROR_NOTIFY_CONSECUTIVE_FAILURES=3
KLINE_LIMIT=120
PAPER_LEVERAGE=1
PAPER_FEE_RATE=0
PAPER_SLIPPAGE_PCT=0
PAPER_FUNDING_RATE=0
RISK_MAX_TOTAL_EXPOSURE_PCT=0.50
RISK_MAX_OPEN_POSITIONS=10
RISK_MAX_SYMBOL_POSITION_PCT=0.05
RISK_PER_TRADE_PCT=0.01
RISK_MAX_CONSECUTIVE_LOSSES=3
RISK_LOSS_COOLDOWN_SECONDS=3600
STRATEGY_BREAKOUT_WINDOW=20
STRATEGY_VOLUME_WINDOW=20
STRATEGY_VOLUME_MULTIPLIER=1.5
STRATEGY_STOP_LOSS_PCT=0.02
STRATEGY_TAKE_PROFIT_PCT=0.04
WEB_ADMIN_TOKEN=
WEB_HOST=127.0.0.1
WEB_PORT=8000
ALERT_RADAR_ENABLED=true
ALERT_AUTO_PAPER_TRADING_ENABLED=false
ALERT_SCAN_INTERVAL_SECONDS=60
ALERT_TOP_GAINERS_LIMIT=30
ALERT_MAX_ALERTS_PER_CYCLE=5
ALERT_MIN_SCORE_TO_STORE=70
ALERT_MIN_24H_QUOTE_VOLUME_USDT=10000000
ALERT_BLACKLIST=
ALERT_WATCHLIST=
ALERT_SEND_A_LEVEL=true
ALERT_SEND_B_LEVEL=true
ALERT_SEND_C_LEVEL=false
ALERT_COOLDOWN_A_SECONDS=300
ALERT_COOLDOWN_B_SECONDS=600
ALERT_COOLDOWN_C_SECONDS=1800
ALERT_SURGE_3M_THRESHOLD=0.015
ALERT_SURGE_5M_THRESHOLD=0.025
ALERT_SURGE_15M_THRESHOLD=0.04
ALERT_VOLUME_RATIO_THRESHOLD=1.8
ALERT_PULLBACK_MIN_RATIO=0.05
ALERT_PULLBACK_MAX_RATIO=0.15
ALERT_BTC_DUMP_15M_THRESHOLD=-0.008
ALERT_HIGH_RISK_15M_CHANGE=0.08
ALERT_HIGH_RISK_1H_CHANGE=0.18
ALERT_MIN_BREAKOUT_CLOSE_POSITION=0.65
ALERT_SECOND_LEG_MIN_CLOSE_POSITION=0.55
ALERT_PULLBACK_VOLUME_CONTRACTION_MAX=1.0
ALERT_OVERHEAT_RSI=82
ALERT_FUNDING_RATE_TTL_SECONDS=900
MINUTE_RUNNER_ENABLED=true
MINUTE_RUNNER_TELEGRAM_ENABLED=true
MINUTE_RUNNER_DIGEST_INTERVAL_SECONDS=300
MINUTE_RUNNER_DIGEST_NO_CHANGE_INTERVAL_SECONDS=900
MINUTE_RUNNER_DIGEST_TOP_N=8
MINUTE_RUNNER_MIN_SCORE_TO_SHOW=72
MINUTE_RUNNER_EMAIL_ENABLED=false
MINUTE_RUNNER_EMAIL_TO=
MINUTE_RUNNER_EMAIL_FROM=
MINUTE_RUNNER_EMAIL_PROVIDER=qq_agent
MINUTE_RUNNER_EMAIL_GLOBAL_COOLDOWN_SECONDS=1800
MINUTE_RUNNER_EMAIL_MAX_PER_HOUR=2
MINUTE_RUNNER_EMAIL_MIN_SCORE=88
MINUTE_RUNNER_EMAIL_TOP_RANK=5
```

不要提交 `.env`。项目已在 `.gitignore` 中排除该文件。

`EXCHANGE_NETWORK_MODE` 决定 Binance 行情接口的网络路径：`direct` 强制直连，`proxy` 强制代理，`direct_fallback` 先直连失败后代理，`proxy_fallback` 先代理失败后直连。本地如果直连 Binance 必失败，建议使用 `EXCHANGE_NETWORK_MODE=proxy`，避免每个请求先等待直连超时；Vultr 日本区生产环境建议使用 `direct`。

`EXCHANGE_PROXY` 是 Binance 行情接口代理地址，只在 `proxy` / `direct_fallback` / `proxy_fallback` 模式下使用。本机直接运行通常使用 `http://127.0.0.1:7890`，Docker/Colima 容器里才需要改成宿主机代理地址，例如 `http://192.168.5.2:7890`。生产直连时留空。

`EXCHANGE_REQUEST_RETRIES` 和 `EXCHANGE_RETRY_DELAY_SECONDS` 用于处理 Binance 偶发 K 线/ticker/OI 请求抖动。生产建议保留 `2` 次短重试，避免单次 `klines` 请求失败导致整轮 paper cycle 报错。

`PAPER_ERROR_NOTIFY_CONSECUTIVE_FAILURES` 控制 paper cycle 错误通知阈值。默认连续失败 3 次才推送 Telegram；单次 Binance 请求抖动只写日志，避免误报刷屏。

`RISK_MAX_CONSECUTIVE_LOSSES` 控制连续亏损达到多少笔后暂停新开仓；`RISK_LOSS_COOLDOWN_SECONDS` 控制暂停时长，默认 3600 秒。设置为 `0` 时会保留旧行为：连续亏损状态会一直阻断新开仓，直到最近平仓记录被盈利交易打断。

`ALERT_AUTO_PAPER_TRADING_ENABLED` 默认是 `false`，行情雷达只提醒、不自动建立模拟仓。只有明确要观察雷达信号自动下单表现时才开启；开启后必须确保只有一个 writer 服务负责写 paper orders，避免 `trading-bot` 和 `alert-radar` 重复建仓。雷达规则阈值以 `config/radar_rules.yaml` 为准，旧的 `ALERT_HOURLY_*` 环境变量不再作为真实规则来源。

模拟盘和平仓回测都按已完成 K 线的 `high` / `low` 判断止损止盈；同一根 K 线同时触发止损和止盈时保守按止损处理，避免未完成 K 线或乐观成交顺序造成收益高估。

`TELEGRAM_PROXY` 用于让 Telegram 通知请求强制走代理。本机运行通常使用 `http://127.0.0.1:7890`；Docker/Colima 容器里才需要改成宿主机代理地址，例如 `http://192.168.5.2:7890`。

`TELEGRAM_ORDER_*` 用于把模拟下单流水从雷达信号频道隔离出去。未填写订单专用 Token/Chat ID 时会回退到 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`；如果想保留雷达提醒但关闭订单流水通知，设置 `TELEGRAM_ORDER_ENABLED=false`。

`WATCH_SYMBOLS` 是 paper 模式实际轮询的交易对列表，使用逗号分隔；未配置时会回退到 `DEFAULT_SYMBOL`。`PAPER_LEVERAGE` 只用于模拟账户的保证金统计，不会触发真实杠杆设置。

`ALERT_WATCHLIST` 是行情雷达专用白名单，留空时扫描全部符合流动性要求的 USDT 永续合约；`ALERT_BLACKLIST` 用于排除不想提醒的交易对。两者都支持 `BTCUSDT` 或 `BTC/USDT:USDT` 写法。

行情雷达规则采用插件式结构：每个规则声明自己需要的 K 线周期、OI 周期和资金费率，scanner 会按启用规则合并请求。底层 K 线、OI、funding 的 TTL 缓存、增量刷新、受限并发和限流退避集中在 `MarketDataService`，scanner 只负责编排候选池、构建指标和运行规则。规则阈值和开关以 `config/radar_rules.yaml` 为准；`.env` 继续用于密钥、端口、运行模式等部署参数。

候选池先用 24h ticker 做轻量筛选，再按涨幅榜、成交额榜、最近 ticker 涨幅榜和 hot/watchlist 分桶合并。默认 `ALERT_CANDIDATE_TOP_N=80`，`ALERT_OI_TOP_N=50`，`ALERT_OI_MAX_REFRESH_PER_LOOP=30`，用于减少漏扫同时避免每轮回到全市场重拉 OI。

radar-loop profiling 会输出 `scan_timeframes`、`scan_oi_periods`、`scan_requires_funding`，用于确认本轮只采集启用规则声明的数据需求；同时输出 `diagnostic_*` 字段，例如 `diagnostic_resonance_stats`、`diagnostic_trend_stats`、`diagnostic_pump_has_first_pump` 和各规则关键闸口计数，用来判断低命中是数据覆盖不足还是规则条件过严。

`ALERT_DIGEST_ENABLED=true` 时，radar loop 会按 `ALERT_DIGEST_INTERVAL_SECONDS` 默认每 15 分钟发送一次 Telegram 热榜。digest 发送间隔和统计窗口是两个概念：`ALERT_DIGEST_INTERVAL_SECONDS` 控制多久推送一次；`ALERT_DIGEST_LOOKBACK_SECONDS` 控制主热榜回看多长时间，默认 14400 秒，也就是主榜统计过去 4 小时；`ALERT_DIGEST_NEWCOMER_SECONDS` 控制“最近新晋异动”模块，默认 900 秒；`ALERT_DIGEST_ACTIVE_SECONDS` 控制主榜活跃度降权窗口，默认 3600 秒。热榜默认取 `ALERT_DIGEST_TOP_N=10`，新晋异动默认取 `ALERT_DIGEST_NEWCOMER_TOP_N=5`，最低入榜分数 `ALERT_DIGEST_MIN_SCORE=60`；它不影响单条 alert 入库，也不扩大自动模拟下单范围。

`MINUTE_RUNNER_ENABLED=true` 时，Minute Runner Radar 会复用 scanner 已声明采集的 5m/15m/1h K 线、5m OI 和 funding，不新增全市场暴力请求；当前阶段 3m 不参与该池判断，因此不会为 Minute Runner 额外拉取 3m K 线。它维护 `minute_runner_states` 状态池：M0 启动观察、M1 单边上涨池、M2E 早期确信池、M2M 成熟确信、M3 过热防追高、M4 趋势破坏。`MINUTE_RUNNER_TELEGRAM_ENABLED=true` 时按 `MINUTE_RUNNER_DIGEST_INTERVAL_SECONDS` 默认每 5 分钟推送一次非空池榜；无变化时按 `MINUTE_RUNNER_DIGEST_NO_CHANGE_INTERVAL_SECONDS` 限频。`MINUTE_RUNNER_EMAIL_ENABLED=false` 默认关闭邮件，开启后只会在首次进入 M2E、未过热/未破位、满足排名或分数门槛时尝试发送邮件，并受全局 30 分钟和每小时 2 封限制。邮件发送失败或限频跳过会记录到池状态，不影响 radar loop。

`config/radar_rules.yaml` 当前包含：

- `volume_price_oi`：量价 OI 共振拉升雷达，覆盖 L0/L1/L2/L3；L0 是早期观察层，价格涨幅是硬门槛，成交量和 OI 只做质量加分，默认不自动 paper、不单条强推 Telegram，只入库并进入 15 分钟热榜。
- `hourly_trend`：小时级单边趋势雷达，覆盖 T1/T2/T3/T4。
- `pump_pullback_second_wave`：爆拉后健康回调 + 二波启动雷达，覆盖 P1/P2/P3/P4。
- `minute_runner`：分钟级单边上涨池，覆盖 M0/M1/M2E/M2M/M3/M4；只维护池榜和邮件提醒，不生成自动下单信号。

## 运行回测

CSV 字段必须为：

```text
timestamp,open,high,low,close,volume
```

运行：

```bash
python -m app.main --mode backtest --csv backtests/sample.csv --equity-curve-csv backtests/equity_curve.csv
```

## 运行模拟盘

```bash
python -m app.main --mode paper
```

模拟盘会按 `POLL_INTERVAL_SECONDS` 持续轮询 `WATCH_SYMBOLS` 中的 Binance 行情，生成策略信号，通过风控后写入 SQLite，并发送 Telegram 通知。如果没有配置 Telegram，通知会写入日志。每轮结束会在日志里输出模拟账户权益、可用余额、已用保证金、已实现盈亏、浮动盈亏和当前持仓数。

调试时可以只跑一轮：

```bash
python -m app.main --mode paper --once
```

## 行情信号雷达

Market Alert Radar 用来持续扫描 Binance USDT-M Futures，识别：

- 涨幅榜强势币：`TOP_GAINER_MOMENTUM`
- 3m/5m/15m 短周期异动：`SHORT_TERM_SURGE`
- 多周期连续突破：`MULTI_TIMEFRAME_BREAKOUT`
- 强势币回调观察：`STRONG_PULLBACK_WATCH`
- 回调后二次启动：`PULLBACK_SECOND_LEG`
- 高位加速风险：`HIGH_RISK_EXTENSION`

单轮扫描：

```bash
python scripts/run_alert_radar_once.py
```

循环扫描：

```bash
./scripts/start_radar_loop.sh
```

该脚本会把终端输出同时追加到 `logs/alert_radar.log`，Web Admin 的 Logs 页面才能持续看到本地 radar loop 新日志。调试时也可以直接运行 `python scripts/run_alert_radar_loop.py`，但裸命令只输出到当前终端，不会自动写入 Web Admin Logs 页面读取的 `logs/*.log`。

模拟盘循环：

```bash
./scripts/start_paper.sh
```

该脚本会把终端输出同时追加到 `logs/trading_bot.log`。

如果 Docker 服务、screen 会话或其他同类 loop 已经在运行，不要再手动启动本地脚本，避免重复 writer 同时写入模拟盘或日志文件。

本地一键启动 Web Admin、行情雷达和模拟盘三个窗口：

```bash
./scripts/start_local_all.sh
```

如需指定 Web Admin 端口：

```bash
./scripts/start_local_all.sh 8010
```

该脚本只负责在 macOS Terminal 中分别打开三个窗口并调用 `start_web.sh`、`start_radar_loop.sh` 和 `start_paper.sh`；原先三个启动脚本仍可单独使用。

注意：该命令会启动 paper 模拟盘 loop，会写入本地 SQLite/日志并访问 Binance 行情 API；如果 Docker、screen 或其他本地 loop 已经在运行，不要重复启动。

本地检查 Telegram 格式，不访问 Binance、不下单：

```bash
python scripts/test_alert_radar.py
```

A级和 B级默认发送 Telegram；C级默认只写入数据库，除非设置 `ALERT_SEND_C_LEVEL=true`。同一个 `symbol + alert_type` 会按等级冷却，默认 A级 10 分钟、B级 20 分钟、C级 60 分钟，避免重复轰炸。

Telegram 示例：

```text
🚨 A级信号：回调二启 / Pullback Second Leg

币种：ALLO/USDT:USDT
现价：0.184200
评分：88/100
建议：回调二启，观察5m收稳后的低风险入场区

短线表现：
3m：+1.20%  5m：+2.10%
15m：+3.80%  1h：+9.50%
24h：+38.60%  BTC15m：-0.10%
量比：2.40x

风险提示：信号仅用于行情提醒，不是交易指令；若BTC突然跳水或5m放量冲高回落，暂停追入。
```

雷达会写入 SQLite：

- `market_alerts`：每条扫描触发的提醒、评分、涨跌幅、量比、建议动作、失效位、目标位、是否发送 Telegram、原始 JSON。
- `alert_states`：每个币的观察状态、上次提醒类型/分数/价格/时间、回调观察前高、支撑和失效位。
- `minute_runner_states`：分钟级单边上涨池状态、趋势年龄、排名分、OI/量能、风险标签和邮件发送/跳过原因。

当前 TODO：资金费率已保留字段但未纳入扫描批量请求；Open Interest 和多空比暂不批量采集，后续可在不影响扫描稳定性的前提下接 Binance REST 或 ccxt 支持接口。

## 管理后台

本地启动管理后台：

```bash
./scripts/start_web.sh
```

打开：

```text
http://127.0.0.1:8011
```

如需指定端口：

```bash
./scripts/start_web.sh 8010
```

启动脚本会先检查目标端口；如果该端口上已经有当前项目的 Web Admin，会先停止旧进程再启动，避免本地同时跑多个后台页面。

后台第一版包含：

- Dashboard：运行模式、真实交易保护状态、监控币对、回测汇总、最近订单/持仓/交易。
- Settings：修改 `WATCH_SYMBOLS`、账户权益、轮询周期和 `MomentumOIStrategy` 参数。
- Backtests：选择 CSV 并运行回测。
- Equity：查看收益曲线。
- Orders / Positions / Trades：查看模拟盘记录。

`Settings` 页面只允许修改白名单字段，不提供 `RUN_MODE=live` 或 `ENABLE_LIVE_TRADING` 开关。保存后会写入 `.env`，需要重启 paper 服务才会被后台交易进程读取。

生产环境建议设置：

```dotenv
WEB_ADMIN_TOKEN=一串长随机字符串
WEB_HOST=127.0.0.1
WEB_PORT=8000
```

通过 Nginx/域名反代 Web Admin 时，必须配置 `WEB_ADMIN_TOKEN`，并让应用仍监听 `127.0.0.1`，由 Nginx 负责公网 80/443、TLS 证书和反向代理。不要把后台服务直接绑定到 `0.0.0.0` 后裸露公网；如果确实配置为非本地监听且 `WEB_ADMIN_TOKEN` 为空，服务会拒绝访问。后台认证只使用安全 cookie/session，不支持 URL query token。

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

默认使用 Python 3.11 镜像运行 `paper` 模式、`admin-web` 管理后台和 `alert-radar` 行情雷达，数据写入宿主机 `./data`。

Docker 默认会持续运行 paper 轮询服务。若只想在容器中跑一轮：

```bash
docker compose run --rm trading-bot python -m app.main --mode paper --once
```

若只想单独启动行情雷达：

```bash
docker compose up -d alert-radar
docker compose logs -f alert-radar
```

管理后台默认只绑定宿主机本地地址：

```text
127.0.0.1:8000
```

Vultr 服务器上可以用 SSH 隧道访问：

```bash
ssh -L 8000:127.0.0.1:8000 root@你的Vultr公网IP
```

然后在本机打开 `http://127.0.0.1:8000`。

## Vultr Ubuntu 生产模拟盘

Vultr 日本区服务器通常可以直接访问 Binance 和 Telegram，生产模拟盘配置里代理应保持为空：

```dotenv
EXCHANGE_NETWORK_MODE=direct
EXCHANGE_PROXY=
EXCHANGE_REQUEST_RETRIES=2
EXCHANGE_RETRY_DELAY_SECONDS=1
TELEGRAM_PROXY=
TELEGRAM_ORDER_ENABLED=true
TELEGRAM_ORDER_BOT_TOKEN=
TELEGRAM_ORDER_CHAT_ID=
TELEGRAM_ORDER_PROXY=
RUN_MODE=paper
ENABLE_LIVE_TRADING=false
PAPER_ERROR_NOTIFY_CONSECUTIVE_FAILURES=3
```

服务器首次部署：

```bash
cp .env.production.example .env
nano .env
./scripts/deploy_vultr_ubuntu.sh
```

`.env.production.example` 是生产模拟盘模板，默认不启用代理，不启用真实交易。编辑 `.env` 时只填服务器实际需要的配置，例如 Telegram Token、Chat ID、账户权益、监控币种和 `WEB_ADMIN_TOKEN`。Binance API Key 在 paper 阶段可以留空；如果填写，建议只使用只读 Key，并绑定 Vultr VPS 公网 IP。

常用运维命令：

```bash
docker compose ps
docker compose logs -f trading-bot
docker compose restart trading-bot
docker compose down
```

更详细的服务器上线步骤见 [Vultr Ubuntu 部署上线教程](docs/vultr_deployment_guide.md)。

## 雷达历史回放

可以回放三个雷达规则，评估命中后的后验收益和及时性。默认用 Binance 下载最近 N 天 5m K 线和 5m/15m/1h OI，并缓存到 `data/replay/`；如果传入本地 CSV，则进入离线模式，不会自动补下载缺失文件。

自动下载示例：

```bash
python scripts/replay_radar_signals.py \
  --symbol BTC/USDT:USDT \
  --days 30 \
  --output reports/radar_replay_BTCUSDT.csv \
  --summary-output reports/radar_replay_BTCUSDT_summary.csv
```

下载缓存文件命名类似：

```text
data/replay/BTCUSDT_klines_5m_30d.csv
data/replay/BTCUSDT_oi_5m_30d.csv
data/replay/BTCUSDT_oi_15m_30d.csv
data/replay/BTCUSDT_oi_1h_30d.csv
```

5m K 线 CSV 需要包含：

```text
timestamp,open,high,low,close,volume
```

OI CSV 可选，需要包含：

```text
timestamp,open_interest
```

离线 CSV 示例：

```bash
python scripts/replay_radar_signals.py \
  --symbol BTC/USDT:USDT \
  --klines-5m data/replay/BTCUSDT_5m.csv \
  --oi-5m data/replay/BTCUSDT_oi_5m.csv \
  --output reports/radar_replay_BTCUSDT.csv \
  --summary-output reports/radar_replay_BTCUSDT_summary.csv
```

明细报告会记录每条信号的 `trigger_price`、未来 15m/30m/1h/4h/24h 收益、最大有利涨幅 `mfe` 和最大不利回撤 `mae`；汇总报告会按 `signal_type` 输出触发次数、1h 胜率、平均收益和 profit factor。

## 测试

```bash
pytest
```

## 真实交易保护

第一版不实现真实下单，也不要把 `ENABLE_LIVE_TRADING` 改为 `true`。`live` 模式会明确退出并提示 live mode 未实现。后续增加真实下单时，必须在执行模块中增加独立开关、风控确认和审计日志。
