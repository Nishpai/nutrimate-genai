"""Step 6: fit the serving models on all ratings and save them to models/.

  content.joblib      TF-IDF + nutrient content model over the full catalogue
  lightfm.npz         LightFM item embeddings and biases (NumPy only, so the API does
                      not need LightFM installed), with the tuned parameters
  popularity.parquet  liked count per recipe
The XGBoost reranker (models/reranker.json) comes from the evaluate step, where it is
trained on validation labels.
"""

from __future__ import annotations

import json
import time

import joblib
import mlflow
import numpy as np
import pandas as pd
import scipy.sparse as sp

from ml import tracking
from ml.cf_models import lightfm_arrays, train_lightfm
from ml.common import load_best_params
from nutrimate_core.paths import MODELS, PROCESSED, REPORTS, params
from nutrimate_core.recsys import ContentModel


def main():
    p = params()
    best = load_best_params()
    tracking.setup()
    t0 = time.time()
    recipes = pd.read_parquet(PROCESSED / "recipes.parquet")
    inter = pd.read_parquet(PROCESSED / "interactions.parquet")
    MODELS.mkdir(exist_ok=True)

    content = ContentModel().fit(recipes)
    joblib.dump(content, MODELS / "content.joblib", compress=3)

    items = np.sort(inter.recipe_id.unique())
    users = np.sort(inter.user_id.unique())
    ii = pd.Series(np.arange(len(items)), index=items)
    uu = pd.Series(np.arange(len(users)), index=users)
    pos = inter[inter.rating >= p["split"]["relevant_rating"]]
    m = sp.csr_matrix((np.ones(len(pos), dtype=np.float32),
                       (pos.user_id.map(uu).to_numpy(), pos.recipe_id.map(ii).to_numpy())),
                      shape=(len(users), len(items)))
    arr = lightfm_arrays(train_lightfm(m, best["lightfm"], p["seed"]))
    np.savez_compressed(MODELS / "lightfm.npz", item_ids=items, item_emb=arr["item_emb"],
                        item_bias=arr["item_bias"])

    pop = pd.DataFrame({"recipe_id": items, "liked_count": np.asarray(m.sum(axis=0)).ravel().astype(int)})
    pop.to_parquet(MODELS / "popularity.parquet", index=False)

    info = {
        "catalogue_recipes": len(recipes), "cf_items": len(items), "cf_users": len(users),
        "positive_interactions": int(m.nnz), "tfidf_vocabulary": len(content.vectorizer.vocabulary_),
        "lightfm_params": best["lightfm"], "hybrid_weights": best["weights"],
        "seconds": round(time.time() - t0, 1),
    }
    (REPORTS / "train_info.json").write_text(json.dumps(info, indent=2))
    with mlflow.start_run(run_name="train-final"):
        mlflow.log_params({f"lightfm_{a}": b for a, b in best["lightfm"].items()})
        mlflow.log_metrics({k: v for k, v in info.items() if isinstance(v, (int, float))})
        for f in ("content.joblib", "lightfm.npz", "popularity.parquet"):
            mlflow.log_artifact(str(MODELS / f))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
