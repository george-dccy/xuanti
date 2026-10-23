"""淘宝搜索卡片的字段归一化。

页面字段会随淘宝前端版本变化；采集器只把 DOM 卡片转成稳定的商品对象，
不依赖淘宝私有签名接口。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

_NUMBER_RE = re.compile(r"([\d,.]+)\s*(万|亿)?")
_PRICE_RE = re.compile(r"[¥￥]\s*([\d,.]+)")
_SALES_RE = re.compile(
    r"(?:月销|已售|付款|收货|销量|人付款|人收货)\s*([\d,.]+\s*[万亿]?)")
_ID_RE = re.compile(r"(?:[?&]id=|/item/)(\d+)")


def _number(value: Any) -> int:
    text = str(value or "").strip().replace(",", "").replace("+", "")
    match = _NUMBER_RE.search(text)
    if not match:
        return 0
    try:
        scale = {"万": 10_000, "亿": 100_000_000}.get(match.group(2) or "", 1)
        return int(float(match.group(1)) * scale)
    except (TypeError, ValueError):
        return 0


def _price(text: str) -> float:
    match = _PRICE_RE.search(text or "")
    if not match:
        return 0.0
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return 0.0


def _sales(text: str) -> int:
    match = _SALES_RE.search(text or "")
    return _number(match.group(1)) if match else 0


def _image_url(value: Any) -> str:
    url = str(value or "").strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return ""


def _extension(url: str) -> str:
    suffix = (urlsplit(url).path.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
              if "." in urlsplit(url).path.rsplit("/", 1)[-1] else "jpg")
    suffix = suffix.lower().split("_")[0]
    return suffix if suffix in {"jpg", "jpeg", "png", "webp"} else "jpg"


@dataclass
class TaobaoMediaItem:
    url: str
    kind: str
    ext: str
    index: int = 0


@dataclass
class TaobaoProduct:
    aweme_id: str
    desc: str
    author_name: str
    media_type: str = "images"
    medias: list[TaobaoMediaItem] = field(default_factory=list)
    cover: str = ""
    quality_label: str = ""
    like_count: int = 0
    comment_count: int = 0
    duration: int = 0
    avatar: str = ""
    platform: str = "taobao"
    sales_count: int = 0
    price: float = 0.0
    shop_name: str = ""
    source_url: str = ""


def parse_taobao_product(raw: dict) -> TaobaoProduct | None:
    """解析一个 DOM 商品卡片快照。"""
    if not isinstance(raw, dict):
        return None
    source_url = str(raw.get("url") or "").strip()
    match = _ID_RE.search(source_url)
    product_id = str(raw.get("id") or (match.group(1) if match else "")).strip()
    if not product_id:
        return None
    text = str(raw.get("text") or "")
    title = str(raw.get("title") or "").strip()
    if not title:
        title = next((line.strip() for line in text.splitlines() if line.strip()), "淘宝商品")
    images = []
    for value in raw.get("images") or []:
        url = _image_url(value)
        if url and url not in images:
            images.append(url)
    if not images:
        cover = _image_url(raw.get("image"))
        if cover:
            images.append(cover)
    if not images:
        return None
    return TaobaoProduct(
        aweme_id=f"taobao:{product_id}",
        desc=title[:1000],
        author_name=str(raw.get("shop") or "淘宝店铺").strip()[:120],
        medias=[TaobaoMediaItem(url=url, kind="image", ext=_extension(url), index=i)
                for i, url in enumerate(images)],
        cover=images[0],
        sales_count=_sales(str(raw.get("sales") or text)),
        price=_price(str(raw.get("price") or text)),
        shop_name=str(raw.get("shop") or "").strip()[:120],
        source_url=source_url,
    )
