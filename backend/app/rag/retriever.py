"""FAISS retrieval over food and recipe descriptions (Sentence Transformers embeddings).

The index returns ids and descriptions only. Nutrition values are always fetched from
MySQL afterwards (see fetch_records), so the vector store can never be the source of a
number shown to the user.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import pandas as pd
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from nutrimate_core.paths import MODELS

from .. import db
from ..config import get_settings
from ..metrics import MODEL_LOADED, RETRIEVAL_SECONDS

log = logging.getLogger("nutrimate.rag")


class FaissRetriever:
    def __init__(self):
        self.ready = False
        self.error: str | None = None
        self._lock = threading.Lock()
        self.model = None
        self.index = None
        self.docs: pd.DataFrame | None = None

    def load(self) -> None:
        import faiss
        from sentence_transformers import SentenceTransformer

        with self._lock:
            t0 = time.time()
            info = json.loads((MODELS / "faiss_info.json").read_text())
            if self.model is None or getattr(self, "model_name", None) != info["model"]:
                try:  # use the cached copy first, so startup works offline and avoids Hub rate limits
                    self.model = SentenceTransformer(info["model"], device="cpu", local_files_only=True)
                except Exception:
                    self.model = SentenceTransformer(info["model"], device="cpu")
                self.model_name = info["model"]
            self.index = faiss.read_index(str(MODELS / "faiss.index"))
            self.docs = pd.read_parquet(MODELS / "faiss_docs.parquet")
            self.info = info
            self.ready, self.error = True, None
            MODEL_LOADED.labels("faiss").set(1)
            log.info("FAISS index with %d documents loaded in %.1fs", len(self.docs), time.time() - t0)

    def embed(self, texts: list[str]):
        return self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)

    def search(self, query: str, k: int = 5, doc_type: str | None = None) -> list[dict]:
        t0 = time.perf_counter()
        q = self.embed([query]).astype("float32")
        fetch = k if doc_type is None else min(len(self.docs), k * 6 + 20)
        scores, idx = self.index.search(q, fetch)
        out = []
        for s, i in zip(scores[0], idx[0]):
            if i < 0:
                continue
            d = self.docs.iloc[int(i)]
            if doc_type and d.doc_type != doc_type:
                continue
            out.append({"doc_type": d.doc_type, "item_id": d.item_id, "name": d["name"], "text": d.text,
                        "score": round(float(s), 4)})
            if len(out) >= k:
                break
        RETRIEVAL_SECONDS.observe(time.perf_counter() - t0)
        return out


retriever = FaissRetriever()


class NutriMateRetriever(BaseRetriever):
    """LangChain retriever over the FAISS index. Documents carry ids in metadata, and
    the page content is the description only (no nutrition numbers)."""

    k: int = 5
    doc_type: str | None = None

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return [Document(page_content=h["text"], metadata={k: v for k, v in h.items() if k != "text"})
                for h in retriever.search(query, k=self.k, doc_type=self.doc_type)]


def fetch_records(t: db.Tx, refs: list[tuple[str, str]]) -> dict:
    """Authoritative rows from MySQL for (doc_type, item_id) pairs."""
    out = {}
    recipe_ids = [int(i) for kind, i in refs if kind == "recipe"]
    food_ids = [i for kind, i in refs if kind == "food"]
    if recipe_ids:
        ph = ", ".join(["%s"] * len(recipe_ids))
        for r in t.all(f"""SELECT recipe_id, name, cuisine, meal_type, servings, total_minutes, calories_kcal,
                                  protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, nutrition_status,
                                  ingredients, instructions, is_vegetarian, is_vegan, is_eggetarian, source
                           FROM recipes WHERE recipe_id IN ({ph})""", recipe_ids):
            out[("recipe", str(r["recipe_id"]))] = r
    if food_ids:
        ph = ", ".join(["%s"] * len(food_ids))
        for r in t.all(f"SELECT * FROM foods WHERE food_id IN ({ph})", food_ids):
            out[("food", r["food_id"])] = r
    return out


def embedding_model_name() -> str:
    return get_settings().embedding_model
