"""Step 5: offline evaluation on the test split, logged to MLflow.

Protocol
  * Base models are trained on the train split only.
  * For a test user, history = train + validation ratings. Items already rated are
    never recommended. Relevant = test items rated 4 or 5.
  * Models compared: popularity, content (TF-IDF), LightFM with its trained user
    vectors, LightFM fold-in (what the app uses for its own users), PyTorch NCF,
    the weighted hybrid, and the hybrid reranked by XGBoost.
  * The XGBoost reranker is trained on validation labels (candidates from train-only
    history) and applied to the test candidates, so test labels are never seen.
  * Cold start: the same models when only a user's first 3 liked recipes are known.
  * Constraints: random diet, allergy and calorie profiles, checking every top-10
    recipe against the rules, with and without the constraint filter.
Outputs: reports/metrics.json, reports/feature_importance.json, models/reranker.json
"""

from __future__ import annotations

import json
import time

import mlflow
import numpy as np
import pandas as pd
import scipy.sparse as sp
import xgboost as xgb

from ml import tracking
from ml.cf_models import lightfm_arrays, train_lightfm, train_ncf
from ml.common import Metrics, content_profiles, foldin_vectors, load_best_params, load_data
from nutrimate_core import constraints as cons
from nutrimate_core.paths import MODELS, PROCESSED, REPORTS, params
from nutrimate_core.recsys import (
    RERANK_FEATURES,
    affinity_matrix,
    blend,
    category_codes,
    item_static,
    rerank_matrix,
    zscore_rows,
)

BATCH = 512


class Scorer:
    """Computes every model's scores for a batch of users given their history."""

    def __init__(self, d, arr, ncf, weights):
        self.d, self.arr, self.ncf, self.w = d, arr, ncf, weights
        self.z_pop = zscore_rows(np.log1p(d.pop)[None, :])
        self.content_t = d.content_items.T.toarray()

    def all(self, u, hist_pos):
        d, arr = self.d, self.arr
        content = content_profiles(d, hist_pos, u) @ self.content_t
        foldin = foldin_vectors(arr["item_emb"], hist_pos, u) @ arr["item_emb"].T + arr["item_bias"]
        zc, zf = zscore_rows(content), zscore_rows(foldin)
        has_cf = np.asarray(hist_pos[u].sum(axis=1)).ravel() > 0
        out = {
            "popularity": np.broadcast_to(d.pop.astype(np.float32), (len(u), len(d.pop))).copy(),
            "content": content,
            "lightfm_foldin": foldin,
            "hybrid": blend(zc, zf, self.z_pop, self.w, has_cf),
        }
        return out, zc, zf


def rerank_inputs(d, scorer, u, hist_pos, n_cand, cuisine_codes, n_cui, meal_codes, n_meal, static, seen):
    s, zc, zf = scorer.all(u, hist_pos)
    hyb = s["hybrid"].copy()
    co = seen[u].tocoo()
    hyb[co.row, co.col] = -np.inf
    cand = np.argpartition(-hyb, n_cand, axis=1)[:, :n_cand]
    order = np.take_along_axis(hyb, cand, axis=1).argsort(axis=1)[:, ::-1]
    cand = np.take_along_axis(cand, order, axis=1)
    rows = hist_pos[u].tolil().rows
    ca = affinity_matrix(rows, cuisine_codes, n_cui)
    ma = affinity_matrix(rows, meal_codes, n_meal)
    X = rerank_matrix(static, zc, zf, scorer.z_pop, s["hybrid"], cand, ca, ma, cuisine_codes, meal_codes)
    return s, cand, X


def make_ranker(cfg, seed, k):
    return xgb.XGBRanker(objective="rank:ndcg", subsample=0.8, colsample_bytree=0.8, random_state=seed,
                         tree_method="hist", eval_metric=f"ndcg@{k}", **cfg)


def group_ndcg(scores, labels, n_cand, n_true, k):
    """Mean NDCG@k over users whose candidate rows are consecutive blocks of n_cand."""
    disc = 1.0 / np.log2(np.arange(2, k + 2))
    s = scores.reshape(-1, n_cand)
    lab = labels.reshape(-1, n_cand)
    out = []
    for u in range(s.shape[0]):
        if n_true[u] == 0:
            continue
        top = np.argsort(-s[u])[:k]
        out.append((lab[u, top] * disc).sum() / disc[: min(int(n_true[u]), k)].sum())
    return float(np.mean(out))


def users_with(m):
    return np.where(np.asarray(m.sum(axis=1)).ravel() > 0)[0]


def first_n_likes(pos: sp.csr_matrix, train_order: pd.DataFrame, n: int) -> sp.csr_matrix:
    first = train_order.groupby("u").head(n)
    return sp.csr_matrix((np.ones(len(first), dtype=np.float32), (first.u, first.i)), shape=pos.shape)


