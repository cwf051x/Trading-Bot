#!/usr/bin/env bash
# Deploy the paper trading service on Ubuntu with Docker Compose.
# 使用 Docker Compose 在 Ubuntu 上部署模拟盘服务。

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This deployment script is intended for Ubuntu/Linux servers."
  echo "该部署脚本用于 Ubuntu/Linux 服务器。"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  echo "正在安装 Docker..."
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is not available. Please install Docker Compose v2."
  echo "未检测到 Docker Compose v2 插件，请先安装。"
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.production.example ]]; then
    cp .env.production.example .env
    echo "Created .env from .env.production.example."
    echo "已从 .env.production.example 创建 .env。"
  else
    echo ".env.production.example is missing."
    echo "缺少 .env.production.example。"
    exit 1
  fi
fi

mkdir -p data backtests logs

WEB_ADMIN_TOKEN_VALUE="$(grep -E '^WEB_ADMIN_TOKEN=' .env | tail -n 1 | cut -d '=' -f 2- || true)"
if [[ -z "$WEB_ADMIN_TOKEN_VALUE" || "$WEB_ADMIN_TOKEN_VALUE" == "change-me" ]]; then
  echo "Please set WEB_ADMIN_TOKEN in .env before production deployment."
  echo "生产部署前请先在 .env 中设置 WEB_ADMIN_TOKEN。"
  exit 1
fi

echo "Validating Docker Compose configuration..."
echo "正在验证 Docker Compose 配置..."
docker compose config >/dev/null

echo "Building image..."
echo "正在构建镜像..."
docker compose build

echo "Running one paper cycle smoke test..."
echo "正在运行一轮模拟盘冒烟测试..."
docker compose run --rm trading-bot python -m app.main --mode paper --once

echo "Starting paper trading service..."
echo "正在启动模拟盘服务..."
docker compose up -d

echo "Deployment complete. Use 'docker compose logs -f trading-bot' to inspect runtime logs."
echo "部署完成。可使用 'docker compose logs -f trading-bot' 查看运行日志。"
