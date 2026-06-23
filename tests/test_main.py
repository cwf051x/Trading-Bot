"""Main entry point tests.
主入口测试。
"""

from app.exchange.binance import Kline
from app.main import build_telegram_notifiers, run_paper_cycle
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


class FakeTelegramSettings:
    telegram_bot_token = "alert-token"
    telegram_chat_id = "alert-chat"
    telegram_proxy = "http://alert-proxy"
    exchange_proxy = "http://exchange-proxy"
    telegram_order_enabled = True
    telegram_order_bot_token = ""
    telegram_order_chat_id = ""
    telegram_order_proxy = ""


def test_build_telegram_notifiers_defaults_orders_to_alert_channel() -> None:
    alert_notifier, order_notifier = build_telegram_notifiers(FakeTelegramSettings())

    assert alert_notifier.bot_token == "alert-token"
    assert alert_notifier.chat_id == "alert-chat"
    assert alert_notifier.proxy == "http://alert-proxy"
    assert order_notifier.bot_token == "alert-token"
    assert order_notifier.chat_id == "alert-chat"
    assert order_notifier.proxy == "http://alert-proxy"


def test_build_telegram_notifiers_uses_dedicated_order_channel() -> None:
    class Settings(FakeTelegramSettings):
        telegram_order_bot_token = "order-token"
        telegram_order_chat_id = "order-chat"
        telegram_order_proxy = "http://order-proxy"

    _, order_notifier = build_telegram_notifiers(Settings())

    assert order_notifier.bot_token == "order-token"
    assert order_notifier.chat_id == "order-chat"
    assert order_notifier.proxy == "http://order-proxy"


def test_build_telegram_notifiers_can_disable_order_channel() -> None:
    class Settings(FakeTelegramSettings):
        telegram_order_enabled = False

    _, order_notifier = build_telegram_notifiers(Settings())

    assert order_notifier.enabled is False


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
