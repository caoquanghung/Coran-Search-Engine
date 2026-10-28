# Plan: search images using their own descriptions

## Objective and scope

Replace query-time image collection from highly ranked articles with a persistent, image-level text search. Each eligible image in the crawled article dataset should have its URL and associated text stored before a user searches. Rank images by how well that text matches the query.

Keep Python, Whoosh, BM25F, Streamlit, Vietnamese accent handling, and the existing article search. This remains text-based retrieval: better image descriptions should improve relevance, but BM25F does not understand visual content or automatically match synonyms. Image recognition, generated captions, embeddings, and external image-search APIs are outside this implementation.

For the initial dataset, “all images” means all eligible editorial images from up to 1,000 valid unique article candidates, not just images in the first six search results. Retain candidates regardless of comment count. After bootstrap, the crawling loop adds newly discovered articles and their images, so the live corpus may grow beyond 1,000 articles. Logos, ads, tracking pixels, navigation images, and related-story thumbnails are excluded.

## Current behavior and causes of poor relevance

- `main.py` passes URLs from the first six results on the current article-results page to `get_related_images()`. Images therefore depend on article ranking, pagination, and article sorting. Image search does not run when article search returns no results.
- `crawler/image_crawler.py` already extracts image alt text and figure captions. However, its query coverage score includes the article title for every image, so an unrelated image can match because of its host article's title.
- `LazyImageCrawler` defaults to at most two images per article and six images overall. Relevant images outside that candidate pool are unavailable.
- The lazy crawler fetches article pages during search, and Streamlit caches its output for an hour. There is no persistent image-description dataset or image index.
- `crawler/parser.py` saves one representative `image_url` per article. It removes `figure figcaption` nodes while extracting article content, so image extraction must happen before this destructive cleanup, or use an independent parse of the original HTML.
- `engine/schema.py` stores the article's representative image URL without searchable image-specific fields. `engine/searcher.py` retrieves article documents only.

## Proposed data flow

```text
Discover and fetch candidate articles
  -> extract article fields and all editorial image contexts from the same HTML
  -> retain up to 1,000 valid unique article candidates
  -> persist documents.jsonl and images.jsonl for that corpus
  -> build the existing article index and a separate image_index/

Every 15 minutes
  -> revisit configured newspaper listing/feed pages to discover article URLs
  -> skip previously crawled articles using persistent crawl state
  -> fetch new articles and extract their image contexts
  -> persist new records and incrementally index only those records
  -> publish updated index generations and checkpoint completed work

User query
  -> existing article search -> article list
  -> image text search across image_index/ -> deduplicated image grid
```

No article-page requests should occur while retrieving image search results. Browsers will still request the image assets when displaying thumbnails.

## 1. Define an image record and extraction contract

Add a query-independent image record, for example `ArticleImage`, separate from the current scored `ResultImage`. Preserve text provenance rather than combining the article title into a generic caption.

| Field | Purpose |
| --- | --- |
| `image_id` | Stable hash of `source_doc_id` and conservatively normalized image URL; unique index key. |
| `image_url` | Resolved, usable image asset URL for display. |
| `canonical_image_url` | Conservative identity URL for duplicate grouping; retain the usable URL separately. |
| `source_doc_id`, `source_url`, `source_title` | Link back to the article and show attribution. |
| `alt_text` | Description from the image's `alt` attribute. |
| `caption` | Visible caption associated with the image or its figure. |
| `image_title` | Optional image-element `title` attribute. |
| `nearby_text` | Bounded local paragraph context, with its origin recorded. |
| `category`, `published_at`, `crawled_at` | Source metadata and refresh information. |
| `position`, `width`, `height` | Stable ordering and dimensions, when available. |
| `context_source`, `searchable` | Describe available evidence and whether enough image context exists for retrieval. |
| `record_version` | Data-format version for migration checks. |

Extraction rules:

