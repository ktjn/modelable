from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

@dataclass(frozen=True, slots=True)
class CustomerCustomerV1:
    customerId: UUID
    displayName: str
    email: str
    status: str
    tags: list[str]
    metadata: dict[str, int]
    createdAt: datetime
    internalRiskNotes: Optional[str] = None
    address: Optional[CustomerCustomerV1Address] = None
    favoriteProduct: Optional[str] = None
    updatedAt: Optional[datetime] = None

@dataclass(frozen=True, slots=True)
class CustomerCustomerV1Address:
    line1: str
    line2: Optional[str] = None
