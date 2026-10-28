from pathlib import Path

import numpy as np
import pytest

from crawler.corpus import write_corpus
from engine import SearchService, build_index
from engine.hybrid_searcher import HybridImageSearchService, HybridSearchService, reciprocal_rank_fusion
from engine.image_indexer import build_image_index
from engine.vector_index import VectorIndex, build_vector_indexes


class ConceptEncoder:
    """Deterministic transport/sea embeddings; tests run offline without weights."""
    dimension = 3
    model_info = {"model_id": "test-concepts", "revision": "1", "dimension": 3}

    def __init__(self):
        self.encoded = []
        self.fail = False

    def encode(self, texts, *, query=False, progress=False):
        if self.fail:
            raise RuntimeError("Simulated encoder failure")
        self.encoded.extend(texts)
        vectors = []
        for text in texts:
            if "xe điện" in text or "phương tiện xanh" in text:
                vectors.append([1.0, 0.0, 0.0])
            elif "cá voi" in text:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return np.asarray(vectors, dtype=np.float32)

    def query_vector(self, query):
        return self.encode([query], query=True)


def corpus(tmp_path):
    docs = []
    for record_id, text, category in (("car", "xe điện chạy bằng pin", "Công nghệ"), ("whale", "cá voi bơi ngoài biển", "Đời sống")):
        image = {"image_id": record_id, "image_url": f"https://cdn.test/{record_id}.jpg", "source_doc_id": record_id,
                 "source_url": f"https://vnexpress.net/{record_id}", "caption": text, "searchable": True, "category": category}
        docs.append({"id": record_id, "url": image["source_url"], "title": text, "content": text,
                     "description": "", "images": [image], "category": category})
    paths = tmp_path / "documents.jsonl", tmp_path / "images.jsonl"
    write_corpus(docs, *paths)
    build_index(paths[0], tmp_path / "index")
    build_image_index(paths[1], tmp_path / "image_index")
    return docs, paths


def test_hybrid_finds_semantic_only_article_and_image(tmp_path: Path):
    _, paths = corpus(tmp_path)
    encoder = ConceptEncoder()
    build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    assert SearchService(tmp_path / "index").search("phương tiện xanh").total == 0
    service = HybridSearchService(tmp_path / "index", tmp_path / "vectors", encoder=encoder)
    page = service.search("phương tiện xanh", page_size=1)
    assert page.results[0].doc_id == "car"
    assert page.total == 2
    assert service.search("phương tiện xanh", page=2, page_size=1).results[0].doc_id == "whale"
    image_service = HybridImageSearchService(tmp_path / "image_index", tmp_path / "vectors", encoder=encoder)
    assert image_service.search("phương tiện xanh").results[0].image_id == "car"
    assert image_service.search("").total == 0
    assert service.search("").total == 2


def test_vector_filter_and_incremental_updates_remove_stale_records(tmp_path: Path):
    docs, paths = corpus(tmp_path)
    encoder = ConceptEncoder()
    build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    before = len(encoder.encoded)
    unchanged = build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    assert unchanged["new_embeddings"] == 0
    assert len(encoder.encoded) == before
    index = VectorIndex(tmp_path / "vectors", "articles", encoder=encoder)
    assert index.search("phương tiện xanh", category="Đời sống")[0][0] == "whale"
    docs[0]["content"] += " Một cập nhật mới."
    write_corpus(docs[:1], *paths)
    updated = build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    assert updated["new_embeddings"] == 1
    assert updated["documents"] == 1
    assert len(VectorIndex(tmp_path / "vectors", "articles", encoder=encoder).records) == 1


def test_failed_build_preserves_previous_generation(tmp_path: Path):
    docs, paths = corpus(tmp_path)
    encoder = ConceptEncoder()
    build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    original = (tmp_path / "vectors/manifest.json").read_bytes()
    docs[0]["content"] += " Nội dung mới."
    write_corpus(docs, *paths)
    encoder.fail = True
    with pytest.raises(RuntimeError):
        build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    assert (tmp_path / "vectors/manifest.json").read_bytes() == original


def test_rrf_uses_union_and_prefers_agreement():
    result = reciprocal_rank_fusion(["keyword", "both"], ["semantic", "both"])
    assert result[0][0] == "both"
    assert {record_id for record_id, _ in result} == {"keyword", "semantic", "both"}