1. Extract from the article body before parser cleanup. Prefer reusing the parsed DOM; do not fetch a page twice just to collect its images.
2. Support current lazy attributes (`data-src`, `data-original`, `data-lazy-src`) and normal `src`, plus `<picture>/<source>` and `srcset` variants. Parse width/density descriptors rather than assuming the last candidate is best. Resolve relative and protocol-relative URLs; reject empty, placeholder, `data:`, and unsupported URLs.
3. Associate an image with its own figure caption and image attributes. For multiple images in one figure, mark a shared caption as figure-level evidence. Include existing VnExpress caption containers when supported by HTML fixtures.
4. Use at most the nearest preceding and following article paragraphs as local context, capped initially at 500 characters total. Do not cross into another figure or unrelated content block. Deduplicate caption text and avoid attaching the whole article body or description to every image.
5. Ignore noneditorial containers and known placeholders. Use explicit tiny dimensions as an additional exclusion signal; missing dimensions alone must not reject an image. Do not use a blanket file-extension filter that could discard real editorial images.
6. Merge repeated appearances of the same image within an article, retaining the richest caption/alt/context and earliest position. In particular, an `og:image` entry must not suppress the richer body-image record when URLs match. A metadata-only image with no local descriptive text is stored as nonsearchable; article-title fallback is for attribution only.
7. Normalize whitespace and Unicode consistently. Keep original Vietnamese text for display. If no usable alt text, caption, image title, or local context exists, preserve the URL but mark the record nonsearchable rather than inventing a description.
8. Deduplicate using URLs conservatively. Preserve query parameters by default, since they may select or authorize a different asset. Only collapse verified CDN size variants using fixture-backed rules. Different URLs with identical pixels will remain separate unless a later asset-hashing feature is added.

## 2. Persist the image corpus during crawling

Update `crawler/parser.py`, `crawler/crawler.py`, and `scripts/crawl.py`:

- Add an `images` collection to `Article`, with an empty default for compatibility. Extract it during normal article parsing using the query-independent extractor in `crawler/image_crawler.py`.
- Carry image records for every retained article candidate, then add new articles and images during scheduled crawling. Export `data/images.jsonl`, one record per source/article-image association, for articles in the corpus. Store the nested collection in `documents.jsonl` as the source of truth so the image export can be regenerated without recrawling.
- Preserve the existing article `image_url` field for compatibility. Do not impose the old two-images-per-article search limit on extraction or persistence.
- Prepare and validate both outputs before publishing them. Record a shared crawl generation and counts in a manifest; index builds must reject mismatched generations. Retain the last valid generation if export fails.
- Log counts for fetched/retained articles, extracted and searchable images, missing descriptions, excluded assets, and duplicates. Retain request retries, timeouts, crawl delay, and existing crawl limits.

### Crawling loop: discover new content every 15 minutes

**Requirement:** The crawler revisits configured newspaper websites every 15 minutes to check for new content. It only crawls and indexes new content, skipping content that has already been crawled.

- Add a background watch mode to `scripts/crawl.py` with a default interval of **900 seconds**. Run it independently of Streamlit. Start a discovery pass immediately on launch, then every 15 minutes; use a process lock to prevent overlapping passes or duplicate watcher instances. If a pass overruns its interval, resume at the next available scheduled slot without overlapping work.
- Revisit configured listing pages or feeds to discover new article links. Initially use the existing VnExpress seeds and parser; additional newspapers require source-specific discovery and extraction support. Listing requests are necessary discovery work, while already processed article pages must be skipped before fetching.
- Store durable crawl state, for example in `data/crawl_state.sqlite`, keyed by normalized source URL with canonical URL and article-ID aliases. Seed it from the existing dataset during migration. Use the existing URL-cleaning rules only where valid for the source, and preserve parameters that identify distinct articles. Resolve canonical aliases after the first fetch and avoid duplicate storage/indexing.
- Track discovery, fetch/extraction, pending indexing, completion, attempt count, and retry time separately. Persist successfully extracted records before indexing. If indexing fails, retry from those saved records without fetching the article again; stable article/image IDs make index writes idempotent. Mark indexing complete only after both applicable article and image index updates succeed. Recover pending work after a restart.
- Retry transient fetch failures with backoff; do not mark them successfully crawled. Record invalid/nonarticle URLs separately so they are not repeatedly retried as new articles. Previously completed articles are neither fetched nor reindexed during the normal loop, even if their text, comments, or images later change. Explicit migration, repair, or recrawl commands remain separate operations.
- Append newly accepted article/image records to the live corpus and update only their index documents. Do not rebuild the full corpus on every pass. A pass with no new content leaves datasets, indexes, and index generations unchanged.
- Log each pass's start/end time, discovered URLs, previously seen URLs skipped, newly crawled articles/images, indexing successes, and failures. Checkpoints must survive shutdown; respect per-source request delays and bounded retries.

## 3. Build a separate persistent Whoosh image index

