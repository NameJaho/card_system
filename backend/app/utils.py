from __future__ import annotations

import math
import secrets
import string
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, message: str = "请求成功", code: int = 200) -> dict[str, Any]:
    return {"code": code, "success": True, "message": message, "data": data}


def fail(
    message: str,
    code: int = 400,
    status_code: int = 200,
    error_code: str | None = None,
    retryable: bool = False,
) -> JSONResponse:
    content: dict[str, Any] = {"code": code, "success": False, "message": message, "data": None}
    if error_code:
        content["error"] = {"code": error_code, "message": message, "retryable": retryable}
    return JSONResponse(status_code=status_code, content=content)


def api_error(code: str, message: str, status_code: int, retryable: bool = False, request_id: str | None = None) -> JSONResponse:
    error = {"code": code, "message": message, "retryable": retryable}
    if request_id:
        error["requestId"] = request_id
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": error},
    )


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


rate_limiter = SlidingWindowRateLimiter()


def page_payload(page: dict[str, Any] | int | None, default_limit: int = 10) -> tuple[int, int]:
    if isinstance(page, dict):
        page_num = int(page.get("pageNum") or page.get("page") or 1)
        limit = int(page.get("limit") or page.get("pageSize") or default_limit)
    elif isinstance(page, int):
        page_num = page
        limit = default_limit
    else:
        page_num = 1
        limit = default_limit
    return max(page_num, 1), max(min(limit, 200), 1)


def paged(query, page: dict[str, Any] | int | None, serializer):
    page_num, limit = page_payload(page)
    total = query.count()
    rows = query.offset((page_num - 1) * limit).limit(limit).all()
    return {
        "list": [serializer(row) for row in rows],
        "page": {"pageNum": page_num, "limit": limit, "count": total, "pageCount": math.ceil(total / limit) if limit else 0},
    }


def now_text(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def random_code(prefix: str, size: int = 16) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(size))


def parse_time_range(value: Any) -> tuple[datetime | None, datetime | None]:
    if not value or not isinstance(value, list) or len(value) != 2:
        return None, None
    try:
        return datetime.fromisoformat(str(value[0])[:19]), datetime.fromisoformat(str(value[1])[:19])
    except ValueError:
        return None, None
