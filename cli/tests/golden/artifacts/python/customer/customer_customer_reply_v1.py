from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

@dataclass(frozen=True, slots=True)
class CustomerCustomerReplyV1:
    customerId: UUID
    displayName: str
    status: str
    tags: list[str]
    metadata: dict[str, int]
    createdAt: datetime
    address: Optional[CustomerCustomerReplyV1Address] = None
    favoriteProduct: Optional[str] = None
    updatedAt: Optional[datetime] = None

@dataclass(frozen=True, slots=True)
class CustomerCustomerReplyV1Address:
    line1: str
    line2: Optional[str] = None
