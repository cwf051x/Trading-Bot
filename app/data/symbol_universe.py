"""Symbol universe filtering for Binance USDT-M futures.
Binance USDT-M 永续合约交易对范围过滤。
"""

from __future__ import annotations

from typing import Any

STABLE_BASE_ASSETS = {"USDC", "FDUSD", "BUSD", "TUSD", "USDP", "DAI", "EURI", "EUR", "TRY", "BRL"}


def normalize_symbol(symbol: str) -> str:
    """Normalize Binance or ccxt symbol strings to ccxt swap style when possible.
    尽量将 Binance 或 ccxt 交易对字符串标准化为 ccxt 合约格式。
    """

    cleaned = symbol.strip().upper()
    if "/" in cleaned:
        return cleaned
    if cleaned.endswith("USDT"):
        base = cleaned[:-4]
        return f"{base}/USDT:USDT"
    return cleaned


def symbol_base(symbol: str) -> str:
    """Return the base asset from a normalized or raw symbol.
    从标准或原始交易对中返回基础资产。
    """

    normalized = normalize_symbol(symbol)
    if "/" in normalized:
        return normalized.split("/", 1)[0]
    if normalized.endswith("USDT"):
        return normalized[:-4]
    return normalized


def parse_symbol_list(value: list[str] | str | None) -> set[str]:
    """Parse comma-separated symbol config into a normalized set.
    将逗号分隔交易对配置解析为标准化集合。
    """

    if value is None or value == "":
        return set()
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = value
    return {normalize_symbol(item) for item in items if str(item).strip()}


def is_usdt_perpetual_symbol(symbol: str) -> bool:
    """Return whether a symbol looks like a USDT-margined perpetual.
    判断交易对是否看起来是 USDT 本位永续合约。
    """

    normalized = normalize_symbol(symbol)
    return normalized.endswith("/USDT:USDT") or normalized.endswith("/USDT")


def is_stable_pair(symbol: str) -> bool:
    """Return whether a symbol is a stablecoin or fiat pair to exclude.
    判断交易对是否属于需要排除的稳定币或法币交易对。
    """

    return symbol_base(symbol) in STABLE_BASE_ASSETS


def filter_symbol_universe(
    tickers: list[dict[str, Any]],
    min_quote_volume: float,
    blacklist: list[str] | str | None = None,
    watchlist: list[str] | str | None = None,
) -> list[dict[str, Any]]:
    """Filter ticker rows into the alert radar scanning universe.
    将 ticker 行过滤为行情雷达扫描范围。
    """

    blacklist_set = parse_symbol_list(blacklist)
    watchlist_set = parse_symbol_list(watchlist)
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        symbol = normalize_symbol(str(ticker.get("symbol") or ""))
        quote_volume = float(ticker.get("quote_volume") or ticker.get("quoteVolume") or 0.0)
        if not is_usdt_perpetual_symbol(symbol):
            continue
        if is_stable_pair(symbol):
            continue
        if symbol in blacklist_set:
            continue
        if watchlist_set and symbol not in watchlist_set:
            continue
        if quote_volume < min_quote_volume:
            continue
        normalized = dict(ticker)
        normalized["symbol"] = symbol
        rows.append(normalized)
    return sorted(rows, key=lambda item: float(item.get("percentage") or 0.0), reverse=True)
