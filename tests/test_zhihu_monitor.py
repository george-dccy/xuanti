"""Offline contracts for the Zhihu creator monitor."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import select

import app.engine.monitor as monitor
import app.db as db
from app.browser.manager import cookie_string_to_state
from app.engine.monitor import MonitorEngine
from app.models import ContentRecord, DouyinAccount, MonitorTarget
from app.platforms.zhihu.extract import parse_zhihu_items
from app.platforms.zhihu.resolve import resolve_zhihu_user_token
from test_project_optimizations import local_project, store


def test_zhihu_user_token_accepts_people_urls_and_rejects_content_urls():
    assert resolve_zhihu_user_token("https://www.zhihu.com/people/wen-jie-16-47/answers") == "wen-jie-16-47"
    assert resolve_zhihu_user_token("user:wen-jie-16-47") == "wen-jie-16-47"
    assert resolve_zhihu_user_token("wen-jie-16-47") == "wen-jie-16-47"
    assert resolve_zhihu_user_token("https://www.zhihu.com/question/123/answer/456") is None
    assert resolve_zhihu_user_token("https://example.com/people/wen-jie-16-47") is None


def test_zhihu_items_normalize_answers_and_articles():
    items = parse_zhihu_items(
        [{
            "id": 101,
            "question": {"id": 9, "title": "如何做长期监控"},
            "excerpt": "<p>先把目标和结果分开。</p>",
            "created_time": 1_700_000_000,
            "voteup_count": 12,
            "comment_count": 3,
            "author": {"name": "作者 A", "avatar_url": "https://pic.example/a.jpg"},
        }],
        [{
            "id": "202",
            "title": "一篇文章",
            "created": 1_700_000_100,
            "voteup_count": 5,
            "comment_count": 1,
            "url": "https://zhuanlan.zhihu.com/p/202",
        }],
    )
    assert [item.aweme_id for item in items] == ["article:202", "answer:101"]
    assert items[1].desc.startswith("如何做长期监控｜先把目标和结果分开。")
    assert items[1].source_url.endswith("/question/9/answer/101")
    assert items[0].media_type == "text"


def test_zhihu_cookie_state_uses_zhihu_domain():
    state = cookie_string_to_state("z_c0=secret; d_c0=session", "zhihu")
    assert '"domain": ".zhihu.com"' in state


def test_zhihu_monitor_records_text_without_download(local_project, monkeypatch):
    local_project.cfg.risk_control.enabled = False
    engine = MonitorEngine(local_project.cfg, local_project.browser)
    account = store(DouyinAccount(
        platform="zhihu", status="active", storage_state=cookie_string_to_state("z_c0=x", "zhihu"),
        nickname="知乎读取号"))
    target = store(MonitorTarget(
        platform="zhihu", sec_uid="creator-token", account_id=account,
        created_at=datetime.utcnow() - timedelta(days=1), download_enabled=False))
    work = parse_zhihu_items(
        [{
            "id": 101,
            "question": {"id": 9, "title": "知乎监控测试"},
            "created_time": int(datetime.utcnow().timestamp()),
            "voteup_count": 8,
            "comment_count": 2,
            "url": "https://www.zhihu.com/question/9/answer/101",
        }],
        [],
    )[0]
    monkeypatch.setattr(engine, "_identity_proxy", lambda _account: (SimpleNamespace(), ""))
    monkeypatch.setattr(
        monitor, "fetch_zhihu_works",
        AsyncMock(return_value=([work], {"nickname": "知乎作者"}, "")),
    )
    engine._notify_new = AsyncMock()

    result = asyncio.run(engine.scan_target(target))

    assert result["ok"] is True
    assert result["new"] == 1
    with db.get_session() as session:
        record = session.exec(select(ContentRecord)).one()
        assert record.platform == "zhihu"
        assert record.media_type == "text"
        assert record.download_status == "skipped"
        assert record.source_url.endswith("/question/9/answer/101")
        assert session.get(MonitorTarget, target).nickname == "知乎作者"
    engine._notify_new.assert_not_awaited()
