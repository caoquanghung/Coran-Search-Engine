from crawler.crawler import VnExpressCrawler


def _page(article_id: int, comments: int) -> str:
    return f"""<html><h1>Article {article_id}</h1><article class="fck_detail">
    <p>This is a sufficiently long article paragraph with enough content to pass the parser validation rule.</p>
    </article><span class="count-comment">{comments} bình luận</span></html>"""


def test_crawler_retains_all_candidates_instead_of_top_comment_subset() -> None:
    crawler = VnExpressCrawler([], max_documents=3, candidate_limit=3, delay=0)
    urls = [f"https://vnexpress.net/article-{number:08d}.html" for number in (1, 2, 3)]
    pages = dict(zip(urls, (_page(1, 1), _page(2, 100), _page(3, 2))))
    crawler.discover = lambda: urls
    crawler._get = lambda url: pages[url]

    articles = crawler.crawl()

    assert [article.id for article in articles] == ["00000001", "00000002", "00000003"]
    assert [article.comment_count for article in articles] == [1, 100, 2]
