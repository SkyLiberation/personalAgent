from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from personal_agent.kernel.contracts.review import DeliveryMessage, DeliveryResult
from personal_agent.kernel.contracts.delivery import DeliveryTarget


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


class InAppDeliveryProvider:
    """A production delivery channel surfaced by the application's inbox API."""

    def send(self, target: DeliveryTarget, message: DeliveryMessage) -> DeliveryResult:
        if target.channel != "in_app":
            return DeliveryResult(ok=False, error=f"unsupported channel: {target.channel}")
        if target.target_type != "user_id":
            return DeliveryResult(ok=False, error=f"unsupported in-app target type: {target.target_type}")
        digest = sha256(f"{target.target_id}\0{message.text}".encode("utf-8")).hexdigest()
        return DeliveryResult(ok=True, provider_message_id=f"in_app_{digest[:20]}")


class DeliveryRouter:
    """Route delivery messages to channel-specific providers."""

    def __init__(self, providers: dict[str, DeliveryProvider]) -> None:
        self.providers = providers

    def send(self, target: DeliveryTarget, message: DeliveryMessage) -> DeliveryResult:
        provider = self.providers.get(target.channel)
        if provider is None:
            return DeliveryResult(ok=False, error=f"no provider registered for channel: {target.channel}")
        return provider.send(target, message)
