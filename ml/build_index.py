"""Step 7: build the FAISS index for retrieval-augmented generation.

Each recipe and food becomes a short description (name, type, cuisine or food group,
main ingredients). The descriptions are embedded with Sentence Transformers and stored
in a FAISS inner-product index over normalised vectors (cosine similarity).

The index holds ids and descriptions only. Nutrition numbers are deliberately left out:
after retrieval, the API fetches them from MySQL by id.

    python -m ml.build_index            # from data/processed (DVC stage)
The admin "rebuild index" job calls build() with documents read from MySQL instead, so
foods imported through the admin page become searchable.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from nutrimate_core.paths import MODELS, PROCESSED, params


def recipe_docs(recipes: pd.DataFrame) -> pd.DataFrame:
    def text(r):
        ings = ", ".join([i for i in str(r.ingredients or "").split("|") if i][:12])
        cuisine = "" if r.cuisine == "Unspecified" else f"{r.cuisine} "
        return f"{r.name}. {cuisine}{r.meal_type} recipe ({r.category}). Ingredients: {ings}."
    return pd.DataFrame({"doc_type": "recipe", "item_id": recipes.recipe_id.astype(str),
                         "name": recipes.name, "text": [text(r) for r in recipes.itertuples()]})


def food_docs(foods: pd.DataFrame) -> pd.DataFrame:
    def text(r):
        group = f", {r.food_group}" if isinstance(r.food_group, str) and r.food_group else ""
        src = "Indian food composition table" if str(r.food_id).startswith("INDB") else r.source
        return f"{r.name}. Food item{group}. Source: {src}."
    return pd.DataFrame({"doc_type": "food", "item_id": foods.food_id.astype(str), "name": foods.name,
                         "text": [text(r) for r in foods.itertuples()]})


def build(docs: pd.DataFrame, model_name: str | None = None, progress=None) -> dict:
    import faiss
    from sentence_transformers import SentenceTransformer

    t0 = time.time()
    model_name = model_name or params()["embeddings"]["model"]
    try:  # use the cached copy first, so startup works offline and avoids Hub rate limits
        model = SentenceTransformer(model_name, device="cpu", local_files_only=True)
    except Exception:
        model = SentenceTransformer(model_name, device="cpu")
    texts = docs.text.tolist()
    chunks = []
    step = 1024
    for s in range(0, len(texts), step):
        chunks.append(model.encode(texts[s:s + step], batch_size=128, normalize_embeddings=True,
                                   show_progress_bar=False, convert_to_numpy=True))
        if progress:
            progress(min(0.95, (s + step) / len(texts)), f"embedded {min(s + step, len(texts)):,} of {len(texts):,}")
    emb = np.vstack(chunks).astype(np.float32)
    index = faiss.IndexFlatIP(emb.shape[1])
    index.add(emb)
    MODELS.mkdir(exist_ok=True)
    tmp = MODELS / "faiss.index.tmp"
    faiss.write_index(index, str(tmp))
    docs.reset_index(drop=True).to_parquet(MODELS / "faiss_docs.parquet", index=False)
    tmp.replace(MODELS / "faiss.index")
    info = {"documents": int(len(docs)), "dimension": int(emb.shape[1]), "model": model_name,
            "recipes": int((docs.doc_type == "recipe").sum()), "foods": int((docs.doc_type == "food").sum()),
            "seconds": round(time.time() - t0, 1)}
    (MODELS / "faiss_info.json").write_text(json.dumps(info, indent=2))
    return info


def main():
    recipes = pd.read_parquet(PROCESSED / "recipes.parquet")
    foods = pd.read_parquet(PROCESSED / "foods.parquet")
    info = build(pd.concat([recipe_docs(recipes), food_docs(foods)], ignore_index=True))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
