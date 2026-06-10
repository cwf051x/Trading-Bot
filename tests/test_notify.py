"""Telegram notifier tests.
Telegram 通知测试。
"""

from app.notify.telegram import TelegramNotifier
from requests import ConnectionError


def test_telegram_disabled_does_not_post(monkeypatch) -> None:
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("requests.post", fake_post)
    notifier = TelegramNotifier()

    sent = notifier.send_message("hello")

    assert sent is False
    assert called is False


def test_telegram_failure_does_not_raise(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        raise ConnectionError("network unavailable")

    monkeypatch.setattr("requests.post", fake_post)
    notifier = TelegramNotifier("token", "chat")

    sent = notifier.send_message("hello")

    assert sent is False


def test_telegram_uses_configured_proxy(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_post(*args, **kwargs):
        captured["proxies"] = kwargs["proxies"]
        return FakeResponse()

    monkeypatch.setattr("requests.post", fake_post)
    notifier = TelegramNotifier("token", "chat", proxy="http://127.0.0.1:7890")

    sent = notifier.send_message("hello")

    assert sent is True
    assert captured["proxies"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
