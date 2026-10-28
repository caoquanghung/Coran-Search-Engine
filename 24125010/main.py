"""Giao diện Streamlit cho VnExpress Search MVP."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from engine import ImageSearchService, SearchService, build_index, image_index_stats, index_stats


ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "documents.jsonl"
INDEX_DIR = ROOT / "index"
IMAGE_INDEX_DIR = ROOT / "image_index"

st.set_page_config(page_title="VnSearch", page_icon="🔎", layout="wide")
st.markdown(
    """
    <style>
      .block-container {max-width: 980px; padding-top: 2rem;}
      .brand {font: 600 2.5rem Arial,sans-serif; letter-spacing:-2px; margin:0 0 .7rem}
      .brand span:nth-child(1),.brand span:nth-child(4){color:#4285f4}
      .brand span:nth-child(2),.brand span:nth-child(6){color:#ea4335}
      .brand span:nth-child(3){color:#fbbc05}.brand span:nth-child(5){color:#34a853}
      .search-meta {color:#70757a;font-size:.88rem;margin:1rem 0 1.4rem}
      .result {font-family:Arial,sans-serif;margin:0 0 1.8rem;max-width:760px}
      .result .path {color:#202124;font-size:.88rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .result h3 {font-size:1.25rem;font-weight:400;margin:.25rem 0 .35rem;line-height:1.3}
      .result h3 a {color:#1a0dab;text-decoration:none}.result h3 a:hover{text-decoration:underline}
      .result .snippet {color:#4d5156;font-size:.92rem;line-height:1.55}
      .result .extra {color:#70757a;font-size:.8rem;margin-top:.25rem}
      .image-heading {font:500 1.05rem Arial,sans-serif;color:#202124;margin:.2rem 0 .8rem}
      .image-caption {font:400 .82rem/1.35 Arial,sans-serif;margin:.3rem 0 1rem;
                      display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
      .image-caption a {color:#1a0dab;text-decoration:none}.image-caption a:hover{text-decoration:underline}
      mark {background:#fff2a8;padding:0}
      .empty {padding:2rem 0;color:#4d5156}
      footer {visibility:hidden}
    </style>
    """,
    unsafe_allow_html=True,
)


def _safe(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


@st.cache_resource(show_spinner=False)
def get_service(index_mtime: float) -> SearchService:
    del index_mtime
    return SearchService(INDEX_DIR)


def _index_mtime(index_dir: Path) -> float:
    return max((item.stat().st_mtime_ns for item in index_dir.glob("*.toc")), default=0)


@st.cache_resource(show_spinner=False)
def get_image_service(index_mtime: float) -> ImageSearchService:
    del index_mtime
    return ImageSearchService(IMAGE_INDEX_DIR)


stats = index_stats(INDEX_DIR)
st.markdown(
    '<div class="brand"><span>V</span><span>n</span><span>S</span><span>e</span><span>a</span><span>rch</span></div>',
    unsafe_allow_html=True,
)

if not stats["ready"]:
    if DATASET.exists() and DATASET.stat().st_size:
        with st.spinner("Đang tạo chỉ mục lần đầu…"):
            build_index(DATASET, INDEX_DIR)
        st.cache_resource.clear()
        st.rerun()
    st.warning("Chưa có dữ liệu tìm kiếm.")
    st.code("python scripts/crawl.py\npython scripts/build_index.py\nstreamlit run main.py", language="bash")
    st.stop()

query_from_url = str(st.query_params.get("q", "")).strip()
if st.session_state.get("_last_url_query") != query_from_url:
    # Initialize from a shared URL, or respond to browser back/forward navigation.
    st.session_state["search_draft"] = query_from_url
    st.session_state["active_query"] = query_from_url
    st.session_state["_last_url_query"] = query_from_url

def submit_search() -> None:
    st.session_state["active_query"] = st.session_state["search_draft"].strip()
    st.session_state["_last_url_query"] = st.session_state["active_query"]
    st.query_params["q"] = st.session_state["active_query"]
    st.query_params["page"] = "1"


left, right = st.columns([8, 1])
with left:
    st.text_input(
        "Từ khóa",
        key="search_draft",
        on_change=submit_search,
        label_visibility="collapsed",
        placeholder="Tìm trong các bài viết VnExpress…",
    )
with right:
    st.button("Tìm kiếm", type="primary", use_container_width=True, on_click=submit_search)

query = st.session_state["active_query"]
try:
    current_page = max(1, int(st.query_params.get("page", "1")))
except (TypeError, ValueError):
    current_page = 1

sort_label = st.radio(
    "Sắp xếp",
    ("Liên quan nhất", "Nhiều bình luận"),
    horizontal=True,
    label_visibility="collapsed",
)
service = get_service(_index_mtime(INDEX_DIR))
try:
    result_page = service.search(
        query,
        page=current_page,
        page_size=10,
        sort_by="comments" if sort_label == "Nhiều bình luận" else "relevance",
    )
except Exception as exc:
    st.error(f"Không thể xử lý truy vấn: {exc}")
    st.stop()

st.markdown(
    f'<div class="search-meta">Khoảng {_safe(result_page.total)} kết quả '
    f'({_safe(f"{result_page.elapsed_ms / 1000:.3f}")} giây)</div>',
    unsafe_allow_html=True,
)

if not result_page.results:
    st.markdown(
        '<div class="empty">Không tìm thấy kết quả phù hợp. Hãy thử từ khóa ngắn hoặc bỏ dấu.</div>',
        unsafe_allow_html=True,
    )

if query:
    st.markdown('<div class="image-heading">Hình ảnh liên quan</div>', unsafe_allow_html=True)
    if not image_index_stats(IMAGE_INDEX_DIR)["ready"]:
        st.caption("Chưa có chỉ mục ảnh. Hãy chạy scripts/backfill_images.py và scripts/build_image_index.py.")
    else:
        try:
            image_page = get_image_service(_index_mtime(IMAGE_INDEX_DIR)).search(query)
            if image_page.results:
                image_columns = st.columns(3)
                for position, related in enumerate(image_page.results):
                    with image_columns[position % 3]:
                        try:
                            st.image(related.image_url, use_container_width=True)
                        except Exception:
                            st.caption("Không tải được ảnh.")
                        st.markdown(
                            f'<div class="image-caption"><a href="{_safe(related.source_url)}" '
                            f'target="_blank" rel="noopener noreferrer">{_safe(related.description)}</a></div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("Không tìm thấy ảnh có mô tả phù hợp.")
        except Exception as exc:
            st.caption(f"Không thể tìm ảnh: {exc}")

for item in result_page.results:
    host = urlparse(item.url).netloc.removeprefix("www.")
    path = urlparse(item.url).path.strip("/").replace("-", " › ")[:90]
    date = item.published_at[:10] if item.published_at else ""
    extras = " · ".join(
        value for value in (date, item.category, f"{item.comment_count} bình luận") if value
    )
    st.markdown(
        f"""
        <div class="result">
          <div class="path">{_safe(host)} › {_safe(path)}</div>
          <h3><a href="{_safe(item.url)}" target="_blank" rel="noopener noreferrer">{_safe(item.title)}</a></h3>
          <div class="snippet">{item.snippet}</div>
          <div class="extra">{_safe(extras)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

if result_page.pages > 1:
    previous, label, following = st.columns([1, 4, 1])
    with previous:
        if st.button("← Trước", disabled=current_page <= 1, use_container_width=True):
            st.query_params["page"] = str(current_page - 1)
            st.rerun()
    with label:
        st.markdown(
            f"<div style='text-align:center;padding:.55rem;color:#70757a'>Trang {current_page}/{result_page.pages}</div>",
            unsafe_allow_html=True,
        )
    with following:
        if st.button("Sau →", disabled=current_page >= result_page.pages, use_container_width=True):
            st.query_params["page"] = str(current_page + 1)
            st.rerun()

with st.sidebar:
    st.subheader("VnSearch MVP")
    st.metric("Tài liệu đã index", stats["documents"])
    st.caption("Xếp hạng mặc định bằng BM25F. Chỉ mục Whoosh được lưu bền vững trong thư mục index/.")
