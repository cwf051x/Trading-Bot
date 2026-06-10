"""Exchange client tests.
交易所客户端测试。
"""

from app.exchange.binance import BinanceFuturesClient


class FakeBinanceUSDM:
    def __init__(self, config):
        self.config = config


def test_binance_client_passes_proxy_to_ccxt(monkeypatch) -> None:
    captured = {}

    def fake_factory(config):
        captured.update(config)
        return FakeBinanceUSDM(config)

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)

    BinanceFuturesClient(proxy="http://127.0.0.1:7890")

    assert captured["proxies"] == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }


def test_binance_client_omits_proxy_when_empty(monkeypatch) -> None:
    captured = {}

    def fake_factory(config):
        captured.update(config)
        return FakeBinanceUSDM(config)

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)

    BinanceFuturesClient()

    assert "proxies" not in captured
