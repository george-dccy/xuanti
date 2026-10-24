"""使用 CreatorHub 管理的登录态 Chrome 读取淘宝热销搜索结果。"""
from __future__ import annotations

from urllib.parse import quote

from .identity import Identity
from .manager import BrowserManager
from ..platforms.taobao import TaobaoProduct, parse_taobao_product


_SEARCH_URL = "https://s.taobao.com/search?q={keyword}&sort=sale-desc&s={offset}"

_CARD_JS = r"""
() => {
  const absolute = value => {
    try { return new URL(String(value || ''), location.href).href; }
    catch (_) { return ''; }
  };
  const textOf = node => (node?.innerText || node?.textContent || '')
    .replace(/\s+/g, ' ').trim();
  const imageOf = img => {
    if (!img) return '';
    const attrs = ['data-src', 'data-lazyload', 'data-original',
      'data-ks-lazyload', 'data-lazy-src', 'src'];
    for (const attr of attrs) {
      const value = img.getAttribute(attr) || '';
      if (value && !value.startsWith('data:')) return absolute(value);
    }
    const srcset = img.getAttribute('srcset') || '';
    const first = srcset.split(',')[0]?.trim().split(/\s+/)[0] || '';
    return first ? absolute(first) : '';
  };
  const idFrom = value => {
    const raw = String(value || '');
    const match = raw.match(/(?:[?&]id=|[?&]item_id=|\/item\/)(\d{6,})/i);
    return match ? match[1] : '';
  };
  const cardOf = node => node?.closest(
    'li,article,[data-item-id],[data-itemid],div[class*="item"],div[class*="Item"]'
  ) || node?.parentElement;
  const nodes = [...document.querySelectorAll('a[href], [data-item-id], [data-itemid]')]
    .filter(node => {
      const href = node.href || node.getAttribute('href') || '';
      return /(?:item\.taobao\.com|detail\.tmall\.com|detail\.taobao\.com)/i.test(href)
        || idFrom(node.getAttribute('data-item-id'))
        || idFrom(node.getAttribute('data-itemid'));
    });
  const seen = new Set();
  const rows = [];
  const add = (id, sourceUrl, card, fallbackTitle = '', fallbackImage = '', fallbackPrice = '') => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    const images = [...(card?.querySelectorAll('img') || [])]
      .map(imageOf).filter(Boolean);
    if (fallbackImage && !images.includes(fallbackImage)) images.unshift(fallbackImage);
    const titleNode = card?.querySelector(
      '[class*="title"],[class*="Title"],[class*="name"],[class*="Name"]'
    );
    const shopNode = card?.querySelector(
      '[class*="shop"],[class*="Shop"],[class*="seller"],[class*="Seller"]'
    );
    const priceNode = card?.querySelector(
      '[class*="price"],[class*="Price"],[data-price]'
    );
    rows.push({
      id, url: absolute(sourceUrl),
      title: textOf(titleNode) || fallbackTitle || textOf(card),
      shop: textOf(shopNode),
      price: priceNode?.getAttribute('data-price') || textOf(priceNode) || fallbackPrice,
      image: images[0] || '', images,
      text: textOf(card) || fallbackTitle,
    });
  };
  for (const node of nodes) {
    const href = node.href || node.getAttribute('href') || '';
    const id = idFrom(href) || idFrom(node.getAttribute('data-item-id'))
      || idFrom(node.getAttribute('data-itemid'));
    const card = cardOf(node);
    add(id, href, card, node.getAttribute('title') || node.getAttribute('aria-label') || '');
  }
  // 某些版本只把商品卡片放进 JSON-LD，不渲染可识别的商品链接。
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const value = JSON.parse(script.textContent || 'null');
      const entries = Array.isArray(value) ? value : [value];
      for (const item of entries) {
        if (!item || typeof item !== 'object') continue;
        const id = idFrom(item.productID || item.sku || item.url);
        const image = Array.isArray(item.image) ? item.image[0] : item.image;
        const price = item.offers?.price || '';
        add(id, item.url || '', null, item.name || '', absolute(image), price);
      }
    } catch (_) {}
  }
  const bodyText = textOf(document.body);
  const blocked = rows.length === 0 && /(安全验证|滑动验证|验证码|访问受限|请完成验证)/.test(bodyText);
  return {rows, blocked, title: document.title || '', body: bodyText.slice(0, 300)};
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
    saw_rows = False
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
            snapshot = await page.evaluate(_CARD_JS)
            if not isinstance(snapshot, dict):
                snapshot = {}
            raw_rows = snapshot.get("rows") or []
            if snapshot.get("blocked"):
                return [], "淘宝搜索页触发安全验证，请在当前账号浏览器窗口完成验证后再重试"
            saw_rows = saw_rows or bool(raw_rows)
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
        if not products and not saw_rows:
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
