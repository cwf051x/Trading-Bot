"""Exchange client tests.
交易所客户端测试。
"""

from app.exchange.binance import BinanceFuturesClient
import requests


class FakeBinanceUSDM:
    def __init__(self, config):
        self.config = config


def test_binance_client_uses_proxy_exchange_in_proxy_mode(monkeypatch) -> None:
    def fake_factory(config):
        return FakeBinanceUSDM(config)

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)

    client = BinanceFuturesClient(proxy="http://127.0.0.1:7890", network_mode="proxy")

    assert client.exchange.config["proxies"] == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }


def test_binance_client_uses_direct_exchange_in_direct_mode(monkeypatch) -> None:
    def fake_factory(config):
        return FakeBinanceUSDM(config)

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)

    client = BinanceFuturesClient(proxy="http://127.0.0.1:7890", network_mode="direct")

    assert "proxies" not in client.exchange.config


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, str | int]]:
        return [{"timestamp": 1_700_000_000_000, "sumOpenInterest": "123.45"}]


def test_klines_retry_transient_exchange_failure(monkeypatch) -> None:
    class FlakyExchange:
        def __init__(self, config):
            self.config = config
            self.calls = 0

        def fetch_ohlcv(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary binance failure")
            return [[1_700_000_000_000, 1, 2, 0.5, 1.5, 100]]

    exchange = FlakyExchange({})

    def fake_factory(config):
        exchange.config = config
        return exchange

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)

    client = BinanceFuturesClient(network_mode="direct", request_retries=1, retry_delay_seconds=0)
    klines = client.get_klines("BTC/USDT:USDT", "15m", limit=2)

    assert exchange.calls == 2
    assert klines[0].close == 1.5


def test_open_interest_history_retries_with_proxy_after_direct_timeout(monkeypatch) -> None:
    def fake_factory(config):
        return FakeBinanceUSDM(config)

    calls = []

    def fake_get(url, *, params, timeout, proxies):
        calls.append({"url": url, "params": params, "timeout": timeout, "proxies": proxies})
        if proxies is None:
            raise requests.ReadTimeout("direct timed out")
        return FakeResponse()

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)
    monkeypatch.setattr(BinanceFuturesClient, "_request_get", staticmethod(fake_get))

    client = BinanceFuturesClient(proxy="http://127.0.0.1:7890", network_mode="direct_fallback")
    points = client.get_open_interest_history("OP/USDT:USDT")

    assert len(points) == 1
    assert points[0].open_interest == 123.45
    assert calls[0]["proxies"] is None
    assert calls[1]["proxies"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    assert calls[1]["params"]["symbol"] == "OPUSDT"


def test_open_interest_history_direct_mode_does_not_require_proxy(monkeypatch) -> None:
    def fake_factory(config):
        return FakeBinanceUSDM(config)

    calls = []

    def fake_get(url, *, params, timeout, proxies):
        calls.append({"url": url, "params": params, "timeout": timeout, "proxies": proxies})
        return FakeResponse()

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)
    monkeypatch.setattr(BinanceFuturesClient, "_request_get", staticmethod(fake_get))

    client = BinanceFuturesClient(network_mode="direct")
    points = client.get_open_interest_history("OP/USDT:USDT")

    assert len(points) == 1
    assert len(calls) == 1
    assert calls[0]["proxies"] is None


def test_open_interest_history_uses_proxy_without_direct_attempt_in_proxy_mode(monkeypatch) -> None:
    def fake_factory(config):
        return FakeBinanceUSDM(config)

    calls = []

    def fake_get(url, *, params, timeout, proxies):
        calls.append({"url": url, "params": params, "timeout": timeout, "proxies": proxies})
        return FakeResponse()

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", fake_factory)
    monkeypatch.setattr(BinanceFuturesClient, "_request_get", staticmethod(fake_get))

    client = BinanceFuturesClient(proxy="http://127.0.0.1:7890", network_mode="proxy")
    points = client.get_open_interest_history("OP/USDT:USDT")

    assert len(points) == 1
    assert len(calls) == 1
    assert calls[0]["proxies"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
