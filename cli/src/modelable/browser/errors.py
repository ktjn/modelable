from typing import Literal


class BrowserRequestValidationError(ValueError):
    """Raised when a browser request cannot be decoded into the public DTO schema."""


BrowserLanguageErrorCode = Literal[
    "STALE_WORKSPACE",
    "LANGUAGE_UNAVAILABLE",
    "INVALID_POSITION",
]


class BrowserLanguageError(ValueError):
    """Raised for an expected, non-terminal browser language request failure."""

    def __init__(self, code: BrowserLanguageErrorCode) -> None:
        super().__init__(code)
        self.code = code
