"""Google-inspired article and image search with persistent input state."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from engine import ImageSearchService, SearchService, build_index, image_index_stats, index_stats
from engine.hybrid_searcher import HybridImageSearchService, HybridSearchService
from engine.vector_index import warmup_encoder
from ui.presentation import BRAND, article, brand, empty_state, footer, image_grid, styles

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "documents.jsonl"
INDEX_DIR = ROOT / "index"
IMAGE_INDEX_DIR = ROOT / "image_index"
VECTOR_INDEX_DIR = ROOT / "vector_index"
MODEL_DIR = ROOT / "models" / "multilingual-e5-small"

page_query = str(st.query_params.get("q", "")).strip()
st.set_page_config(page_title=f"{page_query} - {BRAND}" if page_query else BRAND,
                   page_icon="🔎", layout="wide", initial_sidebar_state="collapsed")


@st.cache_resource(show_spinner=False, max_entries=2)
def get_service(index_mtime: float, vector_generation: str):
    del index_mtime
    if vector_generation:
        return HybridSearchService(INDEX_DIR, VECTOR_INDEX_DIR, model_dir=MODEL_DIR)
    return SearchService(INDEX_DIR)


def _index_mtime(index_dir: Path) -> float:
    return max((item.stat().st_mtime_ns for item in index_dir.glob("*.toc")), default=0)


@st.cache_resource(show_spinner=False, max_entries=2)
def get_image_service(index_mtime: float, vector_generation: str):
    del index_mtime
    if vector_generation:
        return HybridImageSearchService(IMAGE_INDEX_DIR, VECTOR_INDEX_DIR, model_dir=MODEL_DIR)
    return ImageSearchService(IMAGE_INDEX_DIR)


def vector_generation() -> str:
    manifest_path = VECTOR_INDEX_DIR / "manifest.json"
    corpus_path = DATASET.parent / "corpus_manifest.json"
    if not manifest_path.exists() or not corpus_path.exists() or not (MODEL_DIR / "model_info.json").exists():
        return ""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    model = json.loads((MODEL_DIR / "model_info.json").read_text(encoding="utf-8"))
    if manifest.get("model") != model:
        return ""
    if any(manifest.get(key) != corpus.get(key) for key in ("documents_sha256", "images_sha256")):
        return ""
    return manifest["generation"]


stats = index_stats(INDEX_DIR)
if not stats["ready"]:
    if DATASET.exists() and DATASET.stat().st_size:
        with st.spinner("Đang chuẩn bị dữ liệu…"):
            build_index(DATASET, INDEX_DIR)
        st.cache_resource.clear()
        st.rerun()
    st.info("Chưa có dữ liệu tìm kiếm. Hãy chạy scripts/crawl.py và scripts/build_index.py.")
    st.stop()

query_from_url = str(st.query_params.get("q", "")).strip()
if st.session_state.get("_last_url_query") != query_from_url:
    st.session_state["search_draft"] = query_from_url
    st.session_state["active_query"] = query_from_url
    st.session_state["_last_url_query"] = query_from_url

view_from_url = "Hình ảnh" if st.query_params.get("view") == "images" else "Tất cả"
st.session_state["result_view"] = view_from_url
st.session_state["_last_url_view"] = view_from_url
# Rehydrate conditional widgets from the URL before rendering them. Streamlit
# may clean up their widget values while the other tab/homepage is displayed.
st.session_state["sort_order"] = "Nhiều bình luận" if st.query_params.get("sort") == "comments" else "Liên quan nhất"


def submit_search() -> None:
    query = st.session_state["search_draft"].strip()
    st.session_state["active_query"] = query
    st.session_state["_last_url_query"] = query
    st.query_params["q"] = query
    st.query_params["page"] = "1"


def clear_search() -> None:
    st.session_state["search_draft"] = ""
    submit_search()


def suggested_search(query: str) -> None:
    st.session_state["search_draft"] = query
    submit_search()


def switch_view(view: str | None = None) -> None:
    if view is not None:
        st.session_state["result_view"] = view
    selected = st.session_state["result_view"]
    st.session_state["_last_url_view"] = selected
    st.query_params["view"] = "images" if selected == "Hình ảnh" else "all"
    st.query_params["page"] = "1"


def change_sort() -> None:
    st.query_params["sort"] = "comments" if st.session_state["sort_order"] == "Nhiều bình luận" else "relevance"
    st.query_params["page"] = "1"


def go_to_page(page: int) -> None:
    st.query_params["page"] = str(page)


def pagination(current: int, pages: int) -> None:
    if pages <= 1:
        return
    start = max(1, min(current - 2, pages - 4))
    numbers = list(range(start, min(pages + 1, start + 5)))
    with st.container(key="pagination"):
        columns = st.columns([1.9] + [1] * len(numbers) + [1.9], gap="small")
        with columns[0]:
            st.button("Trước", key="previous_page", icon=":material/chevron_left:", disabled=current <= 1,
                      on_click=go_to_page, args=(current - 1,), use_container_width=True)
        for column, number in zip(columns[1:-1], numbers):
            with column:
                st.button(str(number), key=f"page_{number}", type="primary" if number == current else "secondary",
                          disabled=number == current, on_click=go_to_page, args=(number,), use_container_width=True)
        with columns[-1]:
            st.button("Tiếp", key="next_page", icon=":material/chevron_right:", disabled=current >= pages,
                      on_click=go_to_page, args=(current + 1,), use_container_width=True)


query = st.session_state["active_query"]
home = not query
st.markdown(styles(home), unsafe_allow_html=True)
with st.container(key="topbar"):
    logo, search, locale = st.columns([1.7, 7.6, 1], vertical_alignment="center")
    with logo:
        st.markdown(brand(), unsafe_allow_html=True)
    with search:
        with st.container(key="search_pill"):
            field, clear, submit = st.columns([12, 1, 1], gap="small", vertical_alignment="center")
            with field:
                st.text_input("Từ khóa", key="search_draft", on_change=submit_search,
                              label_visibility="collapsed", placeholder="Tìm kiếm tin tức, hình ảnh…")
            with clear:
                st.button("Xóa nội dung", icon=":material/close:", key="clear_search", on_click=clear_search,
                          disabled=not st.session_state["search_draft"], help="Xóa nội dung tìm kiếm")
            with submit:
                st.button("Tìm kiếm", icon=":material/search:", key="submit_search", on_click=submit_search, help="Tìm kiếm")
    with locale:
        st.markdown('<div class="header-locale">Tiếng Việt</div>', unsafe_allow_html=True)

semantic_generation = vector_generation()
if semantic_generation:
    warmup_encoder(MODEL_DIR)

if home:
    st.markdown('<p class="home-subtitle">Khám phá tin tức và hình ảnh theo cách bạn nghĩ.</p>', unsafe_allow_html=True)
    with st.container(key="home_suggestions"):
        for column, suggestion in zip(st.columns(4, gap="small"), ("Thời sự", "Công nghệ", "Du lịch", "Sức khỏe")):
            with column:
                st.button(suggestion, key=f"suggest_{suggestion}", on_click=suggested_search, args=(suggestion,), use_container_width=True)
    st.markdown(footer(stats["documents"], home=True, semantic=bool(semantic_generation)), unsafe_allow_html=True)
    st.stop()

with st.container(key="nav_shell"):
    with st.container(key="navigation"):
        views, tools = st.columns([6, 2], vertical_alignment="center")
        with views:
            st.radio("Loại kết quả", ("Tất cả", "Hình ảnh"), key="result_view", horizontal=True,
                     label_visibility="collapsed", on_change=switch_view)
        with tools:
            if st.session_state["result_view"] == "Tất cả":
                st.selectbox("Sắp xếp", ("Liên quan nhất", "Nhiều bình luận"), key="sort_order",
                             label_visibility="collapsed", on_change=change_sort)

try:
    current_page = max(1, int(st.query_params.get("page", "1")))
except (TypeError, ValueError):
    current_page = 1


def search_images(page: int, size: int):
    if not image_index_stats(IMAGE_INDEX_DIR)["ready"]:
        return None
    return get_image_service(_index_mtime(IMAGE_INDEX_DIR), semantic_generation).search(query, page=page, page_size=size)


if st.session_state["result_view"] == "Hình ảnh":
    with st.container(key="images_shell"):
        try:
            with st.spinner("Đang tìm hình ảnh…"):
                image_page = search_images(current_page, 20)
            if image_page is None:
                st.info("Chưa có dữ liệu hình ảnh để tìm kiếm.")
            elif image_page.results:
                st.markdown(f'<div class="search-meta">Khoảng {image_page.total:,} hình ảnh phù hợp</div>', unsafe_allow_html=True)
                st.markdown(image_grid(image_page.results), unsafe_allow_html=True)
                pagination(current_page, image_page.pages)
            else:
                st.markdown(empty_state(query, images=True), unsafe_allow_html=True)
        except Exception as exc:
            st.error(f"Không thể tìm hình ảnh: {exc}")
else:
    with st.container(key="results_shell"):
        try:
            with st.spinner("Đang tìm kiếm…"):
                result_page = get_service(_index_mtime(INDEX_DIR), semantic_generation).search(
                    query, page=current_page, page_size=10,
                    sort_by="comments" if st.session_state["sort_order"] == "Nhiều bình luận" else "relevance",
                )
        except Exception as exc:
            st.error(f"Không thể xử lý truy vấn: {exc}")
            st.stop()
        st.markdown(f'<div class="search-meta">Khoảng {result_page.total:,} kết quả ({result_page.elapsed_ms / 1000:.2f} giây)</div>', unsafe_allow_html=True)
        try:
            image_page = search_images(1, 4)
            if image_page and image_page.results:
                with st.container(key="image_preview"):
                    heading, more = st.columns([4, 2], vertical_alignment="center")
                    with heading:
                        st.markdown('<div class="section-heading">Hình ảnh</div>', unsafe_allow_html=True)
                    with more:
                        st.button("Xem tất cả", icon=":material/arrow_forward:", key="open_images", on_click=switch_view, args=("Hình ảnh",))
                    st.markdown(image_grid(image_page.results, preview=True), unsafe_allow_html=True)
        except Exception:
            st.caption("Hình ảnh tạm thời chưa sẵn sàng.")
        if result_page.results:
            for item in result_page.results:
                st.markdown(article(item), unsafe_allow_html=True)
            pagination(current_page, result_page.pages)
        else:
            st.markdown(empty_state(query), unsafe_allow_html=True)

st.markdown(footer(stats["documents"], home=False, semantic=bool(semantic_generation)), unsafe_allow_html=True)
