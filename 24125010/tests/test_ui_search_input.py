import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine import build_index, build_image_index


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
    rows.extend({"id": str(number), "title": f"Bản tin bão {number}", "description": "Thông tin thời tiết",
                 "content": "Cơn bão gây mưa lớn trên biển.", "url": f"https://vnexpress.net/storm-{number:08d}.html"}
                for number in range(3, 15))
    dataset = data_dir / "documents.jsonl"
    dataset.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    build_index(dataset, tmp_path / "index")
    images = data_dir / "images.jsonl"
    images.write_text(json.dumps({"image_id": "storm", "image_url": "https://cdn.test/storm.jpg",
                                 "source_doc_id": "1", "source_url": rows[0]["url"],
                                 "caption": "Cơn bão trên biển", "searchable": True}) + "\n")
    build_image_index(images, tmp_path / "image_index")

    app = AppTest.from_file(str(app_path)).run(timeout=20)
    assert not app.exception
    app.text_input[0].set_value("bão").run(timeout=20)
    assert app.session_state["active_query"] == "bão"
    assert app.text_input[0].value == "bão"
    assert app.query_params["q"] == "bão"
    app.button(key="next_page").click().run(timeout=20)
    assert app.query_params["page"] == "2"
    assert app.text_input[0].value == "bão"

    app.selectbox(key="sort_order").set_value("Nhiều bình luận").run(timeout=20)
    assert app.session_state["active_query"] == "bão"
    assert app.text_input[0].value == "bão"
    assert app.query_params["page"] == "1"

    app.text_input[0].set_value("công nghệ").run(timeout=20)
    assert app.session_state["active_query"] == "công nghệ"
    assert app.text_input[0].value == "công nghệ"
    assert app.query_params["page"] == "1"
    assert not app.exception

    app.radio(key="result_view").set_value("Hình ảnh").run(timeout=20)
    assert app.query_params["view"] == "images"
    assert app.text_input[0].value == "công nghệ"
    app.radio(key="result_view").set_value("Tất cả").run(timeout=20)
    assert app.selectbox(key="sort_order").value == "Nhiều bình luận"
    assert app.text_input[0].value == "công nghệ"
    app.button(key="clear_search").click().run(timeout=20)
    assert app.session_state["active_query"] == ""
    assert app.text_input[0].value == ""
    app.button(key="suggest_Công nghệ").click().run(timeout=20)
    assert app.session_state["active_query"] == "Công nghệ"
    assert not app.exception
