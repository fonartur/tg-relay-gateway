"""Ошибки, которые формирует сам шлюз.

Каждая ошибка знает свой HTTP-код и текст. Наружу они уходят в формате
Telegram (``{"ok": false, "error_code": ..., "description": ...}``), чтобы
клиентские фреймворки разобрали их штатно, а не упали на разборе JSON.

Ошибки самого Telegram (включая его 429 со своим ``retry_after``) сюда не
относятся: они проходят насквозь без изменений.
"""

from __future__ import annotations

from typing import Any, ClassVar


class GatewayError(Exception):
    """Базовая ошибка шлюза."""

    status: ClassVar[int] = 500
    description: ClassVar[str] = "Internal Server Error"
    #: Короткое машинное имя причины — для журнала и метрик.
    reason: ClassVar[str] = "internal"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.description)
        self.detail = detail or self.description

    @property
    def retry_after(self) -> int | None:
        return None

    def to_payload(self) -> dict[str, Any]:
        """Тело ответа в формате Bot API."""
        payload: dict[str, Any] = {
            "ok": False,
            "error_code": self.status,
            "description": self.description,
        }
        if self.retry_after is not None:
            payload["parameters"] = {"retry_after": self.retry_after}
        return payload


class Unauthorized(GatewayError):
    """Ключ проекта неизвестен или отключён."""

    status = 401
    description = "Unauthorized"
    reason = "unauthorized"


class QuotaExceeded(GatewayError):
    """Исчерпан месячный лимит тарифа: боты или трафик."""

    status = 402
    description = "Payment Required: tariff limit exceeded"
    reason = "quota"


class PayloadTooLarge(GatewayError):
    """Тело запроса больше разрешённого."""

    status = 413
    description = "Request Entity Too Large"
    reason = "payload_too_large"


class RateLimited(GatewayError):
    """Превышена частота запросов проекта."""

    status = 429
    description = "Too Many Requests: gateway rate limit"
    reason = "rate_limited"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited, retry_after={retry_after}")
        self._retry_after = max(1, retry_after)

    @property
    def retry_after(self) -> int:
        return self._retry_after


class BadGateway(GatewayError):
    """Upstream недоступен или разорвал соединение."""

    status = 502
    description = "Bad Gateway: upstream unavailable"
    reason = "upstream_unavailable"


class GatewayTimeout(GatewayError):
    """Upstream не ответил за отведённое время."""

    status = 504
    description = "Gateway Timeout: upstream did not answer"
    reason = "upstream_timeout"
