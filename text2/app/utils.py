"""Small helpers shared across the application."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    ``datetime.utcnow()`` is deprecated since Python 3.12, so this helper keeps
    the same "naive UTC" semantics the database columns expect without using the
    deprecated call.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
