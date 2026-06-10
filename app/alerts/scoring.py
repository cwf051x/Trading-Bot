"""Scoring helpers for market alert radar.
行情雷达评分辅助逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.alerts.signal_models import AlertLevel, MarketMetrics


@dataclass
class AlertScore:
    """Mutable score accumulator capped to the 0-100 range.
    分数累加器，最终限制在 0-100 区间。
    """

    value: int = 40
    reasons: list[str] = field(default_factory=list)

    def add(self, points: int, reason: str) -> None:
        """Add positive points with an explanation.
        增加加分项并记录原因。
        """

        self.value += points
        self.reasons.append(reason)

    def subtract(self, points: int, reason: str) -> None:
        """Subtract points with an explanation.
        增加扣分项并记录原因。
        """

        self.value -= points
        self.reasons.append(reason)

    def normalized(self) -> int:
        """Return score clipped to 0-100.
        返回限制到 0-100 的分数。
        """

        return max(0, min(100, int(round(self.value))))


def level_from_score(score: int) -> AlertLevel:
    """Map numeric score to alert level.
    将数字评分映射为提醒等级。
    """

    if score >= 85:
        return AlertLevel.A
    if score >= 70:
        return AlertLevel.B
    if score >= 55:
        return AlertLevel.C
    return AlertLevel.IGNORE


def score_metrics(metrics: MarketMetrics) -> AlertScore:
    """Score common momentum and risk features.
    对通用动量与风险特征进行评分。
    """

    score = AlertScore()
    if metrics.rank_24h is not None:
        if metrics.rank_24h <= 10:
            score.add(15, "24h gainer rank top 10 / 24小时涨幅榜前10")
        elif metrics.rank_24h <= 20:
            score.add(12, "24h gainer rank top 20 / 24小时涨幅榜前20")
        elif metrics.rank_24h <= 50:
            score.add(8, "24h gainer rank top 50 / 24小时涨幅榜前50")
    if metrics.stats_1h.change > 0:
        score.add(10, "1h trend is positive / 1小时趋势向上")
    if metrics.stats_15m.higher_lows:
        score.add(10, "15m higher lows / 15分钟低点上移")
    if metrics.stats_5m.breakout or metrics.stats_15m.breakout:
        score.add(10, "breakout above recent high / 突破近期前高")
    if max(metrics.stats_3m.volume_ratio, metrics.stats_5m.volume_ratio, metrics.stats_15m.volume_ratio) >= 1.8:
        score.add(10, "rising with volume expansion / 放量上涨")
    if metrics.stats_5m.close_position >= 0.65 and metrics.stats_15m.close_position >= 0.55:
        score.add(5, "candles close near highs / K线收盘靠近高位")
    if metrics.btc_15m_change < 0 and metrics.stats_15m.change > metrics.btc_15m_change:
        score.add(10, "relative strength while BTC is weak / BTC走弱时相对抗跌")
    if 0.05 <= metrics.stats_15m.pullback_ratio <= 0.15 and metrics.stats_15m.volume_ratio < 1.0:
        score.add(8, "pullback volume contraction / 回调缩量")
    if metrics.stats_5m.change > 0 and metrics.stats_5m.volume_ratio >= 1.8 and metrics.stats_5m.higher_lows:
        score.add(15, "second leg volume expansion / 回调后二次放量启动")
    if metrics.open_interest is not None:
        score.add(8, "open interest data available for confirmation / OI数据可用于确认")

    if metrics.btc_15m_change <= -0.008:
        score.subtract(20, "BTC 15m sharp drop / BTC 15分钟急跌")
    if metrics.stats_5m.distance_to_ma > 0.06 or metrics.stats_15m.distance_to_ma > 0.08:
        score.subtract(10, "price extended from short MA / 价格偏离短周期均线过远")
    if metrics.stats_15m.change >= 0.08:
        score.subtract(10, "15m move is overheated / 15分钟涨幅过热")
    if metrics.stats_1h.change >= 0.18:
        score.subtract(20, "1h move is overheated / 1小时涨幅过热")
    if (metrics.stats_15m.rsi is not None and metrics.stats_15m.rsi >= 82) or (metrics.stats_1h.rsi is not None and metrics.stats_1h.rsi >= 82):
        score.subtract(10, "RSI is overheated / RSI过热")
    if metrics.stats_5m.rejection or metrics.stats_15m.rejection:
        score.subtract(15, "volume rejection wick / 放量冲高回落")
    if metrics.funding_rate is not None and metrics.funding_rate > 0.001:
        score.subtract(10, "funding rate is high / 资金费率偏高")
    if metrics.quote_volume_24h < 10_000_000:
        score.subtract(25, "liquidity below radar threshold / 流动性低于雷达阈值")
    return score
