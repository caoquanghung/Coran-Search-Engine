# VnSearch — Article and Image Search

**Student:** Cao Quang Hung<br>
**Student ID:** 24125010

VnSearch is a Vietnamese article and image-description search engine built with Whoosh, NumPy, multilingual E5, and Streamlit. It combines fast keyword matching with semantic retrieval over a real 1,000-article corpus and presents the results in a familiar Google-inspired interface.

## Why This Project Is Interesting

- **Searches what an image means, not only where it appears.** The crawler saves each image URL together with its caption, alt text, image title, and nearby article text. Image queries are ranked against that description.
- **Hybrid retrieval catches both exact and conceptual matches.** BM25F rewards important query words in titles and descriptions, while multilingual E5 can retrieve related Vietnamese passages even when they do not repeat the same words. Reciprocal Rank Fusion combines both rankings without requiring their scores to use the same scale.
- **Vietnamese-friendly matching.** Keyword search accepts queries with or without diacritics, while the semantic branch preserves the original Vietnamese text for meaning-aware embeddings.
- **One crawl powers two search experiences.** The same corpus supports article results, highlighted snippets, a four-image preview, and an independent image gallery.
- **Incremental by design.** A durable watcher checks newspaper listing pages every 15 minutes, skips URLs already processed, and indexes only new or changed content.
- **Responsive, stateful UI.** The search term, result type, sort order, and page survive Streamlit reruns and are reflected in the URL, so a result view can be bookmarked or shared.
- **Fast after warm-up.** The encoder is prepared in the background; query embeddings and complete candidate rankings are cached; pagination and sorting reuse previous work.

## Submission Package (Under 20 MB)

The submitted ZIP intentionally contains the complete **1,000-article dataset**, associated image descriptions, source code, tests, and documentation, but excludes reproducible generated artifacts:

- `models/` — downloaded multilingual E5 weights (about 466 MiB)
- `index/` and `image_index/` — generated Whoosh indexes
- `vector_index/` — generated semantic embeddings
- Python and pytest caches

This keeps the compressed submission safely below the 20 MB limit without reducing the dataset. Follow the quick-start commands below to regenerate the indexes. The semantic model is downloaded only when hybrid search is enabled.

## Main Features

- Crawls VnExpress articles from multiple categories and pages.
- Stores and indexes up to 1,000 valid article candidates, regardless of comment count.
- Indexes article titles, descriptions, and content with Whoosh.
- Combines BM25F keyword ranking and multilingual E5 semantic retrieval using Reciprocal Rank Fusion (RRF).
- Stores normalized 384-dimensional embeddings in persistent exact cosine vector indexes.
- Supports Vietnamese queries with or without diacritics.
- Displays the URL, title, highlighted snippet, publication date, category, and comment count for each result.
- Supports pagination and sorting by relevance or comment count.
- Extracts every eligible editorial image with its alt text, caption, and nearby text during article crawling.
- Searches a persistent image-description index independently of the article results.
- Can check the VnExpress seed pages every 15 minutes and index only newly discovered articles and images.
- Stores the Whoosh index on disk so the dataset is not re-indexed after every Streamlit interaction.

## Requirements

- Python 3.10 or newer
- The Python packages listed in `requirements.txt`

## Quick Start

Open a terminal in the `24125010` folder and run:

```bash
python -m venv .venv

# macOS or Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Build the lightweight keyword indexes from the included dataset
python scripts/build_index.py
python scripts/build_image_index.py

# Start the application
streamlit run main.py
```

This immediately provides article and image-description search in keyword mode. Streamlit normally opens `http://localhost:8501`.

## Enable Hybrid Semantic Search

To add meaning-aware vector retrieval, download the pinned multilingual E5 model and build its indexes once:

```bash
python scripts/build_vector_index.py --download-model
```

