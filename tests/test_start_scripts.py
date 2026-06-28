"""Local startup script checks.
本地启动脚本检查。
"""

from __future__ import annotations

from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]


def test_radar_and_paper_start_scripts_append_to_work_logs() -> None:
    scripts = {
        "start_radar_loop.sh": ("logs/alert_radar.log", "logs/alert_radar.lock"),
        "start_paper.sh": ("logs/trading_bot.log", "logs/trading_bot.lock"),
    }
    for script_name, (log_path, lock_path) in scripts.items():
        path = ROOT / "scripts" / script_name
        source = path.read_text(encoding="utf-8")

        assert path.exists()
        assert os.access(path, os.X_OK)
        assert "set -euo pipefail" in source
        assert "mkdir -p \"$ROOT_DIR/logs\"" in source
        assert f"LOCK_FILE=\"$ROOT_DIR/{lock_path}\"" in source
        assert "flock -n" in source
        assert "PYTHONUNBUFFERED=1" in source or " -u " in source
        assert "PYTHONPATH=\"$ROOT_DIR" in source
        assert f"tee -a \"$ROOT_DIR/{log_path}\"" in source
        assert "existing_pids" in source


def test_paper_start_script_detects_common_paper_loop_shapes() -> None:
    source = (ROOT / "scripts" / "start_paper.sh").read_text(encoding="utf-8")

    assert "scripts/run_paper.py" in source
    assert "app.main" in source
    assert "paper" in source
    assert "RUN_MODE=paper" in source


def test_readme_explains_local_logs_and_duplicate_writers() -> None:
    source = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "./scripts/start_radar_loop.sh" in source
    assert "./scripts/start_paper.sh" in source
    assert "裸命令只输出到当前终端" in source
    assert "logs/*.log" in source
    assert "不要再手动启动本地脚本" in source
    assert "重复 writer" in source
