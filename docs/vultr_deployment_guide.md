# Vultr Ubuntu 部署上线教程

本文档用于把当前交易系统部署到 Vultr 日本区 Ubuntu VPS。当前版本只运行行情雷达、模拟盘、SQLite 记录、Telegram 通知和管理后台，不具备真实下单能力。

## 1. 部署目标

上线后建议运行 3 个服务：

- `alert-radar`：持续扫描 Binance USDT-M Futures 行情并发送 Telegram 提醒。
- `trading-bot`：模拟盘 paper 服务，保留策略信号、风控和模拟记录。
- `admin-web`：管理后台，只绑定服务器本机 `127.0.0.1:8000`，通过 SSH 隧道访问。

生产环境默认配置：

```dotenv
RUN_MODE=paper
ENABLE_LIVE_TRADING=false
EXCHANGE_PROXY=
TELEGRAM_PROXY=
WEB_HOST=127.0.0.1
WEB_PORT=8000
```

日本区 Vultr 通常不需要 Clash 代理，因此 `EXCHANGE_PROXY` 和 `TELEGRAM_PROXY` 保持为空。

## 2. 上线前你需要准备

### 2.1 Vultr 服务器

建议配置：

- Region：Japan
- OS：Ubuntu 24.04 LTS 或 Ubuntu 22.04 LTS
- CPU/RAM：初期 1 vCPU / 1GB RAM 可以试跑，建议 2GB RAM 更稳。
- Disk：25GB 以上。

记录好：

- 服务器公网 IP
- root 密码或 SSH key

### 2.2 Telegram

准备：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

部署后用它接收：

- 系统错误提醒
- A/B/C 级行情雷达提醒
- 模拟盘通知

### 2.3 Binance API

第一阶段行情雷达只需要公开行情，不需要 API Key。  
如果后续你仍想配置 Binance Key，建议：

- 子账户 API
- 只读权限
- 绑定 Vultr VPS 公网 IP
- 不开启现货/合约交易权限
- 不把 Key 写入代码，只写服务器 `.env`

## 3. 本地代码入库

在本机项目目录确认测试通过：

```bash
cd /Users/chenweifeng/Documents/Trading-Bot
source .venv/bin/activate
python -m pytest
docker compose config --quiet
```

确认 `.env` 没有被 git 跟踪：

```bash
git status --short --ignored
```

提交代码：

```bash
git add .
git commit -m "Add market alert radar and Vultr deployment guide"
```

推送到你的 Git 仓库：

```bash
git remote -v
git push origin main
```

如果你还没有远程仓库，先在 GitHub/GitLab 创建空仓库，然后：

```bash
git remote add origin git@github.com:你的用户名/Trading-Bot.git
git push -u origin main
```

不要提交：

- `.env`
- `data/`
- `backtests/`
- `logs/`
- `.venv/`

这些已经在 `.gitignore` 中忽略。

## 4. 登录 Vultr 服务器

```bash
ssh root@你的Vultr公网IP
```

更新系统：

```bash
apt update
apt upgrade -y
```

安装基础工具：

```bash
apt install -y git curl ca-certificates nano ufw
```

## 5. 建议创建非 root 用户

创建运维用户：

```bash
adduser trader
usermod -aG sudo trader
```

复制 SSH key 到新用户：

```bash
rsync --archive --chown=trader:trader ~/.ssh /home/trader
```

切换用户：

```bash
su - trader
```

后续命令建议在 `trader` 用户下执行。

## 6. 安装 Docker 和 Compose

官方 Docker 安装方式：

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

添加 Docker apt 源：

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
```

安装：

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

允许当前用户使用 Docker：

```bash
sudo usermod -aG docker "$USER"
```

重新登录 SSH，让 docker 用户组生效：

```bash
exit
ssh trader@你的Vultr公网IP
```

验证：

```bash
docker --version
docker compose version
docker run --rm hello-world
```

## 7. 配置防火墙

只开放 SSH：

```bash
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

不要开放 `8000`。管理后台使用 SSH 隧道访问。

## 8. 拉取项目代码

```bash
mkdir -p ~/apps
cd ~/apps
git clone git@github.com:你的用户名/Trading-Bot.git
cd Trading-Bot
```

如果服务器没有配置 GitHub SSH key，也可以临时用 HTTPS：

```bash
git clone https://github.com/你的用户名/Trading-Bot.git
```

## 9. 创建生产 `.env`

```bash
cp .env.production.example .env
nano .env
```

重点检查这些项：

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

DATABASE_PATH=data/trading_bot.sqlite
RUN_MODE=paper
ENABLE_LIVE_TRADING=false

EXCHANGE_PROXY=
TELEGRAM_PROXY=

ACCOUNT_EQUITY=1000
WATCH_SYMBOLS=BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,PIPPIN/USDT:USDT,GENIUS/USDT:USDT

WEB_ADMIN_TOKEN=一串足够长的随机字符串
WEB_HOST=127.0.0.1
WEB_PORT=8000

