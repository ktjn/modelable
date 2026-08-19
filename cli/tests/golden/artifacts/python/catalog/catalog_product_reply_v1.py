from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

@dataclass(frozen=True, slots=True)
class CatalogProductReplyV1:
    productId: UUID
    name: str