def constraint_check(d, scorer, users, n_profiles, seed, k):
    """Share of top-k recipes that break a rule, with and without the filter."""
    rng = np.random.default_rng(seed)
    items = d.items.copy()
    items["search_text"] = [cons.recipe_text(n, i, s) for n, i, s in
                            zip(items.name, items.ingredients.fillna(""), items.instructions.fillna(""))]
    allergens = list(cons.ALLERGEN_GROUPS)
    hist = d.train_pos + d.val_pos
    with_filter = without = 0
    total_with = total_without = 0
    empty = 0
    for _ in range(n_profiles):
        c = cons.Constraints(
            diet=str(rng.choice(["any", "eggetarian", "vegetarian", "vegan"])),
            exclude=list(rng.choice(allergens, size=rng.integers(0, 3), replace=False)),
            max_calories=float(rng.choice([None, 400, 600, 800]) or 0) or None,
        )
        u = np.array([rng.choice(users)])
        scores = scorer.all(u, hist)[0]["hybrid"][0]
        top_raw = np.argsort(-scores)[:k]
        bad_raw = sum(bool(cons.check_recipe(items.iloc[i], c)) for i in top_raw)
        kept, _ = cons.filter_recipes(items, c)
        idx = kept.index.to_numpy()
        if len(idx) == 0:
            empty += 1
            continue
        top_f = idx[np.argsort(-scores[idx])[:k]]
        bad_f = sum(bool(cons.check_recipe(items.iloc[i], c)) for i in top_f)
        without += bad_raw
        total_without += len(top_raw)
        with_filter += bad_f
        total_with += len(top_f)
    return {
        "profiles": n_profiles, "profiles_with_no_match": empty,
        "violations_with_filter": int(with_filter), "recommendations_with_filter": int(total_with),
        "violations_without_filter": int(without), "recommendations_without_filter": int(total_without),
        "violation_rate_without_filter": round(without / max(total_without, 1), 4),
    }


