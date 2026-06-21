"""Market alert radar orchestration tests.
行情雷达编排测试。
"""

from app.alerts.radar import MarketAlertRadar
from app.alerts.alert_state import AlertStateManager
from app.alerts.signal_models import AlertLevel, AlertRuleResult, AlertSignal, AlertType, MarketMetrics, TimeframeStats
from app.config import Settings
from app.execution.paper import PaperTradingEngine
from app.risk.manager import RiskManager
from app.storage.sqlite import SQLiteStorage


def make_alert(alert_type: AlertType, level: AlertLevel, score: int) -> AlertSignal:
    """Build a minimal alert for orchestration tests.
    为编排测试构建最小提醒对象。
    """

    return AlertSignal(
        timestamp=1,
        symbol="PIPPIN/USDT:USDT",
        alert_type=alert_type,
        level=level,
        score=score,
        price=0.018,
        price_change_3m=0.01,
        price_change_5m=0.02,
        price_change_15m=0.30,
        price_change_1h=0.08,
        price_change_24h=0.50,
        volume_ratio=2.0,
        btc_15m_change=0.0,
        reasons=["test / 测试"],
        suggested_action="test",
    )


def test_high_risk_wins_same_cycle_notification_priority() -> None:
    radar = MarketAlertRadar.__new__(MarketAlertRadar)
    high_risk = make_alert(AlertType.HIGH_RISK_EXTENSION, AlertLevel.B, 70)
    top_gainer = make_alert(AlertType.TOP_GAINER_MOMENTUM, AlertLevel.C, 80)

    winner = radar._select_notification_winner([top_gainer, high_risk])

    assert winner == high_risk


def make_metrics(symbol: str) -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        price=1.0,
        price_change_24h=0.4,
        quote_volume_24h=50_000_000,
        rank_24h=1,
        high_24h=1.2,
        low_24h=0.8,
        stats_3m=TimeframeStats(change=0.03, volume_ratio=2.5),
        stats_5m=TimeframeStats(change=0.04, volume_ratio=2.5),
        stats_15m=TimeframeStats(change=0.05, volume_ratio=2.0),
        stats_1h=TimeframeStats(change=0.12, volume_ratio=1.5),
    )


class FakeScanner:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols

    def scan(self) -> list[MarketMetrics]:
        return [make_metrics(symbol) for symbol in self.symbols]


class FakeNotifier:
    def send_message(self, text: str) -> bool:
        return False

    def notify_error(self, message: str) -> bool:
        return False


class NoisyRules:
    def evaluate(self, metrics: MarketMetrics, state: dict | None = None) -> list[AlertRuleResult]:
        return [
            AlertRuleResult(AlertType.TOP_GAINER_MOMENTUM, 69, ["weak / 弱信号"], "ignore"),
            AlertRuleResult(AlertType.SHORT_TERM_SURGE, 74, ["surge / 异动"], "store"),
            AlertRuleResult(AlertType.HIGH_RISK_EXTENSION, 88, ["risk / 风险"], "store risk"),
        ]


def test_radar_keeps_one_alert_per_symbol_and_caps_cycle(tmp_path) -> None:
    settings = Settings(_env_file=None, ALERT_MIN_SCORE_TO_STORE=70, ALERT_MAX_ALERTS_PER_CYCLE=5)
    storage = SQLiteStorage(tmp_path / "radar.sqlite")
    radar = MarketAlertRadar(FakeScanner([f"COIN{i}/USDT:USDT" for i in range(8)]), storage, FakeNotifier(), settings)
    radar.rules = NoisyRules()

    alerts = radar.run_once()

    assert len(alerts) == 5
    assert {alert.alert_type for alert in alerts} == {AlertType.HIGH_RISK_EXTENSION}
    assert all(alert.score >= 70 for alert in alerts)
    assert len(storage.get_market_alerts(limit=20)) == 5


class EntryRules:
    def evaluate(self, metrics: MarketMetrics, state: dict | None = None) -> list[AlertRuleResult]:
        return [AlertRuleResult(AlertType.SHORT_TERM_SURGE, 80, ["surge / 放量异动"], "突破追踪")]


def test_radar_creates_paper_order_for_actionable_alert(tmp_path) -> None:
    settings = Settings(_env_file=None, ALERT_AUTO_PAPER_TRADING_ENABLED=True)
    storage = SQLiteStorage(tmp_path / "radar.sqlite")
    paper = PaperTradingEngine(storage=storage, notifier=None, initial_equity=settings.account_equity, leverage=settings.paper_leverage)
    risk = RiskManager(account_equity=settings.account_equity, btc_drop_threshold_15m=settings.btc_drop_threshold_15m)
    radar = MarketAlertRadar(FakeScanner(["COIN/USDT:USDT"]), storage, FakeNotifier(), settings, paper=paper, risk_manager=risk)
    radar.rules = EntryRules()

    alerts = radar.run_once()

    orders = storage.get_orders()
    positions = storage.get_open_positions("COIN/USDT:USDT")
    assert len(alerts) == 1
    assert len(orders) == 1
    assert len(positions) == 1
    assert orders[0]["side"] == "long"
    assert orders[0]["entry_price"] == 1.0
    assert orders[0]["stop_loss"] == 0.98
    assert orders[0]["take_profit"] == 1.04
    assert orders[0]["quantity"] == 1000.0
    assert "alert SHORT_TERM_SURGE" in orders[0]["reason"]


def test_storage_cooldown_allows_level_upgrade(tmp_path) -> None:
    settings = Settings(_env_file=None, ALERT_COOLDOWN_A_SECONDS=300, ALERT_COOLDOWN_B_SECONDS=600, ALERT_COOLDOWN_C_SECONDS=1800)
    storage = SQLiteStorage(tmp_path / "radar.sqlite")
    storage.initialize()
    state = AlertStateManager(storage, settings)
    prior = make_alert(AlertType.VOLUME_PRICE_OI_RESONANCE, AlertLevel.B, 70)
    state.record_alert(prior, sent_to_telegram=False)

    upgraded = make_alert(AlertType.VOLUME_PRICE_OI_RESONANCE, AlertLevel.A, 85)

    assert state.should_record(upgraded, now_ms=prior.timestamp + 1_000)


def test_storage_cooldown_blocks_same_level_repeat(tmp_path) -> None:
    settings = Settings(_env_file=None, ALERT_COOLDOWN_A_SECONDS=300, ALERT_COOLDOWN_B_SECONDS=600, ALERT_COOLDOWN_C_SECONDS=1800)
    storage = SQLiteStorage(tmp_path / "radar.sqlite")
    storage.initialize()
    state = AlertStateManager(storage, settings)
    prior = make_alert(AlertType.VOLUME_PRICE_OI_RESONANCE, AlertLevel.B, 70)
    state.record_alert(prior, sent_to_telegram=False)

    repeated = make_alert(AlertType.VOLUME_PRICE_OI_RESONANCE, AlertLevel.B, 75)

    assert not state.should_record(repeated, now_ms=prior.timestamp + 1_000)
