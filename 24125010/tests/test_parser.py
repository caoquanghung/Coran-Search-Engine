from crawler.parser import parse_article


HTML = """
<html><head>
  <link rel="canonical" href="https://vnexpress.net/bai-thu-nghiem-12345678.html">
  <meta property="article:section" content="Công nghệ">
  <meta property="article:published_time" content="2026-10-20T08:00:00+07:00">
</head><body>
  <h1 class="title-detail">AI hỗ trợ tìm kiếm tiếng Việt</h1>
  <p class="description">Một hệ thống truy hồi thông tin mới được giới thiệu.</p>
  <article class="fck_detail">
    <p>Đây là đoạn nội dung đầu tiên đủ dài để bộ phân tích xác định đây là một bài báo hợp lệ.</p>
    <p>Công cụ sử dụng chỉ mục đảo và mô hình BM25 để xếp hạng các tài liệu phù hợp.</p>
  </article>
  <span class="count-comment">1.234 bình luận</span>
</body></html>
"""


def test_parse_article() -> None:
    article = parse_article(HTML, "https://vnexpress.net/anything")
    assert article is not None
    assert article.id == "12345678"
    assert article.title == "AI hỗ trợ tìm kiếm tiếng Việt"
    assert "BM25" in article.content
    assert article.category == "Công nghệ"
    assert article.comment_count == 1234


def test_reject_non_article() -> None:
    assert parse_article("<html><h1>Trang chủ</h1></html>", "https://vnexpress.net") is None
