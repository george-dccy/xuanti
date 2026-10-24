"""知乎搜索接口签名适配。

签名实现来自 MediaCrawler 的学习版知乎适配，保留其原始版权与许可证声明；
这里仅负责在 CreatorHub 内调用，不把签名算法散落到抓取流程中。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


_JS_PATH = Path(__file__).parent / "static" / "zhihu.js"
_CONTEXT = None
_AVAILABLE: bool | None = None


def _ensure_node_path() -> None:
    """让 PyExecJS 在 PM2/非登录 SSH 环境中也能找到 Node.js。"""
    candidates = []
    configured = os.environ.get("CREATORHUB_NODE_BIN", "").strip()
    if configured:
        candidates.append(Path(configured))
    found = shutil.which("node")
    if found:
        candidates.append(Path(found))
    candidates.extend(Path("/root/.nvm/versions/node").glob("*/bin/node"))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        parent = str(candidate.parent)
        current = os.environ.get("PATH", "").split(os.pathsep)
        if parent not in current:
            os.environ["PATH"] = parent + os.pathsep + os.environ.get("PATH", "")
        return


def _context():
    global _CONTEXT
    if _CONTEXT is None:
        _ensure_node_path()
        import execjs

        _CONTEXT = execjs.compile(_JS_PATH.read_text(encoding="utf-8-sig"))
    return _CONTEXT


def available() -> bool:
    """返回签名运行时是否可用，不发起网络请求。"""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        _AVAILABLE = bool(sign("/api/v4/search_v3?q=test", "d_c0=test"))
    except Exception:
        _AVAILABLE = False
    return _AVAILABLE


def sign(url: str, cookies: str) -> dict[str, str]:
    """为知乎 v4 API 生成 ``x-zse-96`` 与 ``x-zst-81``。"""
    if not str(cookies or "").strip():
        raise ValueError("知乎签名需要 Cookie")
    return dict(_context().call("get_sign", str(url), str(cookies)))
