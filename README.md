# VnSearch — Text Search Engine MVP

Ứng dụng thu thập các bài VnExpress, giữ tối đa 100 bài có số bình luận cao nhất trong tập ứng viên, lập chỉ mục đảo bằng Whoosh và tìm kiếm với BM25F. Giao diện Streamlit trình bày mỗi kết quả theo cấu trúc quen thuộc: đường dẫn, tiêu đề, đoạn trích và metadata.

## Chức năng

- Crawl theo nhiều chuyên mục, phân trang, retry khi lỗi tạm thời và delay giữa các request.
- Parse title, sapo, nội dung, URL canonical, chuyên mục, ngày đăng, ảnh và số bình luận.
- Lưu dataset dạng JSONL; chọn top 100 theo `comment_count`.
- Lưu Whoosh index trên đĩa, không re-index sau mỗi lần tìm kiếm.
- BM25F với trọng số tiêu đề > mô tả > nội dung; so khớp Unicode không dấu.
- Snippet dùng sliding window và Maximum Query Coverage để ưu tiên đoạn phủ nhiều query term nhất.
- Phân trang, sắp xếp theo độ liên quan hoặc số bình luận, highlight không phân biệt dấu.

## Cài đặt và chạy

Yêu cầu Python 3.10 trở lên.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Thu thập tối đa 500 ứng viên, giữ 100 bài nhiều bình luận nhất
python scripts/crawl.py --limit 100 --pages 5 --candidates 500

# Xây index persistent
python scripts/build_index.py

# Mở giao diện
streamlit run main.py
```

Giao diện cũng tự xây index lần đầu nếu `data/documents.jsonl` đã tồn tại nhưng `index/` chưa có index hợp lệ.

## Lệnh hữu ích

```bash
# Crawl nhanh để demo
python scripts/crawl.py --limit 20 --pages 1 --candidates 40 --delay 0.5

# Cập nhật/upsert vào index đang có
python scripts/build_index.py --update

# Chạy test
pytest -q
```

## Dữ liệu và lưu ý

Các URL seed nằm trong `data/seeds.txt`. "Top 100" được tính trong toàn bộ tập URL ứng viên tìm thấy ở các trang seed đã cấu hình; tăng `--pages` và `--candidates` để có độ phủ lớn hơn. Cấu trúc HTML của trang nguồn có thể thay đổi, vì vậy parser dùng CSS selector, JSON-LD và metadata làm các lớp fallback.

Hãy giữ `--delay` ở mức hợp lý, không chạy nhiều crawler đồng thời, và tuân thủ điều khoản/robots policy của website nguồn. Dataset và index là sản phẩm sinh ra nên được `.gitignore` bỏ qua.

## Cấu trúc

```text
main.py                 Streamlit UI
crawler/                link discovery + article parser
engine/                 schema + persistent index + BM25F search
scripts/crawl.py        crawl CLI
scripts/build_index.py  indexing CLI
data/seeds.txt          seed URLs
tests/                  parser/search tests
```
