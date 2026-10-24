"""知乎回答与文章的统一作品字段。

接口字段形状参考 OpenCLI 的知乎适配器（Apache-2.0，
https://github.com/jackwener/OpenCLI/tree/main/clis/zhihu），这里是
CreatorHub 自己的 Python 归一化实现。
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().replace(",", "").replace("+", "")
    if not text:
        return 0
    try:
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        if text.endswith("亿"):
            return int(float(text[:-1]) * 100000000)
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _timestamp(*values: Any) -> int:
    for value in values:
        stamp = _to_int(value)
        if stamp:
            return stamp // 1000 if stamp > 10_000_000_000 else stamp
    return 0


def _plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _HTML_TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


@dataclass
class ZhihuWork:
    """与监控引擎兼容的文本作品对象。"""

    aweme_id: str
    kind: str
    desc: str
    create_time: int = 0
    cover: str = ""
    like_count: int = 0
    comment_count: int = 0
    source_url: str = ""
    author_name: str = ""
    author_avatar: str = ""
    media_type: str = "text"
    quality_label: str = ""
    medias: list = field(default_factory=list)
    platform: str = "zhihu"

def parse_zhihu_work(raw: dict, kind: str) -> ZhihuWork | None:
    """把知乎 answer/article 原始对象转成监控可用的文本作品。"""
    if not isinstance(raw, dict):
        return None
    item_id = str(raw.get("id") or "").strip()
    if not item_id:
        return None
    kind = "article" if kind == "article" else "answer"
    author = raw.get("author") or {}
    if not isinstance(author, dict):
        author = {}
    author_name = str(author.get("name") or "").strip()
    author_avatar = str(
        author.get("avatar_url") or author.get("avatarUrl") or "").strip()
    question = raw.get("question") or {}
    if not isinstance(question, dict):
        question = {}
    title = _plain_text(raw.get("title") or question.get("title"))
    excerpt = _plain_text(raw.get("excerpt"))
    if kind == "answer":
        desc = title or excerpt or "知乎回答"
        question_id = str(question.get("id") or "").strip()
        source_url = str(raw.get("url") or "").strip()
        if not source_url and question_id:
            source_url = f"https://www.zhihu.com/question/{question_id}/answer/{item_id}"
    else:
        desc = title or excerpt or "知乎文章"
        source_url = str(raw.get("url") or "").strip()
        if not source_url:
            source_url = f"https://zhuanlan.zhihu.com/p/{item_id}"
    if excerpt and title and excerpt not in title:
        desc = f"{title}｜{excerpt}"
    reaction = raw.get("reaction_statistics") or {}
    if not isinstance(reaction, dict):
        reaction = {}
    return ZhihuWork(
        aweme_id=f"{kind}:{item_id}",
        kind=kind,
        desc=desc[:1000],
        create_time=_timestamp(
            raw.get("created_time"), raw.get("created"),
            raw.get("updated_time"), raw.get("updated")),
        like_count=_to_int(
            raw.get("voteup_count")
            or reaction.get("like_count")),
        comment_count=_to_int(raw.get("comment_count")),
        source_url=source_url,
        author_name=author_name,
        author_avatar=author_avatar,
    )


def parse_zhihu_items(answer_rows: list, article_rows: list) -> list[ZhihuWork]:
    """归一化并按发布时间倒序去重。"""
    rows: list[ZhihuWork] = []
    seen: set[str] = set()
    for kind, values in (("answer", answer_rows), ("article", article_rows)):
        for raw in values or []:
            item = parse_zhihu_work(raw, kind)
            if not item or item.aweme_id in seen:
                continue
            seen.add(item.aweme_id)
            rows.append(item)
    rows.sort(key=lambda item: (item.create_time, item.aweme_id), reverse=True)
    return rows


def parse_zhihu_search_items(payload: dict) -> list[ZhihuWork]:
    """解析知乎 ``/api/v4/search_v3`` 的搜索结果。

    搜索响应的外层类型是 ``search_result``，真正的回答或文章放在
    ``object`` 中；不要把外层卡片当成作品，否则会丢掉题目、链接和作者字段。
    """
    if not isinstance(payload, dict):
        return []
    rows: list[ZhihuWork] = []
    seen: set[str] = set()
    for entry in payload.get("data") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in {"search_result", "zvideo"}:
            continue
        raw = entry.get("object")
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip().lower()
        # 关键词监控先覆盖回答和文章；视频搜索结果没有文本下载语义，
        # 避免把它伪装成“回答 / 文章”入库。
        if kind not in {"answer", "article"}:
            continue
        item = parse_zhihu_work(raw, kind)
        if item and item.aweme_id not in seen:
            seen.add(item.aweme_id)
            rows.append(item)
    rows.sort(key=lambda item: (item.create_time, item.aweme_id), reverse=True)
    return rows
