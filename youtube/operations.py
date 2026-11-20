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
    requires_comment_access: bool = False
    writes: bool = False


OPERATIONS: dict[str, Operation] = {}


def operation(
    *, requires_oauth: bool = False, requires_comment_access: bool = False, writes: bool = False
) -> Callable[[F], F]:
    """Register a public operation; enforce OAuth for it when ``requires_oauth``.

    ``requires_comment_access`` marks comment reads, which Google refuses under
    the read-only OAuth scopes: they need YOUTUBE_API_KEY or an OAuth token with
    the opt-in comments scope (see :meth:`YouTubeClient.comment_services`).
    ``writes`` marks operations that change YouTube (uploads): they are only
    supported when ``YOUTUBE_ALLOW_UPLOADS`` is on.
    """

    def decorator(fn: F) -> F:
        summary = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
        OPERATIONS[fn.__name__] = Operation(fn.__name__, requires_oauth, summary, requires_comment_access, writes)
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
