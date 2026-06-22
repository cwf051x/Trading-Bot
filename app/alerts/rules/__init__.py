"""Built-in alert radar rules.
内置行情雷达规则集合。
"""

from app.alerts.rules.base import AlertRule
from app.alerts.rules.hourly_trend import HourlyTrendRule
from app.alerts.rules.volume_price_oi import VolumePriceOIRule

__all__ = ["AlertRule", "HourlyTrendRule", "VolumePriceOIRule"]
