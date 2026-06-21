"""Symbol universe selection tests.
交易对扫描范围选择测试。
"""

from app.data.symbol_universe import filter_symbol_universe


def test_filter_symbol_universe_merges_volume_top_gainers_and_watchlist() -> None:
    tickers = [
        {"symbol": "AAAUSDT", "quoteVolume": 12_000_000, "percentage": 1},
        {"symbol": "BBBUSDT", "quoteVolume": 1_000_000, "percentage": 120},
        {"symbol": "CCCUSDT", "quoteVolume": 900_000, "percentage": 90},
        {"symbol": "DDDUSDT", "quoteVolume": 500_000, "percentage": 0},
        {"symbol": "EEEUSDT", "quoteVolume": 800_000, "percentage": -5},
        {"symbol": "USDCUSDT", "quoteVolume": 50_000_000, "percentage": 2},
    ]

    rows = filter_symbol_universe(
        tickers=tickers,
        min_quote_volume=10_000_000,
        top_gainers_limit=2,
        blacklist="CCCUSDT",
        watchlist="EEEUSDT",
    )

    assert [row["symbol"] for row in rows] == ["BBB/USDT:USDT", "AAA/USDT:USDT", "EEE/USDT:USDT"]
    assert rows[0]["rank_24h"] == 1
    assert rows[1]["rank_24h"] == 2
    assert rows[2]["rank_24h"] == 4
