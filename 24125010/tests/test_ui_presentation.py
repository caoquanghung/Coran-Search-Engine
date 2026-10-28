from types import SimpleNamespace

from ui.presentation import article, image_grid


def test_image_descriptions_and_urls_are_escaped():
    row = SimpleNamespace(description='<script>alert("x")</script>', source_title="Title",
                          source_url="javascript:alert(1)", image_url='https://cdn.test/a.jpg" onerror="alert(1)')
    markup = image_grid([row])
    assert "<script>" not in markup
    assert "javascript:" not in markup
    assert 'href="#"' in markup
    assert ' onerror="' not in markup


def test_article_title_and_source_are_escaped():
    row = SimpleNamespace(url="https://vnexpress.net/test", category="<Tin tức>", published_at="2026-10-28",
                          title="<script>Title</script>", snippet="An engine-escaped <mark>snippet</mark>", comment_count=12)
    markup = article(row)
    assert "<script>" not in markup
    assert "&lt;Tin tức&gt;" in markup
    assert "28 thg 10, 2026" in markup
    assert "<mark>snippet</mark>" in markup