This downloads `intfloat/multilingual-e5-small` and saves a pinned copy in `models/multilingual-e5-small/`. The model files occupy approximately 466 MiB. Subsequent indexing and searches use the local files and work without another download. Restart the application after the build:

```bash
streamlit run main.py
```

Type a query and press Enter or click **Tìm kiếm**. The search text stays in the box when you change sorting or move between result pages.
The centered homepage offers quick topic searches. Results use a compact search header, source breadcrumbs, blue linked titles, and a four-image preview. Switch between **Tất cả** and **Hình ảnh** to browse articles or a full image grid. The clear button returns to the homepage; numbered pagination and sorting preserve the current query. The layout adapts to narrower screens.
The app prepares the embedding model in a background thread while the page opens. A search submitted before preparation finishes can still wait for that first initialization. Later queries reuse the model and cached results.

## Persistent Indexing

The application reuses the article keyword index in `index/`, image keyword index in `image_index/`, and semantic indexes in `vector_index/`. Streamlit caches services by both keyword and vector generations, so updates become visible on the next rerun. The model is shared across article and image queries. Query embeddings and complete ranked candidate lists are cached; sorting and pagination reuse those candidates. A new index generation creates fresh service caches.

The index is created only when no valid index exists and `data/documents.jsonl` is available. Therefore, entering a query, changing the sort option, or moving between result pages does not rebuild the dataset index.

To rebuild the index manually, run:

```bash
python scripts/build_index.py
python scripts/build_image_index.py
python scripts/build_vector_index.py
```

Vector builds reuse embeddings for unchanged text. They encode new or changed records, remove stale records, and publish a completed generation only after a successful build. Model revision and corpus fingerprints prevent mixing incompatible indexes. If the semantic index/model is missing or the corpus has changed, the UI explicitly reports keyword-only search until the vector index is rebuilt.

## Hybrid Search

Article text is split into overlapping passages of at most 384 tokenizer tokens, including a short title/description prefix. Image vectors contain deduplicated caption, alt text, image title, and local context; the host article title is not added. E5 receives `passage: ` for records and `query: ` for queries. Vietnamese diacritics are preserved for embeddings.

NumPy performs an exact cosine scan over normalized vectors stored in `.npy` files. This has the same exhaustive search behavior as a flat inner-product index and avoids a conflicting OpenMP runtime between FAISS and PyTorch on macOS. Article passages are grouped by article using the best passage score. BM25F and semantic retrieval each provide up to 50 candidates, and RRF combines their ranks with `k=60`. Semantic results are admitted even when no query words occur in their descriptions. Image assets are deduplicated before display.

For nonempty queries, the displayed total is the combined candidate pool, up to 100 articles or image associations before image deduplication. Comment sorting sorts that same article pool. An empty article query still browses the full corpus. Dense retrieval returns the nearest descriptions and can include weak matches; its similarity scores are not probabilities.

## Search Performance

Inference uses the same E5 weights through Transformers with masked mean pooling and normalization. Model initialization and the first inference are prepared in the background, with a shared loader to prevent duplicate models during concurrent searches. CPU inference defaults to two PyTorch threads to limit overhead on short queries. `VNSEARCH_CPU_THREADS` changes that limit; `VNSEARCH_DEVICE=cpu` forces CPU instead of an available GPU.

On the local CPU with the 1,000-article corpus, a sample benchmark measured approximately 5.4 seconds for cold model loading, 14–16 ms for prepared query embeddings, 0.23–0.46 seconds for complete new article/image queries, and under 1 ms for cached results. Sorting and pagination also reuse the cached ranking. These backend measurements exclude page rendering and downloading remote image assets; timings vary by machine and query.

Run the benchmark in a fresh process to measure startup separately:

```bash
python scripts/benchmark_search.py
python scripts/benchmark_search.py --query "nước dâng làm ngập đường phố" --repeat 10
```

Existing vector indexes remain compatible with the inference changes; rebuilding them is unnecessary.