ALERT_RADAR_ENABLED=true
ALERT_SCAN_INTERVAL_SECONDS=60
ALERT_MIN_24H_QUOTE_VOLUME_USDT=10000000
ALERT_SEND_A_LEVEL=true
ALERT_SEND_B_LEVEL=true
ALERT_SEND_C_LEVEL=false
```

生成 `WEB_ADMIN_TOKEN`：

```bash
openssl rand -hex 32
```

生产环境建议：

- `ALERT_SEND_C_LEVEL=false`，避免太吵。
- `ALERT_COOLDOWN_B_SECONDS=1200`，B 级 20 分钟冷却。
- `ALERT_WATCHLIST=` 留空时扫描全部高流动性 USDT 永续；刚上线可以先填少量币观察稳定性。

## 10. 创建数据目录

```bash
mkdir -p data backtests logs
```

## 11. 配置检查

```bash
docker compose config --quiet
```

如果没有输出，说明 Compose 配置语法通过。

## 12. 构建镜像

```bash
docker compose build
```

首次构建会下载 Python 3.11 镜像和依赖，可能需要几分钟。

## 13. 启动前冒烟测试

测试 Python 导入和数据库建表：

```bash
docker compose run --rm trading-bot python -m compileall app scripts
```

测试 Telegram 格式，不访问 Binance：

```bash
docker compose run --rm alert-radar python scripts/test_alert_radar.py
```

跑一轮真实行情雷达：

```bash
docker compose run --rm alert-radar python scripts/run_alert_radar_once.py
```

如果 Telegram 正常，你会收到 A/B 级提醒；如果当前行情没有触发，终端会显示本轮生成的 alert 数。

## 14. 正式启动

```bash
docker compose up -d
```

查看服务：

```bash
docker compose ps
```

看雷达日志：

```bash
docker compose logs -f alert-radar
```

看模拟盘日志：

```bash
docker compose logs -f trading-bot
```

看后台日志：

```bash
docker compose logs -f admin-web
```

## 15. 访问管理后台

因为后台只绑定服务器本机地址，你需要在本机开 SSH 隧道：

```bash
ssh -L 8000:127.0.0.1:8000 trader@你的Vultr公网IP
```

保持这个 SSH 窗口不要关，然后在本机浏览器打开：

```text
http://127.0.0.1:8000
```

如果配置了 `WEB_ADMIN_TOKEN`，登录时输入该 token。

后台页面：

- Dashboard：模拟盘概况。
- Settings：修改 watchlist、雷达阈值、冷却期。
- Alerts：查看雷达提醒、是否推送 Telegram、建议动作。
- Backtests / Equity：回测和收益曲线。
- Orders / Positions / Trades：模拟盘记录。

保存 Settings 后，需要重启服务才会读取新 `.env`：

```bash
docker compose restart alert-radar trading-bot
```

## 16. 查看 SQLite 记录

进入服务器项目目录：

```bash
cd ~/apps/Trading-Bot
```

查看最近雷达提醒：

```bash
sqlite3 data/trading_bot.sqlite "select datetime(timestamp/1000,'unixepoch','localtime'),symbol,alert_type,level,score,price,sent_to_telegram,suggested_action from market_alerts order by id desc limit 20;"
```

查看状态：

```bash
sqlite3 data/trading_bot.sqlite "select symbol,state,last_alert_type,last_alert_score,last_alert_price,datetime(last_alert_at/1000,'unixepoch','localtime') from alert_states order by symbol;"
```

## 17. 日常运维命令

更新代码：

```bash
cd ~/apps/Trading-Bot
git pull
docker compose build
docker compose up -d
```

重启雷达：

```bash
docker compose restart alert-radar
```

停止全部服务：

```bash
docker compose down
```

查看资源：

```bash
docker stats
df -h
free -h
```

查看最近日志：

```bash
docker compose logs --tail=100 alert-radar
```

## 18. 备份数据库

手动备份：

```bash
mkdir -p backups
cp data/trading_bot.sqlite "backups/trading_bot_$(date +%Y%m%d_%H%M%S).sqlite"
```

下载到本机：

```bash
scp trader@你的Vultr公网IP:~/apps/Trading-Bot/data/trading_bot.sqlite ./trading_bot.sqlite
```

## 19. 安全检查清单

上线前确认：

- `.env` 没有提交到 Git。
- `ENABLE_LIVE_TRADING=false`。
- `RUN_MODE=paper`。
- `EXCHANGE_PROXY=`，日本区服务器通常不需要代理。
- `TELEGRAM_PROXY=`。
- `WEB_ADMIN_TOKEN` 不是 `change-me`。
- 防火墙没有开放 `8000`。
- 后台通过 SSH 隧道访问。
- Binance API Key 如果配置，只读、绑定 VPS IP、不开放交易权限。

## 20. 常见问题

### Telegram 没收到

检查：

```bash
docker compose logs --tail=100 alert-radar
```

确认：

- Bot token 正确。
- Chat ID 正确。
- 你已经给 bot 发过 `/start`。
- `.env` 中 `TELEGRAM_PROXY=` 为空。

### Binance 行情失败

查看日志：

```bash
docker compose logs --tail=100 alert-radar
```

如果服务器无法访问 Binance，再考虑加代理；正常日本区 Vultr 不需要。

### 提醒太少

可以逐步降低：

```dotenv
ALERT_MIN_24H_QUOTE_VOLUME_USDT=5000000
ALERT_VOLUME_RATIO_THRESHOLD=1.5
ALERT_SEND_C_LEVEL=true
```

修改后重启：

```bash
docker compose restart alert-radar
```

### 提醒太多

可以提高：

```dotenv
ALERT_VOLUME_RATIO_THRESHOLD=2.0
ALERT_COOLDOWN_B_SECONDS=1800
ALERT_SEND_C_LEVEL=false
```

修改后重启：

```bash
docker compose restart alert-radar
```

## 21. 参考资料

- Docker 官方 Ubuntu 安装文档：https://docs.docker.com/engine/install/ubuntu/
- Docker Compose 官方文档：https://docs.docker.com/compose/
- Binance Academy 风险管理与技术分析内容：https://academy.binance.com/
- Investopedia 突破交易、风险管理和技术分析内容：https://www.investopedia.com/

这些资料只用于改进行情雷达启发式规则。系统输出仍然只是行情提醒，不是交易建议或交易指令。
