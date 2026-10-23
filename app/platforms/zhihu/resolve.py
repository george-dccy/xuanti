"""解析知乎创作者主页与 url_token。

知乎作者监控只接受 ``/people/<url_token>`` 主页或直接填写 url_token；
问题页、回答页和专栏文章页不是创作者监控目标。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PEOPLE_RE = re.compile(r"^/people/([^/?#]+)(?:/.*)?/?$")


def resolve_zhihu_user_token(value: str) -> str | None:
    """返回知乎用户的 ``url_token``，无法识别时返回 ``None``。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("user:"):
        raw = raw[5:].strip()
    if _TOKEN_RE.fullmatch(raw):
        return raw

    candidate = raw if "://" in raw else "https://" + raw
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in {"zhihu.com", "www.zhihu.com"}:
        return None
    match = _PEOPLE_RE.fullmatch(parts.path or "")
    if not match or not _TOKEN_RE.fullmatch(match.group(1)):
        return None
    return match.group(1)