Add `engine/image_schema.py` and `engine/image_indexer.py`, plus `scripts/build_image_index.py`.

- Store one searchable document per source/article-image association in `image_index/`. Store the identity and attribution fields; index caption, alt text, image title, and local context separately.
- Reuse `VI_ANALYZER` and `fold_vietnamese`. Provide a folded counterpart for each searchable field so accent-insensitive retrieval preserves field weighting. Keep original text stored for display and snippets.
- Store the article title for display only in the initial version. Do not index the full article body, article title, comment count, filename, or URL as image relevance evidence.
- Start with relative boosts of caption **4**, alt text **3**, image title **2**, and nearby text **1**. Configure boosts in one place only, avoiding accidental multiplication between schema boosts and query-parser boosts. These are tuning starting points, not validated optimal values.
- Build into a temporary directory, validate counts and schema/data versions, then publish the completed index. Keep the previous valid index recoverable if publication fails. Do not rebuild on Streamlit reruns.
- Use a full build for bootstrap, schema migrations, and explicit repair. Scheduled passes must update the article and image indexes only with newly persisted records, using stable IDs to prevent duplicates on retry. Commit and publish new generations only after successful updates; reopen cached searchers when generations change. An explicit source refresh must replace its records and remove stale images, while normal scheduled passes leave existing sources untouched.
- Publish an index generation identifier for cache invalidation. Keep article and image index paths and readiness checks independent.

## 4. Retrieve and rank images independently

Add `engine/image_searcher.py` with `ImageSearchService.search(query, page=1, page_size=6, category="")` and typed result/page objects.

1. Query all searchable image records using BM25F over image-specific text fields. Combine original and folded field queries with disjunction-max behavior or an equivalent scheme that avoids counting the same evidence twice. Preserve a preference for exact accented matches when otherwise tied, while retaining unaccented recall.
2. Prefer coverage of more query terms and phrase matches, then tune field weights against judged examples. A record must match its image-specific text to become a candidate. Do not admit a result solely because its article matched, and do not fill empty result slots with unrelated images.
3. Generate display descriptions/snippets from matching caption, alt text, image title, or local context. Keep the source article title as attribution. Escape all displayed text using the existing UI safety pattern.
4. Group matches by canonical image identity across sources, retaining the highest-scoring source association and its own matched description. Apply duplicate grouping before final pagination so totals and page sizes represent distinct images. Use a stable image-ID tie-breaker for reproducible ordering.
5. Return an empty result page for an empty query or no matching descriptions. Category filtering can restrict the image corpus; article comment sorting and article pagination must not change image ranking.

For the small initial corpus, retrieving all matches before deduplication is acceptable. Measure latency before adding candidate limits that could reduce recall.

## 5. Connect the image index to Streamlit

Update `main.py` and relevant package exports:

- Replace `get_related_images(query, article_urls)` with the cached image search service. Run image retrieval for every nonempty query, including queries with zero article hits.
- Keep the existing image grid as the first UI iteration. Populate it from global image results with a matched description and source link. If pagination is exposed, give it state separate from article pagination.
- Key service and result caches by the image index generation, query, filters, and image pagination. Invalidate cached results when a new image index is published.
- Show a clear image-specific empty/unavailable state when descriptions do not match or the image index has not been built. Keep article search usable. Do not silently fall back to lazy article-image retrieval.
- Remove the old query-time crawler call after validation. Handle unavailable image assets without failing the article-results page; document that remote images can change after crawling.

## 6. Migrate the existing dataset and package

The existing JSONL contains representative image URLs but not the complete image collection or its captions. Rebuilding an index from those URLs alone cannot recover the missing descriptions.

1. Add a backfill command, `scripts/backfill_images.py`, that refetches the URLs already in `data/documents.jsonl`, extracts image context, and writes a new versioned dataset/export. Preserve article IDs and corpus membership during this migration.
2. Record failures explicitly and support retrying failed sources. Without a previous image record, a failed source remains a documented coverage gap rather than a successful empty extraction. Keep previous records on failed refreshes; replace a source's records only after a successful extraction, including a successful zero-image result.
3. Build and validate the image index, then switch the UI to it. Keep the article index usable throughout. A normal future crawl should produce image records directly and no longer need backfill.
4. Update README setup, project structure, crawl/index instructions, corpus scope, text-retrieval limitations, and migration guidance.
5. The repository also contains a `24125010/` submission copy and `24125010.zip`. Implement in the root source first; synchronize and regenerate the submission artifacts only during the packaging stage, then smoke-test the packaged application.
6. Seed persistent crawl state from the migrated corpus, then start the 15-minute watcher. Document how to start/stop the watcher and recover pending indexing work.

