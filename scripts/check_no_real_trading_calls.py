"""CI guard that blocks accidental real exchange trading calls.
CI 安全检查：防止误引入真实交易所下单/杠杆相关调用。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [ROOT / "app", ROOT / "scripts", ROOT / "tests"]

FORBIDDEN_CALLS = {
    "create_order",
    "create_market_order",
    "create_limit_order",
    "create_stop_order",
    "set_leverage",
    "set_margin_mode",
    "set_position_mode",
    "private_post_order",
}
FORBIDDEN_ATTRIBUTE_PREFIXES = ("fapiPrivate",)
FORBIDDEN_TEXT_SNIPPETS = ("/fapi/v1/order",)


def scan_file_paths(paths: Iterable[Path], root: Path = ROOT) -> list[str]:
    """Scan Python files and return forbidden trading-call findings.
    扫描 Python 文件并返回疑似真实交易调用，供 CI 和单元测试复用。
    """

    violations: list[str] = []
    for path in paths:
        if path == Path(__file__).resolve():
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{_display_path(path, root)}:{exc.lineno or 1}: syntax error prevents safety scan")
            continue
        visitor = RealTradingCallVisitor(path=path, root=root)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return violations


def discover_python_files() -> list[Path]:
    """Return repository Python files covered by the safety guard.
    返回安全检查覆盖的仓库 Python 文件。
    """

    files: list[Path] = []
    for directory in SCAN_DIRS:
        files.extend(directory.rglob("*.py"))
    return files


class RealTradingCallVisitor(ast.NodeVisitor):
    """AST visitor that distinguishes internal storage writes from exchange calls.
    用 AST 区分内部模拟盘落库和真实交易所调用，避免注释绕过行级 allowlist。
    """

    def __init__(self, path: Path, root: Path) -> None:
        self.path = path
        self.root = root
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name and self._call_is_forbidden(node.func, name):
            self._add(node, name)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        value = node.value
        if isinstance(value, str) and any(snippet in value for snippet in FORBIDDEN_TEXT_SNIPPETS):
            self._add(node, value)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        value = _literal_string(node)
        if value and any(snippet in value for snippet in FORBIDDEN_TEXT_SNIPPETS):
            self._add(node, value)
        self.generic_visit(node)

    def _call_is_forbidden(self, func: ast.expr, name: str) -> bool:
        if name == "create_open_order_position":
            return False
        if name == "create_order":
            return not _is_allowed_storage_create_order(func)
        if name in FORBIDDEN_CALLS:
            return True
        return any(name.startswith(prefix) for prefix in FORBIDDEN_ATTRIBUTE_PREFIXES)

    def _add(self, node: ast.AST, detail: str) -> None:
        self.violations.append(f"{_display_path(self.path, self.root)}:{getattr(node, 'lineno', 1)}: {detail}")


def _call_name(func: ast.expr) -> str | None:
    """Return the called function or method name.
    提取调用名，支持 obj.method() 和 function() 两种形态。
    """

    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_allowed_storage_create_order(func: ast.expr) -> bool:
    """Allow only internal SQLite paper-storage create_order calls.
    只允许内部 SQLite 模拟盘落库 create_order，未知对象一律禁止。
    """

    if not isinstance(func, ast.Attribute):
        return False
    value = func.value
    if isinstance(value, ast.Name):
        return value.id == "storage"
    if isinstance(value, ast.Attribute):
        return value.attr == "storage" and isinstance(value.value, ast.Name) and value.value.id == "self"
    return False


def _literal_string(node: ast.AST) -> str | None:
    """Fold simple literal string concatenation used in source.
    折叠简单字符串字面量拼接，避免拆分敏感路径绕过扫描。
    """

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left)
        right = _literal_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    violations = scan_file_paths(discover_python_files(), root=ROOT)
    if violations:
        print("Potential real trading calls found:", file=sys.stderr)
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
