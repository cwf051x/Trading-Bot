"""Exchange client tests.
交易所客户端测试。
"""

from app.exchange.binance import BinanceFuturesClient
import requests


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


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, str | int]]:
        return [{"timestamp": 1_700_000_000_000, "sumOpenInterest": "123.45"}]


def test_open_interest_history_retries_with_proxy_after_direct_timeout(monkeypatch) -> None:
    def fake_factory(config):
        return FakeBinanceUSDM(config)

    calls = []

    def fake_get(url, params, timeout, proxies):
        calls.append({"url": url, "params": params, "timeout": timeout, "proxies": proxies})
        if proxies is None:
            raise requests.ReadTimeout("direct timed out")
        return FakeResponse()

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)
    monkeypatch.setattr(requests, "get", fake_get)

    client = BinanceFuturesClient(proxy="http://127.0.0.1:7890")
    points = client.get_open_interest_history("OP/USDT:USDT")

    assert len(points) == 1
    assert points[0].open_interest == 123.45
    assert calls[0]["proxies"] is None
    assert calls[1]["proxies"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    assert calls[1]["params"]["symbol"] == "OPUSDT"