def test_hybrid_images_deduplicate_before_pagination(tmp_path: Path):
    docs, paths = corpus(tmp_path)
    docs[1]["images"].append({**docs[0]["images"][0], "image_id": "duplicate"})
    write_corpus(docs, *paths)
    build_image_index(paths[1], tmp_path / "image_index")
    encoder = ConceptEncoder()
    build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    service = HybridImageSearchService(tmp_path / "image_index", tmp_path / "vectors", encoder=encoder)
    first = service.search("phương tiện xanh", page_size=1)
    second = service.search("phương tiện xanh", page=2, page_size=1)
    assert first.total == second.total == 2
    assert first.results[0].image_url != second.results[0].image_url


def test_model_revision_must_match_index(tmp_path: Path):
    _, paths = corpus(tmp_path)
    encoder = ConceptEncoder()
    build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    encoder.model_info = {**encoder.model_info, "revision": "different"}
    with pytest.raises(ValueError, match="revision"):
        VectorIndex(tmp_path / "vectors", "articles", encoder=encoder).search("phương tiện xanh")


def test_pagination_and_sorting_reuse_ranked_results(tmp_path: Path):
    _, paths = corpus(tmp_path)
    encoder = ConceptEncoder()
    build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    service = HybridSearchService(tmp_path / "index", tmp_path / "vectors", encoder=encoder)
    first = service.search("phương tiện xanh", page_size=1)
    encoded = len(encoder.encoded)
    service.search("phương tiện xanh", page=2, page_size=1)
    service.search("phương tiện xanh", sort_by="comments")
    assert len(encoder.encoded) == encoded
    assert service._ranked.cache_info().misses == 1
    assert service._ranked.cache_info().hits == 2
    assert first.results[0].doc_id == "car"
    images = HybridImageSearchService(tmp_path / "image_index", tmp_path / "vectors", encoder=encoder)
    images.search("phương tiện xanh", page_size=1)
    encoded = len(encoder.encoded)
    images.search("phương tiện xanh", page=2, page_size=1)
    assert len(encoder.encoded) == encoded
    assert images._ranked.cache_info().hits == 1


def test_background_preparation_shares_model_with_concurrent_search(tmp_path: Path, monkeypatch):
    import json
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from engine import vector_index

    (tmp_path / "model_info.json").write_text(json.dumps(ConceptEncoder.model_info))
    entered, release = threading.Event(), threading.Event()
    constructed = []

    class DelayedEncoder(ConceptEncoder):
        def __init__(self, model_dir):
            constructed.append(self)
            entered.set()
            assert release.wait(5)
            super().__init__()

    monkeypatch.setattr(vector_index, "EmbeddingEncoder", DelayedEncoder)
    preparation = vector_index.warmup_encoder(tmp_path)
    assert entered.wait(5)
    with ThreadPoolExecutor(max_workers=1) as executor:
        search = executor.submit(vector_index.get_encoder, tmp_path)
        release.set()
        assert search.result(timeout=5) is preparation.result(timeout=5)
    assert len(constructed) == 1
    assert constructed[0].encoded == ["khởi động tìm kiếm"]


def test_watch_recovers_semantic_update_before_marking_done(tmp_path: Path, monkeypatch):
    from crawler.watch import CrawlLoop

    _, paths = corpus(tmp_path)
    encoder = ConceptEncoder()
    build_vector_indexes(*paths, tmp_path / "vectors", encoder=encoder)
    monkeypatch.setattr("crawler.watch.build_vector_indexes",
                        lambda *args: build_vector_indexes(*args, encoder=encoder))

    class NewArticleCrawler:
        _clean_url = staticmethod(lambda url: url)
        fetches = 0

        def discover(self):
            return ["https://vnexpress.net/new-12345678.html"]

        def _get(self, url):
            self.fetches += 1
            return '<h1>Bài mới</h1><article><p>' + 'Nội dung mới đủ dài để được lưu lại trong tập dữ liệu tìm kiếm. ' * 3 + '</p></article>'

    crawler = NewArticleCrawler()
    loop = CrawlLoop(crawler, documents_path=paths[0], images_path=paths[1],
                     article_index=tmp_path / "index", image_index=tmp_path / "image_index",
                     state_path=tmp_path / "state.sqlite", vector_dir=tmp_path / "vectors")
    encoder.fail = True
    assert loop.run_once()["failed"] == 1
    assert loop.db.execute("SELECT status FROM articles WHERE url=?", (crawler.discover()[0],)).fetchone()[0] == "pending"
    encoder.fail = False
    loop.run_once()
    assert crawler.fetches == 1
    assert loop.db.execute("SELECT status FROM articles WHERE url=?", (crawler.discover()[0],)).fetchone()[0] == "done"
    assert len({row["record_id"] for row in VectorIndex(tmp_path / "vectors", "articles", encoder=encoder).records}) == 3
