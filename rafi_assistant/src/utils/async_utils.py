"""Helpers for working with awaitables and synchronous values interchangeably."""

from __future__ import annotations

import inspect
from typing import Any


def is_coroutine(value: Any) -> bool:
    """Return True if value implements the awaitable protocol."""
    return inspect.isawaitable(value)


async def await_if_needed(value: Any) -> Any:
    """Await the value if it's awaitable or execute queries when possible."""
    if value is None:
        return None

    execute_attr = getattr(value, "execute", None)
    if callable(execute_attr) and not hasattr(value, "data"):
        response = execute_attr()
        resolved = await await_if_needed(response)
        return getattr(resolved, "data", resolved)

    if is_coroutine(value):
        return await value

    return value
