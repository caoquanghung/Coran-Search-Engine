import json
from pathlib import Path

from crawler.corpus import write_corpus
from crawler.image_records import extract_article_images
from crawler.parser import parse_article
from crawler.watch import CrawlLoop
from engine.image_indexer import build_image_index
from engine.image_searcher import ImageSearchService


def article_html() -> str:
    return """<html><head><meta property="og:image" content="https://cdn.test/storm.jpg"></head>
    <body><h1>Chứng khoán hôm nay</h1><article class="fck_detail">
    <p>Một bản tin đủ dài về thị trường đang thay đổi và có nhiều diễn biến mới trong nước hôm nay.</p>
    <figure><img data-src="https://cdn.test/storm.jpg" alt="Cơn bão trên biển">
      <figcaption>Ảnh vệ tinh ghi lại mắt bão và gió mạnh</figcaption></figure>
    <p>Ảnh chụp từ vệ tinh trong buổi sáng hôm nay tại vùng biển.</p>
    <figure><img src="https://cdn.test/market.jpg" alt="Bảng điện tử tại sàn giao dịch"></figure>
    <figure><img src="https://cdn.test/blank.jpg"></figure>
    </article></body></html>"""


def test_image_search_uses_image_context_globally(tmp_path: Path) -> None:
    article = parse_article(article_html(), "https://vnexpress.net/test-12345678.html")
    assert article is not None
    assert len(article.images or []) == 3
    assert article.images[0].caption.startswith("Ảnh vệ tinh")
    assert article.images[0].alt_text == "Cơn bão trên biển"
    assert len({item.image_id for item in article.images}) == 3
    docs = tmp_path / "documents.jsonl"
    images = tmp_path / "images.jsonl"
    write_corpus([article.to_dict()], docs, images)
    assert build_image_index(images, tmp_path / "image_index") >= 2
    service = ImageSearchService(tmp_path / "image_index")
    assert service.search("bão gió").results[0].image_url.endswith("storm.jpg")
    assert service.search("bao gio").results[0].image_url.endswith("storm.jpg")
    assert service.search("chứng khoán").total == 0
    assert service.search("").total == 0


class FakeCrawler:
    _clean_url = staticmethod(lambda url: url)

    def __init__(self, html: str):
        self.html = html
        self.fetches = 0

    def discover(self):
        return ["https://vnexpress.net/test-12345678.html"]

    def _get(self, url):
        self.fetches += 1
        return self.html


def test_watch_skips_known_and_recovers_pending_without_fetch(tmp_path: Path) -> None:
    crawler = FakeCrawler(article_html())
    settings = dict(documents_path=tmp_path / "documents.jsonl", images_path=tmp_path / "images.jsonl",
                    article_index=tmp_path / "index", image_index=tmp_path / "image_index",
                    state_path=tmp_path / "state.sqlite")
    loop = CrawlLoop(crawler, **settings)
    assert loop.run_once()["new"] == 1
    assert crawler.fetches == 1
    assert loop.run_once()["new"] == 0
    assert crawler.fetches == 1
    assert len(list(loop._documents())) == 1

    loop.db.execute("UPDATE articles SET status='pending',payload=?", (json.dumps(loop._documents()[0]),))
    loop.db.commit()
    restarted = CrawlLoop(crawler, **settings)
    assert restarted.run_once()["new"] == 0
    assert crawler.fetches == 1
    assert restarted.db.execute("SELECT status FROM articles").fetchone()[0] == "done"
    assert ImageSearchService(settings["image_index"]).search("bão").total == 1


def test_srcset_and_metadata_only_image() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("""<meta property="og:image" content="https://cdn.test/full.jpg">
    <article><figure><picture><source srcset="https://cdn.test/full.jpg 1200w, https://cdn.test/small.jpg 400w">
    <img src="data:image/gif;base64,AA==" alt="Bão lớn"></picture>
    <figcaption>Ảnh vệ tinh</figcaption></figure></article>""", "lxml")
    rows = extract_article_images(soup, source_doc_id="one", source_url="https://vnexpress.net/a-12345678.html", source_title="Tiêu đề")
    assert len(rows) == 1
    assert rows[0].image_url.endswith("full.jpg")
    assert rows[0].caption == "Ảnh vệ tinh"
    assert rows[0].searchable


def test_same_asset_from_two_articles_is_one_result(tmp_path: Path) -> None:
    first = parse_article(article_html(), "https://vnexpress.net/a-12345678.html")
    second = parse_article(article_html(), "https://vnexpress.net/b-12345679.html")
    assert first and second
    images = tmp_path / "images.jsonl"
    write_corpus([first.to_dict(), second.to_dict()], tmp_path / "documents.jsonl", images)
    build_image_index(images, tmp_path / "image_index")
    assert ImageSearchService(tmp_path / "image_index").search("mắt bão").total == 1
