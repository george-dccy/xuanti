"""使用 CreatorHub 管理的登录态 Chrome 读取淘宝热销搜索结果。"""
from __future__ import annotations

from urllib.parse import quote

from .identity import Identity
from .manager import BrowserManager
from ..platforms.taobao import TaobaoProduct, parse_taobao_product


_SEARCH_URL = "https://s.taobao.com/search?q={keyword}&sort=sale-desc&s={offset}"

_CARD_JS = r"""
() => {
  const anchors = [...document.querySelectorAll('a[href]')]
    .filter(a => /(?:item\.taobao\.com\/item\.htm|detail\.tmall\.com\/item\.htm)/i.test(a.href));
  const seen = new Set();
  const rows = [];
  const textOf = node => (node?.innerText || '').replace(/\s+/g, ' ').trim();
  for (const anchor of anchors) {
    const match = anchor.href.match(/[?&]id=(\d+)/);
    if (!match || seen.has(match[1])) continue;
    seen.add(match[1]);
    let card = anchor.closest('li,article,div[class*="Card"],div[class*="item"],div[class*="Item"]');
    if (!card) card = anchor.parentElement;
    const images = [...(card?.querySelectorAll('img') || [])]
      .map(img => img.currentSrc || img.src || img.dataset.src || img.dataset.ksLazyload || '')
      .filter(Boolean);
    const titleNode = card?.querySelector('[class*="title"],[class*="Title"],[class*="name"],[class*="Name"]');
    const shopNode = card?.querySelector('[class*="shop"],[class*="Shop"],[class*="seller"],[class*="Seller"]');
    rows.push({
      id: match[1], url: anchor.href,
      title: textOf(titleNode) || textOf(anchor),
      shop: textOf(shopNode), image: images[0] || '', images,
      text: textOf(card) || textOf(anchor),
    });
  }
  return rows;
}
"""


def _error_message(url: str, detail: str = "") -> str:
    lower = (url or "").lower()
    if any(token in lower for token in ("punish", "captcha", "verify", "deny")):
        return "淘宝触发安全验证，请在当前账号浏览器窗口完成验证后再重试"
    return f"淘宝搜索页没有读取到商品卡片{('：' + detail) if detail else ''}"


async def fetch_taobao_products(
    mgr: BrowserManager,
    identity: Identity,
    keyword: str,
    known_ids: set[str],
    *,
    max_pages: int = 3,
    block_media: bool = False,
) -> tuple[list[TaobaoProduct], str]:
    """按销量优先读取淘宝搜索结果，返回新商品与错误信息。"""
    page = await mgr.new_page(identity, block_media)
    products: list[TaobaoProduct] = []
    seen: set[str] = set()
    error = ""
    try:
        pages = max(1, min(int(max_pages or 3), 30))
        for page_index in range(pages):
            url = _SEARCH_URL.format(
                keyword=quote(keyword, safe=""), offset=page_index * 44)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_timeout(1800)
            except Exception:
                pass
            raw_rows = await page.evaluate(_CARD_JS)
            if not isinstance(raw_rows, list):
                raw_rows = []
            page_products = []
            for raw in raw_rows:
                item = parse_taobao_product(raw)
                if not item or item.aweme_id in seen:
                    continue
                seen.add(item.aweme_id)
                if item.aweme_id not in known_ids:
                    page_products.append(item)
            products.extend(page_products)
            if not raw_rows or all(
                    str(row.get("id") or "") and
                    f"taobao:{row.get('id')}" in known_ids
                    for row in raw_rows if isinstance(row, dict)):
                break
            if page_products == [] and page_index > 0:
                break
        if not products:
            error = _error_message(page.url)
    except Exception as exc:
        error = _error_message(getattr(page, "url", ""), repr(exc))
    finally:
        try:
            await page.close()
        except Exception:
            pass
    products.sort(key=lambda item: (item.sales_count, item.price, item.aweme_id), reverse=True)
    return products, error
