"""Dependency-light contracts for the Taobao hot-product parser."""
from app.platforms.taobao.extract import parse_taobao_product
from app.engine.share_downloader import detect_platform


def test_taobao_product_extracts_sales_price_and_images():
    item = parse_taobao_product({
        "id": "123456789",
        "url": "https://item.taobao.com/item.htm?id=123456789",
        "title": "女装连衣裙 春季新款",
        "shop": "示例女装店",
        "text": "女装连衣裙 春季新款 ¥129.00 月销 2.3万",
        "images": ["//img.alicdn.com/demo.jpg", "//img.alicdn.com/color-1.jpg"],
    })
    assert item is not None
    assert item.aweme_id == "taobao:123456789"
    assert item.price == 129.0
    assert item.sales_count == 23000
    assert item.shop_name == "示例女装店"
    assert item.medias[0].url == "https://img.alicdn.com/demo.jpg"
    assert len(item.medias) == 1
    assert item.source_url.endswith("id=123456789")


def test_taobao_domains_are_classified_for_target_cleaning():
    assert detect_platform("https://item.taobao.com/item.htm?id=1") == "taobao"
    assert detect_platform("https://detail.tmall.com/item.htm?id=1") == "taobao"