def main():
    p = params()
    k, seed, n_cand = p["eval"]["k"], p["seed"], p["reranker"]["candidates"]
    best = load_best_params()
    tracking.setup()
    t0 = time.time()
    d = load_data()
    n_items = len(d.items)

    lfm = train_lightfm(d.train_pos, best["lightfm"], seed)
    arr = lightfm_arrays(lfm)
    t_ncf = time.time()
    ncf = train_ncf(d.train_pos, p["ncf"], seed)
    ncf_seconds = time.time() - t_ncf
    scorer = Scorer(d, arr, ncf, best["weights"])

    static = item_static(d.items)
    cui_codes, cuisines = category_codes(d.items.cuisine)
    meal_codes, meals = category_codes(d.items.meal_type)

    # ---- train the reranker on validation labels
    vu = users_with(d.val_pos)
    Xs, ys, groups = [], [], []
    for s in range(0, len(vu), BATCH):
        u = vu[s:s + BATCH]
        _, cand, X = rerank_inputs(d, scorer, u, d.train_pos, n_cand, cui_codes, len(cuisines),
                                   meal_codes, len(meals), static, d.train_seen)
        lab = np.asarray(d.val_pos[u].toarray()[np.arange(len(u))[:, None], cand]).reshape(-1)
        Xs.append(X)
        ys.append(lab)
        groups += [n_cand] * len(u)
    X, y = np.vstack(Xs), np.concatenate(ys)
    n_true = np.asarray(d.val_pos[vu].sum(axis=1)).ravel()

    # pick the reranker settings on a held-out 20% of validation users (test is not used),
    # and keep the reranker only if it beats the plain hybrid order there
    rng = np.random.default_rng(seed)
    hold = np.zeros(len(vu), dtype=bool)
    hold[rng.choice(len(vu), size=len(vu) // 5, replace=False)] = True
    row_hold = np.repeat(hold, n_cand)
    hybrid_order = -np.tile(np.arange(n_cand, dtype=float), len(vu))
    base_ndcg = group_ndcg(hybrid_order[row_hold], y[row_hold], n_cand, n_true[hold], k)
    grid = [dict(max_depth=3, n_estimators=150, learning_rate=0.05, min_child_weight=5),
            dict(max_depth=4, n_estimators=300, learning_rate=0.03, min_child_weight=10),
            dict(max_depth=p["reranker"]["max_depth"], n_estimators=p["reranker"]["n_estimators"],
                 learning_rate=p["reranker"]["learning_rate"], min_child_weight=1)]
    selection = []
    for cfg in grid:
        r = make_ranker(cfg, seed, k)
        r.fit(X[~row_hold], y[~row_hold], group=[n_cand] * int((~hold).sum()))
        selection.append({"params": cfg, "holdout_ndcg": round(group_ndcg(r.predict(X[row_hold]), y[row_hold],
                                                                         n_cand, n_true[hold], k), 4)})
    best_cfg = max(selection, key=lambda x: x["holdout_ndcg"])
    reranker_enabled = best_cfg["holdout_ndcg"] > base_ndcg
    ranker = make_ranker(best_cfg["params"], seed, k)
    ranker.fit(X, y, group=groups)
    MODELS.mkdir(exist_ok=True)
    ranker.save_model(MODELS / "reranker.json")
    importance = dict(zip(RERANK_FEATURES, [round(float(v), 4) for v in ranker.feature_importances_]))

    # ---- test
    tu = users_with(d.test_pos)
    hist = d.train_pos + d.val_pos
    seen = d.train_seen + d.val_seen
    names = ["popularity", "content", "lightfm", "lightfm_foldin", "ncf_pytorch", "hybrid", "hybrid_xgb_rerank"]
    ms = {n: Metrics(k, n_items) for n in names}
    for s in range(0, len(tu), BATCH):
        u = tu[s:s + BATCH]
        sc, cand, X = rerank_inputs(d, scorer, u, hist, n_cand, cui_codes, len(cuisines),
                                    meal_codes, len(meals), static, seen)
        sc["lightfm"] = arr["user_emb"][u] @ arr["item_emb"].T + arr["item_bias"]
        sc["ncf_pytorch"] = ncf(u)
        rr = ranker.predict(X).reshape(len(u), n_cand)
        re = sc["hybrid"] - 1e6
        re[np.arange(len(u))[:, None], cand] = 1e3 + rr
        sc["hybrid_xgb_rerank"] = re
        for n in names:
            ms[n].add(sc[n], seen[u], d.test_pos[u])
    results = {n: m.result() for n, m in ms.items()}

    # ---- cold start: only the first 3 liked recipes in train are known
    split = pd.read_parquet(PROCESSED / "split.parquet")
    rel = p["split"]["relevant_rating"]
    idx_u = pd.Series(np.arange(len(d.users)), index=d.users)
    idx_i = pd.Series(np.arange(n_items), index=d.items.recipe_id)
    tr = split[(split.split == "train") & (split.rating >= rel)].sort_values(["user_id", "ts"])
    tr = tr.assign(u=tr.user_id.map(idx_u).to_numpy(), i=tr.recipe_id.map(idx_i).to_numpy())
    cold_hist = first_n_likes(d.train_pos, tr, 3)
    cold = {n: Metrics(k, n_items) for n in ["popularity", "content", "lightfm_foldin", "hybrid"]}
    for s in range(0, len(tu), BATCH):
        u = tu[s:s + BATCH]
        sc, _, _ = scorer.all(u, cold_hist)
        for n in cold:
            cold[n].add(sc[n], cold_hist[u], d.test_pos[u])
    cold_results = {n: m.result() for n, m in cold.items()}

    cons_res = constraint_check(d, scorer, tu, p["eval"]["constraint_profiles"], seed, k)

    out = {
        "protocol": "per-user temporal split 70/10/20; history = train+val; relevant = rating >= 4",
        "k": k, "test_users": int(len(tu)), "candidate_items": n_items,
        "train_interactions": int(d.train_seen.nnz), "val_interactions": int(d.val_seen.nnz),
        "test_interactions": int(d.test_pos.nnz),
        "lightfm_params": best["lightfm"], "hybrid_weights": best["weights"],
        "reranker": {"objective": "rank:ndcg", "candidates": n_cand, "train_rows": int(len(y)),
                     "train_positives": int(y.sum()), "selection": selection,
                     "holdout_ndcg_hybrid_order": round(base_ndcg, 4), "chosen": best_cfg["params"],
                     "enabled_in_app": bool(reranker_enabled)},
        "ncf_train_seconds": round(ncf_seconds, 1),
        "models": results, "cold_start_3_likes": cold_results, "constraints": cons_res,
        "seconds": round(time.time() - t0, 1),
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "metrics.json").write_text(json.dumps(out, indent=2))
    (REPORTS / "feature_importance.json").write_text(json.dumps(importance, indent=2))

    with mlflow.start_run(run_name="evaluate"):
        mlflow.log_params({f"lightfm_{a}": b for a, b in best["lightfm"].items()})
        mlflow.log_params({f"w_{a}": b for a, b in best["weights"].items()})
        mlflow.log_params({"k": k, "rerank_candidates": n_cand, "ncf_dim": p["ncf"]["dim"]})
        for n, r in results.items():
            for mname, v in r.items():
                if mname != "users":
                    mlflow.log_metric(f"{n}.{mname.replace('@', '_at_')}", v)
        for n, r in cold_results.items():
            mlflow.log_metric(f"cold3.{n}.ndcg_at_{k}", r[f"ndcg@{k}"])
        mlflow.log_metric("reranker_enabled", int(reranker_enabled))
        mlflow.log_metric("constraint_violations_with_filter", cons_res["violations_with_filter"])
        mlflow.log_artifact(str(REPORTS / "metrics.json"))
        mlflow.log_artifact(str(REPORTS / "feature_importance.json"))
        mlflow.log_artifact(str(MODELS / "reranker.json"))
    print(json.dumps({n: r for n, r in results.items()}, indent=1))
    print(json.dumps(cold_results, indent=1))
    print(json.dumps(cons_res, indent=1))


if __name__ == "__main__":
    main()
