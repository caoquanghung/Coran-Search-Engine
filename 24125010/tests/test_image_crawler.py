from crawler.image_crawler import extract_images


HTML = """
<html><head>
  <meta property="og:image" content="https://i1-vnexpress.vnecdn.net/main.jpg">
</head><body>
  <h1 class="title-detail">Bão gây gió mạnh trên biển</h1>
  <article class="fck_detail">
    <figure>
      <img data-src="https://i1-vnexpress.vnecdn.net/storm.jpg" alt="Mắt bão">
      <figcaption>Ảnh vệ tinh cho thấy bão và gió mạnh.</figcaption>
    </figure>
    <figure>
      <img src="https://i1-vnexpress.vnecdn.net/people.jpg" alt="Người dân">
      <figcaption>Người dân đi lại trên đường.</figcaption>
    </figure>
  </article>
</body></html>
"""


def test_extract_images_ranks_by_unaccented_query_coverage() -> None:
    images = extract_images(HTML, "https://vnexpress.net/test-12345678.html", "bao gio")
    assert len(images) == 3
    assert images[0].image_url.endswith("storm.jpg")
    assert images[0].score[0] == 2
    assert "bão" in images[0].caption


def test_extract_images_deduplicates_urls() -> None:
    html = HTML.replace(
        "https://i1-vnexpress.vnecdn.net/people.jpg",
        "https://i1-vnexpress.vnecdn.net/storm.jpg",
    )
    images = extract_images(html, "https://vnexpress.net/test-12345678.html", "bao")
    assert len(images) == 2
