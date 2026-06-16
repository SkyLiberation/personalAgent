from __future__ import annotations

from typing import Protocol

from .models import DeliveryMessage, DeliveryResult, DeliveryTarget


class DeliveryProvider(Protocol):
    def send(self, target: DeliveryTarget, message: DeliveryMessage) -> DeliveryResult:
        ...


class FeishuDeliveryProvider:
    """Delivery provider backed by the Feishu integration service."""

    def __init__(self, feishu_service) -> None:
        self.feishu_service = feishu_service

    def send(self, target: DeliveryTarget, message: DeliveryMessage) -> DeliveryResult:
        if target.channel != "feishu":
            return DeliveryResult(ok=False, error=f"unsupported channel: {target.channel}")
        if target.target_type != "chat_id":
            return DeliveryResult(ok=False, error=f"unsupported Feishu target type: {target.target_type}")
        try:
            self.feishu_service.send_digest(target.target_id, message.text)
        except Exception as exc:
            return DeliveryResult(ok=False, error=str(exc))
        return DeliveryResult(ok=True)


class DeliveryRouter:
    """Route delivery messages to channel-specific providers."""

    def __init__(self, providers: dict[str, DeliveryProvider]) -> None:
        self.providers = providers

    def send(self, target: DeliveryTarget, message: DeliveryMessage) -> DeliveryResult:
        provider = self.providers.get(target.channel)
        if provider is None:
            return DeliveryResult(ok=False, error=f"no provider registered for channel: {target.channel}")
        return provider.send(target, message)