The old dataset has one representative image URL per article and does not contain full captions. To populate image search for those articles, run:

```bash
python scripts/backfill_images.py --input data/documents.jsonl --output data/images.jsonl
python scripts/build_image_index.py --input data/images.jsonl --index image_index
```

Backfill requests each existing article page. Failed URLs are written to `data/image_backfill_failures.txt`; rerun the command when the source is reachable, then rebuild both image and vector indexes. Keyword matching uses Vietnamese accent folding; semantic retrieval matches descriptions through E5 embeddings. Image search still operates on associated text rather than image pixels.

## Optional: Crawling the Dataset Again

The included dataset is ready to use. To crawl a new dataset and rebuild the index:

```bash
python scripts/crawl.py --limit 1000 --pages 5 --candidates 1500
python scripts/build_index.py
python scripts/build_image_index.py
python scripts/build_vector_index.py
```

This creates a new corpus from the first 1,000 valid unique article candidates, along with `data/images.jsonl` and a corpus manifest. To expand an existing dataset without refetching its articles, run:

```bash
python scripts/crawl.py --expand --limit 1000 --pages 5 --candidates 1500
```

Expansion adds unseen articles until the corpus has 1,000 records, then rebuilds the keyword indexes and updates an existing vector index. To continue discovering new content after that, run the watcher as a separate process:

```bash
python scripts/crawl.py --watch --interval 900 --state data/crawl_state.sqlite
```

The watcher checks the configured listing pages immediately and every 15 minutes after that. It skips previously indexed article URLs, saves new article and image records, and updates keyword and existing vector indexes. Only changed text is embedded. Indexing is marked complete after semantic updates succeed, so failed work resumes from saved records without refetching the article. Stop it with Ctrl+C. For a single pass, use `python scripts/crawl.py --once`. The live dataset can grow beyond 1,000 articles; the watcher currently supports the configured VnExpress seeds.

Please use a reasonable crawl delay and follow the source website's terms and robots policy.

## Running the Tests

```bash
pytest -q tests
```

## Project Structure

```text
24125010/
├── main.py                  # Streamlit graphical interface
├── ui/                      # Shared result markup and responsive styles
├── requirements.txt         # Required Python libraries
├── README.md                # Setup and usage instructions
├── crawler/
│   ├── crawler.py           # Link discovery and article crawling
│   ├── parser.py            # Article content extraction
│   ├── image_records.py     # Image URLs and description extraction
│   ├── corpus.py            # Article/image dataset exports
│   └── watch.py             # Persistent 15-minute crawl loop
├── engine/
│   ├── schema.py            # Whoosh schema and Vietnamese normalization
│   ├── indexer.py           # Persistent index construction
│   ├── searcher.py          # Article retrieval and snippets
│   ├── image_schema.py      # Image text schema
│   ├── image_indexer.py     # Image index build and updates
│   ├── image_searcher.py    # Image keyword retrieval
│   ├── vector_index.py     # E5 embeddings and exact cosine indexes
│   └── hybrid_searcher.py   # Independent branches and RRF fusion
├── scripts/
│   ├── crawl.py             # Dataset crawling command
│   ├── backfill_images.py   # Upgrade existing article dataset
│   ├── build_index.py       # Article index command
│   ├── build_image_index.py # Image index command
│   ├── benchmark_search.py  # Startup/new-query/cached latency measurements
│   └── build_vector_index.py # Offline semantic index command
├── data/
│   ├── documents.jsonl      # Crawled article dataset
│   ├── images.jsonl         # Image URLs with associated text
│   ├── crawl_state.sqlite   # Watcher state
│   └── seeds.txt            # Initial category URLs
├── index/                   # Prebuilt persistent Whoosh index
├── image_index/             # Persistent image-description index
├── vector_index/            # Versioned article/image cosine indexes
├── models/                  # Local pinned multilingual E5 model
└── tests/                   # Automated tests
```
