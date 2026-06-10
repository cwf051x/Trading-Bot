"""Main entry point tests.
主入口测试。
"""

from app.exchange.binance import Kline
from app.main import run_paper_cycle
from app.risk.manager import RiskManager
from app.storage.sqlite import SQLiteStorage
from app.strategies.base import Signal


class FakeClient:
    def get_klines(self, symbol: str, timeframe: str, limit: int, since=None):
        if symbol.startswith("BTC"):
            return [
                Kline(timestamp=1, open=100, high=100, low=100, close=100, volume=1),
                Kline(timestamp=2, open=100, high=100, low=100, close=100, volume=1),
            ]
        return [
            Kline(timestamp=1, open=100, high=101, low=99, close=100, volume=100),
            Kline(timestamp=2, open=100, high=105, low=99, close=104, volume=300),
        ]


class FakeStrategy:
    def generate_signal(self, market_data):
        return Signal(market_data["symbol"], "long", 0.8, 104.0, 100.0, 112.0, "test signal", 2)


class FakeNotifier:
    def __init__(self):
        self.signals = []
        self.orders = []
        self.blocks = []

    def notify_signal(self, signal):
        self.signals.append(signal)

    def notify_paper_order(self, order):
        self.orders.append(order)

    def notify_risk_block(self, signal, reason):
        self.blocks.append((signal, reason))

    def notify_error(self, message):
        pass


class FakeSettings:
    default_symbol = "ETH/USDT:USDT"
    active_symbols = ["ETH/USDT:USDT"]
    default_timeframe = "15m"
    kline_limit = 2


def test_run_paper_cycle_creates_order_once(tmp_path):
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    notifier = FakeNotifier()
    from app.execution.paper import PaperTradingEngine

    paper = PaperTradingEngine(storage=storage, notifier=notifier)
    risk = RiskManager(account_equity=10_000)

    run_paper_cycle(FakeClient(), paper, FakeStrategy(), risk, notifier, FakeSettings())
    run_paper_cycle(FakeClient(), paper, FakeStrategy(), risk, notifier, FakeSettings())

    assert len(storage.get_open_positions("ETH/USDT:USDT")) == 1
    assert len(notifier.signals) == 2
    assert len(notifier.orders) == 1


def test_run_paper_cycle_handles_multiple_symbols(tmp_path):
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    notifier = FakeNotifier()
    from app.execution.paper import PaperTradingEngine

    paper = PaperTradingEngine(storage=storage, notifier=notifier)
    risk = RiskManager(account_equity=10_000)

    class MultiSettings(FakeSettings):
        active_symbols = ["ETH/USDT:USDT", "SOL/USDT:USDT"]

    run_paper_cycle(FakeClient(), paper, FakeStrategy(), risk, notifier, MultiSettings())

    assert len(storage.get_open_positions("ETH/USDT:USDT")) == 1
    assert len(storage.get_open_positions("SOL/USDT:USDT")) == 1
    assert len(notifier.signals) == 2
    assert len(notifier.orders) == 2
