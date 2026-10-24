"""通过知乎登录态读取作者作品或关键词搜索结果。"""
from __future__ import annotations

import json
from urllib.parse import quote, urlencode

import httpx

from .identity import Identity
from .manager import BrowserManager, normalize_proxy
from ..platforms.zhihu.extract import parse_zhihu_items, parse_zhihu_search_items
from ..platforms.zhihu.sign import sign as sign_zhihu


# Endpoint shape is based on OpenCLI's Apache-2.0 Zhihu adapter; the browser
# transport, pagination and normalization below are an independent Python
# implementation for CreatorHub.
_HOME_URL = "https://www.zhihu.com/"
_INCLUDE = (
    "data[*].id,data[*].question,data[*].title,data[*].excerpt,"
    "data[*].created_time,data[*].updated_time,data[*].created,data[*].updated,"
    "data[*].voteup_count,data[*].comment_count,data[*].reaction_statistics,"
    "data[*].url,data[*].author"
)

_SEARCH_PAGE_URL = "https://www.zhihu.com/search?q={keyword}&search_source=Filter&type=content"
_SEARCH_API = "https://www.zhihu.com/api/v4/search_v3"
_SEARCH_HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "x-api-version": "3.0.91",
    "x-app-za": "OS=Web",
    "x-requested-with": "fetch",
    "x-zse-93": "101_3_3.0",
}


def _api_url(user_token: str, kind: str) -> str:
    return (
        "https://www.zhihu.com/api/v4/members/"
        f"{quote(user_token, safe='')}/{kind}?limit=20&offset=0&include="
        f"{quote(_INCLUDE, safe='')}"
    )


def _error_text(status: int, kind: str, detail: str = "") -> str:
    label = "回答" if kind == "answers" else "文章"
    if status in {401, 403}:
        return "知乎读取接口需要有效登录 Cookie；请在知乎平台粘贴 Cookie 后重试"
    if status == 404:
        return "知乎用户不存在，或该用户的公开内容接口不可用"
    suffix = f"：{detail}" if detail else ""
    return f"知乎{label}接口请求失败（HTTP {status}）{suffix}"


def _cookie_header(cookies: list[dict]) -> str:
    pairs = []
    for cookie in cookies or []:
        name = str(cookie.get("name") or "").strip()
        if name:
            pairs.append(f"{name}={cookie.get('value', '')}")
    return "; ".join(pairs)


def _search_params(keyword: str, offset: int, limit: int = 20) -> dict[str, object]:
    return {
        "gk_version": "gz-gaokao",
        "t": "general",
        "q": keyword,
        "correction": 1,
        "offset": offset,
        "limit": limit,
        "filter_fields": "",
        "lc_idx": offset,
        "show_all_topics": 0,
        "search_source": "Filter",
        "time_interval": "",
        "sort": "",
        "vertical": "",
    }


