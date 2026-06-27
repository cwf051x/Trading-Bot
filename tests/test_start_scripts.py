"""Local startup script checks.
本地启动脚本检查。
"""

from __future__ import annotations

from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]


def test_radar_and_paper_start_scripts_append_to_work_logs() -> None:
    scripts = {
        "start_radar_loop.sh": "logs/alert_radar.log",
        "start_paper.sh": "logs/trading_bot.log",
    }
    for script_name, log_path in scripts.items():
        path = ROOT / "scripts" / script_name
        source = path.read_text(encoding="utf-8")

        assert path.exists()
        assert os.access(path, os.X_OK)
        assert "set -euo pipefail" in source
        assert "mkdir -p \"$ROOT_DIR/logs\"" in source
        assert f"tee -a \"$ROOT_DIR/{log_path}\"" in source
        assert "existing_pids" in source
