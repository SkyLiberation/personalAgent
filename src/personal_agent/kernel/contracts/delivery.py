"""Delivery destination value objects shared by bounded domains."""

from pydantic import BaseModel, Field


class DeliveryTarget(BaseModel):
    channel: str = "feishu"
    target_type: str = "chat_id"
    target_id: str = Field(min_length=1)


__all__ = ["DeliveryTarget"]
