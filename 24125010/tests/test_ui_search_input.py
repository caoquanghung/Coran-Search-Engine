import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine import build_index


def test_typing_and_sorting_keep_search_text(tmp_path: Path) -> None:
    app_path = tmp_path / "main.py"
    app_path.write_text((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"), encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    rows = [
        {"id": "1", "title": "Cơn bão trên biển", "description": "Thời tiết",
         "content": "Cơn bão đang tiến đến gần đất liền và gây mưa lớn trên biển.",
         "url": "https://vnexpress.net/storm-12345678.html"},
        {"id": "2", "title": "Công nghệ mới", "description": "Sản phẩm mới",
         "content": "Công nghệ mới giúp cải thiện trải nghiệm tìm kiếm thông tin.",
         "url": "https://vnexpress.net/technology-12345679.html"},
    ]
    dataset = data_dir / "documents.jsonl"
    dataset.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    build_index(dataset, tmp_path / "index")

    app = AppTest.from_file(str(app_path)).run(timeout=20)
    assert not app.exception
    app.text_input[0].set_value("bão").run(timeout=20)
    assert app.session_state["active_query"] == "bão"
    assert app.text_input[0].value == "bão"
    assert app.query_params["q"] == "bão"

    app.radio[0].set_value("Nhiều bình luận").run(timeout=20)
    assert app.session_state["active_query"] == "bão"
    assert app.text_input[0].value == "bão"

    app.text_input[0].set_value("công nghệ").run(timeout=20)
    assert app.session_state["active_query"] == "công nghệ"
    assert app.text_input[0].value == "công nghệ"
    assert app.query_params["page"] == "1"
    assert not app.exception
