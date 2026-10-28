"""Versioned exact cosine indexes for article passages and image descriptions."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_ID = "intfloat/multilingual-e5-small"
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "multilingual-e5-small"
FORMAT_VERSION = 2
_ENCODER_LOCK = threading.RLock()
_WARMUP_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vnsearch-warmup")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingEncoder:
    """One offline encoder shared by article, image, and cached query embeddings."""

    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.model_dir = model_dir
        info = model_dir / "model_info.json"
        if not info.exists():
            raise FileNotFoundError("Embedding model missing. Run python scripts/build_vector_index.py --download-model")
        self.model_info = json.loads(info.read_text(encoding="utf-8"))
        device = os.environ.get("VNSEARCH_DEVICE", "auto")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        if device == "cpu":
            torch.set_num_threads(max(1, int(os.environ.get("VNSEARCH_CPU_THREADS", "2"))))
        self._torch = torch
        self._inference_lock = threading.Lock()
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        self.model = AutoModel.from_pretrained(str(model_dir), local_files_only=True).to(device).eval()
        self.dimension = int(self.model.config.hidden_size)
        if self.dimension != self.model_info["dimension"]:
            raise ValueError("Encoder dimension differs from model metadata")

    def encode(self, texts: list[str], *, query: bool = False, progress: bool = False) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        prefix = "query: " if query else "passage: "
        batches = range(0, len(texts), 24)
        if progress:
            from tqdm import tqdm
            batches = tqdm(batches, desc="Embedding batches")
        vectors = []
        # E5's original masked mean pooling and normalization, without importing
        # the SentenceTransformers training/evaluation stack during a query.
        with self._inference_lock, self._torch.inference_mode():
            for start in batches:
                batch = self.tokenizer([prefix + text for text in texts[start:start + 24]],
                                       padding=True, truncation=True, max_length=512, return_tensors="pt")
                batch = {key: value.to(self.model.device) for key, value in batch.items()}
                hidden = self.model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                normalized = self._torch.nn.functional.normalize(pooled, p=2, dim=1)
                vectors.append(normalized.cpu().numpy())
        return np.concatenate(vectors).astype(np.float32, copy=False)

    @lru_cache(maxsize=128)
    def query_vector(self, query: str) -> np.ndarray:
        return self.encode([query], query=True)


@lru_cache(maxsize=2)
def _cached_encoder(model_dir: Path, model_signature: str) -> EmbeddingEncoder:
    return EmbeddingEncoder(model_dir)


def get_encoder(model_dir: Path = DEFAULT_MODEL_DIR) -> EmbeddingEncoder:
    model_dir = model_dir.resolve()
    info = model_dir / "model_info.json"
    if not info.exists():
        raise FileNotFoundError("Embedding model missing. Run python scripts/build_vector_index.py --download-model")
    with _ENCODER_LOCK:
        return _cached_encoder(model_dir, info.read_text(encoding="utf-8"))


def _prepare_encoder(model_dir: Path) -> EmbeddingEncoder:
    encoder = get_encoder(model_dir)
    encoder.query_vector("khởi động tìm kiếm")
    return encoder


@lru_cache(maxsize=2)
def _warmup_encoder(model_dir: Path, model_signature: str):
    return _WARMUP_EXECUTOR.submit(_prepare_encoder, model_dir)


def warmup_encoder(model_dir: Path = DEFAULT_MODEL_DIR):
    """Start preparation without blocking the UI; concurrent queries share one model."""
    model_dir = model_dir.resolve()
    signature = (model_dir / "model_info.json").read_text(encoding="utf-8")
    return _warmup_encoder(model_dir, signature)


def download_model(model_dir: Path = DEFAULT_MODEL_DIR) -> dict:
    """Pin the resolved upstream revision and save real files for offline use."""
    from huggingface_hub import model_info
    from sentence_transformers import SentenceTransformer

    revision = model_info(MODEL_ID).sha
    model = SentenceTransformer(MODEL_ID, revision=revision, cache_folder=str(Path(tempfile.gettempdir()) / "vnsearch-model-cache"), device="cpu")
    model_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(model_dir))
    dimension_method = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    info = {"model_id": MODEL_ID, "revision": revision, "dimension": int(dimension_method())}
    (model_dir / "model_info.json").write_text(json.dumps(info), encoding="utf-8")
    _cached_encoder.cache_clear()
    _warmup_encoder.cache_clear()
    return info


def article_records(doc: dict, tokenizer=None) -> list[dict]:
    header = " ".join(str(doc.get(k) or "") for k in ("title", "description")).strip()
    content = str(doc.get("content") or "")
    if tokenizer is not None:
        header_ids = tokenizer.encode(header, add_special_tokens=False, verbose=False)[:96]
        body = tokenizer.encode(content, add_special_tokens=False, verbose=False)
        header = tokenizer.decode(header_ids, skip_special_tokens=True)
        size = 384 - len(header_ids)
        chunks = [tokenizer.decode(body[i:i + size], skip_special_tokens=True) for i in range(0, len(body), size - 48)]
    else:
        words = content.split()
        chunks = [" ".join(words[i:i + 160]) for i in range(0, len(words), 136)]
    doc_id = str(doc.get("id") or doc["url"])
    return [{"record_id": doc_id, "chunk_id": f"{doc_id}:{i}", "category": str(doc.get("category") or ""),
             "text": "\n".join(part for part in (header, chunk) if part)}
            for i, chunk in enumerate(chunks or [""]) if header or chunk]


def image_records(row: dict) -> list[dict]:
    if not row.get("searchable"):
        return []
    parts = list(dict.fromkeys(str(row.get(k) or "").strip() for k in ("caption", "alt_text", "image_title", "nearby_text")))
    text = "\n".join(part for part in parts if part)
    return [{"record_id": str(row["image_id"]), "chunk_id": str(row["image_id"]),
             "asset_id": str(row.get("canonical_image_url") or row["image_url"]),
             "category": str(row.get("category") or ""), "text": text}] if text else []


class VectorIndex:
    def __init__(self, directory: Path, kind: str, *, encoder=None, model_dir: Path = DEFAULT_MODEL_DIR) -> None:
        self.directory, self.kind = directory, kind
        self.encoder, self.model_dir = encoder, model_dir
        # Retry if a writer publishes a generation while this reader is opening files.
        for attempt in range(2):
            self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if self.manifest["version"] != FORMAT_VERSION:
                raise ValueError("Unsupported vector index format; rebuild vector indexes")
            stem = self.manifest["generation"] + "-" + kind
            try:
                self.records = json.loads((directory / f"{stem}.json").read_text(encoding="utf-8"))
                self.vectors = np.load(directory / f"{stem}.npy", allow_pickle=False, mmap_mode="r")
                break
            except (FileNotFoundError, RuntimeError):
                if attempt:
                    raise
        if self.vectors.shape != (len(self.records), self.manifest["model"]["dimension"]):
            raise ValueError("Vector index metadata count mismatch")

    def search(self, query: str, *, limit: int = 50, category: str = "") -> list[tuple[str, float, str]]:
        if not query.strip() or not self.records:
            return []
        encoder = self.encoder or get_encoder(self.model_dir)
        if encoder.model_info != self.manifest["model"]:
            raise ValueError("Vector index uses a different model revision; rebuild it")
        vector = np.ascontiguousarray(encoder.query_vector(query), dtype=np.float32).copy()
        vector /= np.maximum(np.linalg.norm(vector, axis=1, keepdims=True), 1e-12)
        # Exact scan and grouping before the candidate limit preserve category recall.
        scores = self.vectors @ vector[0]
        positions = np.argsort(-scores, kind="stable")
        found = []
        seen = set()
        for position in positions:
            score = scores[position]
            row = self.records[int(position)]
            if category and row["category"].casefold() != category.casefold():
                continue
            identity = row.get("asset_id", row["record_id"])
            if identity in seen:
                continue
            seen.add(identity)
            found.append((row["record_id"], float(score), row["text"]))
            if len(found) >= limit:
                break
        return found


def _build_vector_indexes(documents_path: Path, images_path: Path, directory: Path, *, encoder=None,
                          model_dir: Path = DEFAULT_MODEL_DIR, progress: bool = False) -> dict:
    from crawler.corpus import corpus_is_consistent, read_manifest

    corpus = read_manifest(documents_path)
    if corpus and not corpus_is_consistent(documents_path, images_path):
        raise ValueError("Corpus exports do not match the manifest")
    encoder = encoder or get_encoder(model_dir)
    documents_bytes, images_bytes = documents_path.read_bytes(), images_path.read_bytes()
    docs = [json.loads(line) for line in documents_bytes.splitlines() if line.strip()]
    images = [json.loads(line) for line in images_bytes.splitlines() if line.strip()]
    signatures = {"documents_sha256": hashlib.sha256(documents_bytes).hexdigest(),
                  "images_sha256": hashlib.sha256(images_bytes).hexdigest()}
    previous_path = directory / "manifest.json"
    if previous_path.exists():
        previous = json.loads(previous_path.read_text())
        files_exist = all((directory / f"{previous['generation']}-{kind}{suffix}").exists()
                          for kind in ("articles", "images") for suffix in (".npy", ".json"))
        if files_exist and previous.get("version") == FORMAT_VERSION and previous.get("record_policy") == 1 and previous.get("model") == encoder.model_info and all(previous.get(k) == v for k, v in signatures.items()):
            return {**previous, "new_embeddings": 0}
    data = {
        "articles": [record for doc in docs for record in article_records(doc, getattr(encoder, "tokenizer", None))],
        "images": [record for image in images for record in image_records(image)],
    }
    directory.mkdir(parents=True, exist_ok=True)
    generation = uuid.uuid4().hex
    old_generation = None
    old_manifest = directory / "manifest.json"
    if old_manifest.exists():
        old_generation = json.loads(old_manifest.read_text())["generation"]
    counts = {}
    encoded_count = 0
    new_files: list[Path] = []
    try:
        for kind, records in data.items():
            cached = {}
            if old_generation:
                try:
                    old = VectorIndex(directory, kind)
                except (FileNotFoundError, ValueError):
                    old = None
                if old is not None and old.manifest["model"] == encoder.model_info:
                    cached = {_hash(row["text"]): old.vectors[i] for i, row in enumerate(old.records)}
            missing = list(dict.fromkeys(row["text"] for row in records if _hash(row["text"]) not in cached))
            if missing:
                vectors = encoder.encode(missing, progress=progress)
                cached.update({_hash(text): vector for text, vector in zip(missing, vectors)})
            encoded_count += len(missing)
            matrix = np.ascontiguousarray([cached[_hash(row["text"])] for row in records], dtype=np.float32).reshape(-1, encoder.dimension)
            if not np.isfinite(matrix).all():
                raise ValueError("Encoder produced non-finite vectors")
            matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
            stem = directory / f"{generation}-{kind}"
            index_file, records_file = stem.with_suffix(".npy"), stem.with_suffix(".json")
            new_files.extend((index_file, records_file))
            np.save(index_file, matrix, allow_pickle=False)
            records_file.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            counts[kind] = len(records)
        manifest = {"version": FORMAT_VERSION, "record_policy": 1, "backend": "numpy-flat-cosine", "generation": generation, "model": encoder.model_info,
                    "counts": counts, "documents": len(docs), "new_embeddings": encoded_count,
                    **signatures}
        if documents_bytes != documents_path.read_bytes() or images_bytes != images_path.read_bytes():
            raise ValueError("Corpus changed during vector indexing; retry the build")
        temporary = directory / "manifest.json.tmp"
        temporary.write_text(json.dumps(manifest), encoding="utf-8")
        os.replace(temporary, old_manifest)
    except Exception:
        for file in new_files:
            file.unlink(missing_ok=True)
        raise
    # Keep current and previous generation so concurrent readers can finish opening.
    for file in directory.iterdir():
        if file.suffix in {".npy", ".json", ".faiss"} and file.name != "manifest.json":
            if not file.name.startswith((generation, old_generation or generation)):
                file.unlink(missing_ok=True)
    return manifest


def build_vector_indexes(documents_path: Path, images_path: Path, directory: Path, *, encoder=None,
                         model_dir: Path = DEFAULT_MODEL_DIR, progress: bool = False) -> dict:
    from filelock import FileLock

    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / "build.lock")):
        return _build_vector_indexes(documents_path, images_path, directory, encoder=encoder,
                                     model_dir=model_dir, progress=progress)
