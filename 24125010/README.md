# VnSearch — Article and Image Search

**Student:** Cao Quang Hung<br>
**Student ID:** 24125010

VnSearch is a Vietnamese text search engine built with Whoosh and Streamlit. It crawls VnExpress articles, creates a persistent inverted index, and presents matching documents in a Google-style interface.

## Main Features

- Crawls VnExpress articles from multiple categories and pages.
- Stores a dataset containing the 100 candidate articles with the highest comment counts.
- Indexes article titles, descriptions, and content with Whoosh.
- Uses BM25F ranking, with higher weights for titles and descriptions.
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

## Installation

Open a terminal in the `24125010` folder and run:

```bash
python -m venv .venv

# macOS or Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## Running the Application

The submitted package contains a crawled article dataset and persistent article index. Build the image corpus and index as described below, then start the graphical interface with:

```bash
streamlit run main.py
```

Streamlit will display a local URL, normally `http://localhost:8501`.

## Persistent Indexing

The application reuses the article index in `index/` and image index in `image_index/`. Streamlit caches each search service by its index generation, so updates become visible on the next rerun.

The index is created only when no valid index exists and `data/documents.jsonl` is available. Therefore, entering a query, changing the sort option, or moving between result pages does not rebuild the dataset index.

To rebuild the index manually, run:

```bash
python scripts/build_index.py
```

The old dataset has one representative image URL per article and does not contain full captions. To populate image search for those articles, run:

```bash
python scripts/backfill_images.py --input data/documents.jsonl --output data/images.jsonl
python scripts/build_image_index.py --input data/images.jsonl --index image_index
```

Backfill requests each existing article page. Failed URLs are written to `data/image_backfill_failures.txt`; rerun the command when the source is reachable. The image UI reports when no image index is available. Text matching uses Vietnamese accent folding and BM25F over image caption, alt text, image title, and local paragraph context. It does not inspect image pixels or automatically infer synonyms.

## Optional: Crawling the Dataset Again

The included dataset is ready to use. To crawl a new dataset and rebuild the index:

```bash
python scripts/crawl.py --limit 100 --pages 5 --candidates 500
python scripts/build_index.py
python scripts/build_image_index.py
```

The initial crawl selects the 100 articles with the highest comment counts from its candidates. It writes `data/documents.jsonl`, `data/images.jsonl`, and a corpus manifest. To continue discovering new content, run the watcher as a separate process:

```bash
python scripts/crawl.py --watch --interval 900 --state data/crawl_state.sqlite
```

The watcher checks the configured listing pages immediately and every 15 minutes after that. It skips previously indexed article URLs, saves new article and image records, and updates both indexes. Its SQLite state survives restarts; pending index work resumes without refetching the article. Stop it with Ctrl+C. For a single pass, use `python scripts/crawl.py --once`. The live dataset grows beyond the initial 100 articles; keep a copy of the initial dataset if a fixed-size submission is required. The watcher currently supports the configured VnExpress seeds.

Please use a reasonable crawl delay and follow the source website's terms and robots policy.

## Running the Tests

```bash
pytest -q tests
```

## Project Structure

```text
24125010/
├── main.py                  # Streamlit graphical interface
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
│   └── image_searcher.py    # Independent image retrieval
├── scripts/
│   ├── crawl.py             # Dataset crawling command
│   ├── backfill_images.py   # Upgrade existing article dataset
│   ├── build_index.py       # Article index command
│   └── build_image_index.py # Image index command
├── data/
│   ├── documents.jsonl      # Crawled article dataset
│   ├── images.jsonl         # Image URLs with associated text
│   ├── crawl_state.sqlite   # Watcher state
│   └── seeds.txt            # Initial category URLs
├── index/                   # Prebuilt persistent Whoosh index
├── image_index/             # Persistent image-description index
└── tests/                   # Automated tests
```
