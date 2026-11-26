"""Internal domain exceptions (batch U1.1).

These types organise failures by cause inside the service layer. The public
HTTP contract is unchanged: endpoints still return the existing
``{"detail": ...}`` shape, with ``ValueError``-family failures mapped to 422
and ``RuntimeError``-family failures mapped to 503 at the route layer.

``ChainDataError`` is re-exported here so callers have one stable import path;
its definition remains in :mod:`blockchain_util` and old imports keep working.
"""

from .blockchain_util import ChainDataError  # re-export: backward compatible

__all__ = [
    "ChainDataError",
    "PortalError",
    "ValidationError",
    "SignerUnavailableError",
    "UnavailableBackendError",
    "FileAccessError",
]


class PortalError(RuntimeError):
    """Base class for all portal domain failures."""


class ValidationError(PortalError, ValueError):
    """Input failed a domain validation check (maps to HTTP 422)."""


class SignerUnavailableError(PortalError):
    """No active/trusted signer is available to sign a chain block."""


class UnavailableBackendError(PortalError):
    """An optional external backend (LLM, web research, mail) is unavailable."""


class FileAccessError(PortalError, OSError):
    """A local chain / raw-document file could not be read or written."""