Planned commands to add and document (these do not exist yet):

```bash
# Upgrade the existing corpus without changing its selected article list.
python scripts/backfill_images.py --input data/documents.jsonl --output data/images.jsonl
python scripts/build_image_index.py --input data/images.jsonl --index image_index

# Future normal crawl: write articles, nested image records, image export, and manifest.
python scripts/crawl.py --limit 1000 --pages 5 --candidates 1500
python scripts/build_index.py
python scripts/build_image_index.py --input data/images.jsonl --index image_index

# Continuous discovery: crawl and incrementally index new articles/images only.
python scripts/crawl.py --watch --interval 900 --state data/crawl_state.sqlite
```

The backfill command must also update the nested image records and generation manifest, using staged writes, even though `--output` names the flattened image export.

## 7. Validate correctness and relevance

Use offline HTML fixtures and temporary indexes for automated tests; no live network is required for the test suite.

| Area | Required checks |
| --- | --- |
| Extraction | Multiple images; caption/alt pairing; shared figures; bounded nearby paragraphs; lazy URLs; picture/srcset; relative URLs; placeholders; missing descriptions. |
| Data integrity | Captions survive article parsing; `og:image` merges with richer body metadata; stable IDs; conservative URL identity; all eligible images from retained sources are exported. |
| Ranking | A specific matching caption outranks weak local context; a matching article title alone produces no image hit; a relevant image outside the top article results is found; an image can match when no article document matches. |
| Vietnamese | Accented/unaccented queries retrieve expected images; folded-field boosts remain consistent; exact accented evidence can win a tie over an ambiguous folded match. |
| Search behavior | Empty/no-match queries; global URL deduplication before pagination; stable ordering; article sorting/pagination does not affect image results. |
| Persistence | Restart reuses the index; migration from old JSONL; failed fetch/rebuild preserves valid data; successful refresh removes stale records; generation changes invalidate caches. |
| Crawling loop | With a fake clock and mocked HTTP, verify 900-second scheduling, no overlapping passes, known URLs skipped before article fetch, persistent deduplication after restart, new records indexed once, empty passes causing no writes, fetch retries, and recovery of saved records after partial index failure without recrawling. |
| UI/regression | Image retrieval makes no article HTTP requests; missing image index and broken assets are handled; existing article search tests pass. |

Before replacing the current path, freeze a representative corpus and record the current lazy crawler's results. Judge a set of about 20 Vietnamese queries, including accented/unaccented pairs, multiword descriptions, ambiguous terms, and deliberate no-match cases. Use saved HTML for reproducible baseline extraction. Label each displayed image as relevant or irrelevant to the query using its description and visual inspection.

Compare Precision@6 (relevant results divided by six slots), per-query result coverage, duplicate count, and local search latency. Report unfilled slots separately; do not claim improved precision just from showing fewer images. Set a proposed release target of at least a 15 percentage-point improvement in mean Precision@6 on this fixed set, no regression on the title-only false-positive fixtures, and no duplicate displayed URLs. Measure the baseline first and report actual results; this target is not a promised outcome. Report warm local retrieval p50/p95 separately from remote image rendering time.

## Implementation order and completion criteria

1. **Extraction and dataset:** introduce the image model, preserve captions, crawl all editorial image contexts, and persist consistent versioned outputs.
2. **Index and retrieval:** implement the separate schema, full rebuild, image search service, accent handling, and duplicate grouping; validate offline ranking cases.
3. **Migration, scheduled crawling, and UI:** backfill the existing corpus, expand it to 1,000 candidates, seed crawl state, build its image index, add the 15-minute discovery loop and incremental indexing, replace lazy UI retrieval, and verify restart recovery, cache invalidation, and article-search independence.
4. **Evaluation and delivery:** run existing and new tests, assess the fixed relevance set, tune based on evidence, update README, and refresh submission artifacts.

The improvement is complete when a query retrieves images from their own stored descriptions across the full corpus, independently of which articles are displayed; all eligible image URLs are preserved with context provenance; the image index and crawl state persist across restarts; a background pass checks for new content every 15 minutes and crawls/indexes only new records; and correctness, relevance evaluation, migration, and packaged-app checks have been documented.
