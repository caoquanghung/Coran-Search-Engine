```
<MSSV>/
│
├── main.py                   # Streamlit entry point
│
├── crawler/
│   ├── __init__.py
│   ├── crawler.py            # Fetch website, follow links
│   └── parser.py             # Extract title, content, URL
│
├── engine/
│   ├── __init__.py
│   ├── indexer.py            # Build & persist Whoosh index
│   ├── searcher.py           # Query processing & retrieval
│   └── schema.py             # Whoosh document schema
│
├── data/
│   ├── seeds.txt             # Initial URLs to crawl
│   └── documents.jsonl       # Crawled dataset
│
├── index/                    # Whoosh persistent index
│
├── scripts/
│   ├── crawl.py              # Run crawler
│   └── build_index.py        # Run indexing
│
├── requirements.txt
├── README.md
└── .gitignore
```

