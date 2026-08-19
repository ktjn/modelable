from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

@dataclass(frozen=True, slots=True)
class CustomerCustomerRequestV1:
    customerId: UUID
    displayName: str
    email: str
    status: str
    tags: list[str]
    metadata: dict[str, int]
    address: Optional[CustomerCustomerRequestV1Address] = None
    favoriteProduct: Optional[str] = None

@dataclass(frozen=True, slots=True)
class CustomerCustomerRequestV1Address:
    line1: str
    line2: Optional[str] = None