async def fetch_zhihu_search(
    mgr: BrowserManager,
    identity: Identity,
    keyword: str,
    known_ids: set[str],
    *,
    max_pages: int = 3,
    block_media: bool = True,
) -> tuple[list, str]:
    """按 MediaCrawler 的方式读取知乎关键词搜索。

    先打开搜索页让浏览器建立真实 Cookie，再用同一账号 Cookie 调用
    ``search_v3`` 并生成知乎要求的签名；这样不会把未签名的浏览器 fetch
    当成已经登录的接口请求。
    """
    page = await mgr.new_page(identity, block_media)
    error = ""
    try:
        search_url = _SEARCH_PAGE_URL.format(keyword=quote(keyword, safe=""))
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(800)
        cookies = await page.context.cookies(["https://www.zhihu.com"])
        cookie_header = _cookie_header(cookies)
        if "d_c0=" not in cookie_header:
            return [], "知乎 Cookie 缺少 d_c0；请从知乎登录态重新复制完整 Cookie"
        try:
            sign_zhihu("/api/v4/search_v3?q=test", cookie_header)
        except Exception as exc:
            return [], f"知乎签名运行环境不可用: {exc}"

        ua = identity.ua or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        items = []
        seen: set[str] = set()
        pages = max(1, min(int(max_pages or 3), 30))
        proxy = normalize_proxy(identity.proxy)
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, proxy=proxy or None
        ) as client:
            for page_index in range(pages):
                params = _search_params(keyword, page_index * 20)
                query = urlencode(params)
                uri = f"/api/v4/search_v3?{query}"
                headers = {
                    **_SEARCH_HEADERS,
                    "cookie": cookie_header,
                    "referer": search_url,
                    "user-agent": ua,
                    **sign_zhihu(uri, cookie_header),
                }
                response = await client.get(_SEARCH_API, params=params, headers=headers)
                if response.status_code != 200:
                    detail = response.text[:160]
                    if response.status_code in {401, 403}:
                        return items, "知乎搜索接口拒绝访问；请更新包含 d_c0 / z_c0 的 Cookie"
                    return items, _error_text(response.status_code, "answers", detail)
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    return items, "知乎搜索接口返回了非 JSON 内容，可能触发安全验证"
                if not isinstance(payload, dict):
                    return items, "知乎搜索接口返回结构异常"
                page_items = parse_zhihu_search_items(payload)
                fresh = 0
                for item in page_items:
                    if item.aweme_id in seen or item.aweme_id in known_ids:
                        continue
                    seen.add(item.aweme_id)
                    items.append(item)
                    fresh += 1
                paging = payload.get("paging") or {}
                if not page_items or paging.get("is_end") or not fresh:
                    break
        return items, ""
    except Exception as exc:
        return [], f"知乎关键词搜索失败: {exc}"
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def fetch_zhihu_works(
    mgr: BrowserManager,
    identity: Identity,
    user_token: str,
    known_ids: set[str],
    *,
    max_pages: int = 3,
    block_media: bool = True,
) -> tuple[list, dict | None, str]:
    """读取用户最近回答与文章，返回 (原始回答, 原始文章, 错误)。"""
    page = await mgr.new_page(identity, block_media)
    payload = None
    try:
        await page.goto(_HOME_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_timeout(800)
        except Exception:
            pass
        payload = await page.evaluate(
            """
            async ({answersUrl, articlesUrl, maxPages, knownIds}) => {
              const load = async (kind, firstUrl) => {
                const rows = [];
                const visited = new Set();
                let url = firstUrl;
                let error = null;
                for (let page = 0; url && page < maxPages; page += 1) {
                  if (visited.has(url)) break;
                  visited.add(url);
                  let response;
                  let body;
                  try {
                    response = await fetch(url, {
                      credentials: "include",
                      headers: {Accept: "application/json"},
                    });
                    body = await response.json();
                  } catch (err) {
                    error = {status: 0, detail: String(err && err.message || err)};
                    break;
                  }
                  if (!response.ok) {
                    error = {status: response.status, detail: body && body.error && body.error.message || ""};
                    break;
                  }
                  if (!body || !Array.isArray(body.data)) {
                    error = {status: 200, detail: "响应缺少 data 数组"};
                    break;
                  }
                  rows.push(...body.data);
                  const fresh = body.data.some(row => !knownIds.includes(`${kind}:${row && row.id}`));
                  const paging = body.paging || {};
                  if (!body.data.length || paging.is_end || !fresh) break;
                  const next = paging.next;
                  if (!next) break;
                  const nextUrl = new URL(next, location.origin);
                  if (nextUrl.origin !== location.origin || !nextUrl.pathname.startsWith("/api/v4/members/")) break;
                  url = nextUrl.toString();
                }
                return {kind, rows, error};
              };
              const [answers, articles] = await Promise.all([
                load("answer", answersUrl), load("article", articlesUrl),
              ]);
              return {answers, articles};
            }
            """,
            {
                "answersUrl": _api_url(user_token, "answers"),
                "articlesUrl": _api_url(user_token, "articles"),
                "maxPages": max(1, min(int(max_pages or 3), 30)),
                "knownIds": list(known_ids),
            },
        )
    except Exception as exc:
        return [], None, f"打开知乎读取页失败: {exc!r}"
    finally:
        try:
            await page.close()
        except Exception:
            pass

    if not isinstance(payload, dict):
        return [], None, "知乎返回了无法解析的响应"
    answers = payload.get("answers") or {}
    articles = payload.get("articles") or {}
    answer_rows = answers.get("rows") if isinstance(answers, dict) else []
    article_rows = articles.get("rows") if isinstance(articles, dict) else []
    items = parse_zhihu_items(answer_rows or [], article_rows or [])
    errors = []
    for result, kind in ((answers, "answers"), (articles, "articles")):
        error = result.get("error") if isinstance(result, dict) else None
        if error:
            errors.append(_error_text(
                int(error.get("status") or 0), kind, str(error.get("detail") or "")))
    author = None
    for item in items:
        if item.author_name or item.author_avatar:
            author = {"nickname": item.author_name, "avatar": item.author_avatar}
            break
    if not items and errors:
        return [], author, "；".join(dict.fromkeys(errors))
    return items, author, "；".join(dict.fromkeys(errors))
