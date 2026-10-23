"""通过知乎登录态浏览器读取作者回答和文章。"""
from __future__ import annotations

from urllib.parse import quote

from .identity import Identity
from .manager import BrowserManager
from ..platforms.zhihu.extract import parse_zhihu_items


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
