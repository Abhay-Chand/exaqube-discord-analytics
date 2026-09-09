from __future__ import annotations

from typing import Any


def ev(kind: str, **kwargs: Any) -> dict:
    return {"event": kind, **kwargs}
