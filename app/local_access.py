"""Lightweight boundaries for a single-user, local-only workbench. No login."""
from __future__ import annotations

import os
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse


def loopback(host: str) -> bool:
    host = str(host or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        address = ip_address(host)
        return address.is_loopback or bool(
            getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def local_request(request: Request) -> bool:
    # Both the peer and Host matter: a DNS-rebinding Host or a local reverse
    # proxy does not turn an arbitrary remote page into the local workbench.
    return bool(request.client and loopback(request.client.host)
                and loopback(request.url.hostname or ""))


def _same_origin(request: Request, value: str) -> bool:
    try:
        origin, target = urlsplit(value), urlsplit(str(request.url))
        def identity(url):
            return (url.scheme, (url.hostname or "").lower(),
                    url.port or (443 if url.scheme == "https" else 80))
        return (not origin.username and not origin.password
                and origin.scheme in {"http", "https"}
                and origin.path in {"", "/"} and not origin.query and not origin.fragment
                and identity(origin) == identity(target))
    except ValueError:
        return False


class LocalAccessMiddleware:
    """Protect local data/actions, without users, passwords, sessions or roles."""
    def __init__(self, app):
        self.app = app
        self.public_hosts = frozenset(
            host.strip().lower().rstrip(".")
            for host in os.environ.get("CREATORHUB_PUBLIC_HOSTS", "").split(",")
            if host.strip()
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        path = scope.get("path", "")
        api = path == "/api" or path.startswith("/api/")
        error = None
        try:
            hostname = (request.url.hostname or "").lower().rstrip(".")
            trusted_proxy_host = hostname in self.public_hosts
            forwarded_proxy = bool(
                request.headers.get("x-forwarded-for")
                or request.headers.get("x-forwarded-proto")
            )
            valid_peer = bool(request.client and loopback(request.client.host)) \
                or (trusted_proxy_host and forwarded_proxy)
            valid_host = loopback(hostname) or trusted_proxy_host
            valid_local = (valid_peer and valid_host
                           and len(request.headers.getlist("host")) == 1)
            request.url.port
        except ValueError:
            valid_local = False
        if not valid_local:
            error = "当前工作台仅供本机或受信反向代理访问"
        elif api and (request.headers.get("sec-fetch-site", "") in {"cross-site", "same-site"}
                      or ("origin" in request.headers and not _same_origin(request, request.headers["origin"]))):
            error = "请从 CreatorHub 同源页面发起请求"
        if error:
            await JSONResponse({"detail": error}, status_code=403,
                               headers={"Cache-Control": "no-store"})(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [(b"x-content-type-options", b"nosniff"),
                            (b"x-frame-options", b"DENY"),
                            (b"referrer-policy", b"no-referrer")]
                if not path.startswith("/static/"):
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)
        # Pure ASGI: do not buffer media, exports or SSE streams.
        await self.app(scope, receive, secure_send)
