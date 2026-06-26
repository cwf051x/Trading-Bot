"""CI guard that blocks accidental real exchange trading calls.
CI 安全检查：防止误引入真实交易所下单/杠杆相关调用。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [ROOT / "app", ROOT / "scripts", ROOT / "tests"]

FORBIDDEN_PATTERNS = [
    r"\bcreate_order\b",
    r"\bcreate_market_order\b",
    r"\bcreate_limit_order\b",
    r"\bcreate_stop_order\b",
    r"\bset_leverage\b",
    r"\bset_margin_mode\b",
    r"\bset_position_mode\b",
    r"\bfapiPrivate\b",
    r"\bprivate_post_order\b",
    r"/fapi/v1/order",
]

# Internal paper-storage helpers intentionally use create_order naming but do
# not call an exchange. Keep this allowlist narrow and line-oriented.
ALLOWLIST_PATTERNS = [
    r"def create_order\(",
    r"\bstorage\.create_order\(",
    r"create_open_order_position",
    r"check_no_real_trading_calls",
    r"FORBIDDEN_PATTERNS",
]


def main() -> int:
    forbidden = re.compile("|".join(FORBIDDEN_PATTERNS))
    allowlist = re.compile("|".join(ALLOWLIST_PATTERNS))
    violations: list[str] = []
    for directory in SCAN_DIRS:
        for path in directory.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not forbidden.search(line):
                    continue
                if allowlist.search(line):
                    continue
                violations.append(f"{path.relative_to(ROOT)}:{line_no}: {line.strip()}")
    if violations:
        print("Potential real trading calls found:", file=sys.stderr)
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
