import json
from pathlib import Path

from engine import SearchService, build_index
from engine.searcher import _snippet


def test_build_and_search_without_accents(tmp_path: Path) -> None:
    documents = tmp_path / "documents.jsonl"
    rows = [
        {
            "id": "1",
            "title": "Trí tuệ nhân tạo tại Việt Nam",
            "description": "Ứng dụng AI trong công nghệ",
            "content": "Trí tuệ nhân tạo đang thay đổi ngành công nghệ và tìm kiếm thông tin.",
            "url": "https://vnexpress.net/ai-12345678.html",
            "category": "Công nghệ",
            "comment_count": 42,
        },
        {
            "id": "2",
            "title": "Thị trường chứng khoán",
            "description": "Diễn biến mới nhất",
            "content": "Nhà đầu tư theo dõi thị trường tài chính trong phiên hôm nay.",
            "url": "https://vnexpress.net/tai-chinh-12345679.html",
            "category": "Kinh doanh",
            "comment_count": 12,
        },
    ]
    documents.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    index_dir = tmp_path / "index"
    assert build_index(documents, index_dir) == 2

    page = SearchService(index_dir).search("tri tue nhan tao")
    assert page.total == 1
    assert page.results[0].title == rows[0]["title"]
    assert page.results[0].comment_count == 42


def test_empty_query_returns_all(tmp_path: Path) -> None:
    documents = tmp_path / "documents.jsonl"
    documents.write_text(
        json.dumps(
            {
                "id": "1",
                "title": "Một tiêu đề",
                "description": "Mô tả",
                "content": "Nội dung bài viết đủ để được đưa vào chỉ mục tìm kiếm.",
                "url": "https://vnexpress.net/test-12345678.html",
                "comment_count": 1,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    index_dir = tmp_path / "index"
    build_index(documents, index_dir)
    assert SearchService(index_dir).search("").total == 1


def test_accent_insensitive_search_and_surface_tiebreak(tmp_path: Path) -> None:
    documents = tmp_path / "documents.jsonl"
    rows = [
        {
            "id": "storm",
            "title": "Một bài có bão",
            "description": "Cảnh báo thời tiết",
            "content": "Cảnh báo được phát trước khi cơn bão tiến vào đất liền.",
            "url": "https://vnexpress.net/storm-12345678.html",
        },
        {
            "id": "warning",
            "title": "Một bài chỉ có cảnh báo",
            "description": "Thông tin cảnh báo",
            "content": "Cơ quan chức năng cảnh báo người dân chú ý.",
            "url": "https://vnexpress.net/warning-12345679.html",
        },
    ]
    documents.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    index_dir = tmp_path / "index"
    build_index(documents, index_dir)

    page = SearchService(index_dir).search("bão")
    assert page.total == 2
    assert page.results[0].title == "Một bài có bão"
    assert "<mark>bão</mark>" in page.results[0].snippet

    unaccented = SearchService(index_dir).search("bao")
    assert unaccented.total == 2
    assert "<mark>" in unaccented.results[0].snippet


def test_snippet_highlights_normalized_matches() -> None:
    text = "Tỷ phú cảnh báo về tình hình. Gieo gió ắt sẽ gặt bão trong thời gian tới."
    snippet = _snippet(text, "bão", limit=70)
    assert "<mark>bão</mark>" in snippet
    assert "<mark>báo</mark>" in snippet


def test_sliding_window_maximizes_query_coverage() -> None:
    text = (
        "Mưa xuất hiện đầu bài. "
        + "nội dung không liên quan " * 8
        + "Cuối bài có bão đi kèm gió mạnh trên biển."
    )
    snippet = _snippet(text, "mua bao gio", limit=100)
    assert "<mark>bão</mark>" in snippet
    assert "<mark>gió</mark>" in snippet
    assert "<mark>Mưa</mark>" not in snippet
