"""Registry of public operations and whether each needs OAuth.

Decorating a function with :func:`operation` does two things: it records the
operation (so :func:`youtube.auth.auth_status` can list what the current
credentials support), and, for ``requires_oauth=True``, it refuses up front
with :class:`~youtube.errors.OAuthRequiredError` when only an API key is
available -- before any request is sent.

Decorated functions take a :class:`~youtube.client.YouTubeClient` as their
first argument.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from youtube.errors import oauth_required

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class Operation:
    """One public operation and its credential requirement."""

    name: str
    requires_oauth: bool
    summary: str


OPERATIONS: dict[str, Operation] = {}


def operation(*, requires_oauth: bool = False) -> Callable[[F], F]:
    """Register a public operation; enforce OAuth for it when ``requires_oauth``."""

    def decorator(fn: F) -> F:
        summary = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
        OPERATIONS[fn.__name__] = Operation(fn.__name__, requires_oauth, summary)
        if not requires_oauth:
            return fn

        @functools.wraps(fn)
        def wrapper(client: Any, *args: Any, **kwargs: Any) -> Any:
            if not client.auth.has_oauth:
                raise oauth_required(fn.__name__)
            return fn(client, *args, **kwargs)

        wrapper.requires_oauth = True  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
