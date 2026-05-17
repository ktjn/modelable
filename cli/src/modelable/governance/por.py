from __future__ import annotations

from dataclasses import dataclass


DEFAULT_POR_ISSUER = "modelable-registry.local"
DEFAULT_POR_ISSUED_AT = "1970-01-01T00:00:00Z"


@dataclass(frozen=True)
class PortableOwnershipRecord:
    model: str
    issuer: str = DEFAULT_POR_ISSUER
    issued_at: str = DEFAULT_POR_ISSUED_AT
    signature: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "model": self.model,
            "issuer": self.issuer,
            "issuedAt": self.issued_at,
            **({"signature": self.signature} if self.signature else {}),
        }


def build_por_reference(ref: str, *, issuer: str = DEFAULT_POR_ISSUER) -> dict[str, str]:
    """Return the unsigned POR reference embedded in generated artifacts."""
    return {
        "model": ref,
        "issuer": issuer,
        "issuedAt": DEFAULT_POR_ISSUED_AT,
    }


def build_por_record(
    ref: str,
    *,
    issuer: str = DEFAULT_POR_ISSUER,
    issued_at: str = DEFAULT_POR_ISSUED_AT,
    signature: str | None = None,
) -> PortableOwnershipRecord:
    return PortableOwnershipRecord(
        model=ref,
        issuer=issuer,
        issued_at=issued_at,
        signature=signature,
    )
