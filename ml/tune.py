"""Step 4: Optuna tuning on the validation split.

Study 1 tunes LightFM (factors, learning rate, regularisation, epochs) for NDCG@10 of its
own user vectors on validation. Study 2 tunes the hybrid weights (content, LightFM
fold-in, popularity) on validation with the tuned LightFM. The test split is not used.
Every trial is logged to MLflow as a nested run.
"""

from __future__ import annotations

import json

import mlflow
import numpy as np
import optuna

from ml import tracking
from ml.cf_models import lightfm_arrays, train_lightfm
from ml.common import Metrics, content_profiles, foldin_vectors, load_data
from nutrimate_core.paths import REPORTS, params
from nutrimate_core.recsys import blend, zscore_rows

BATCH = 512


def val_users(d):
    return np.where(np.asarray(d.val_pos.sum(axis=1)).ravel() > 0)[0]


def eval_lightfm_val(d, arr, users, k):
    m = Metrics(k, len(d.items))
    for s in range(0, len(users), BATCH):
        u = users[s:s + BATCH]
        sc = arr["user_emb"][u] @ arr["item_emb"].T + arr["item_bias"]
        m.add(sc, d.train_seen[u], d.val_pos[u])
    return m.result()


def main():
    p = params()
    k = p["eval"]["k"]
    seed = p["seed"]
    tracking.setup()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    d = load_data()
    users = val_users(d)
    print(f"validation users: {len(users):,}")

    with mlflow.start_run(run_name="tune"):
        def lfm_objective(trial):
            cfg = {
                "no_components": trial.suggest_categorical("no_components", [16, 32, 48, 64]),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                "item_alpha": trial.suggest_float("item_alpha", 1e-8, 1e-4, log=True),
                "epochs": trial.suggest_int("epochs", 10, 70, step=5),
                "loss": "warp",
            }
            arr = lightfm_arrays(train_lightfm(d.train_pos, cfg, seed))
            res = eval_lightfm_val(d, arr, users, k)
            with mlflow.start_run(run_name=f"lightfm-trial-{trial.number}", nested=True):
                mlflow.log_params(cfg)
                mlflow.log_metric("val_ndcg10", res[f"ndcg@{k}"])
            return res[f"ndcg@{k}"]

        s1 = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
        s1.optimize(lfm_objective, n_trials=p["tune"]["lightfm_trials"])
        best_lfm = {**s1.best_params, "loss": "warp"}
        print("best LightFM", best_lfm, round(s1.best_value, 4))

        arr = lightfm_arrays(train_lightfm(d.train_pos, best_lfm, seed))
        z_pop_row = zscore_rows(np.log1p(d.pop)[None, :])
        cache = []
        for s in range(0, len(users), BATCH):
            u = users[s:s + BATCH]
            zc = zscore_rows(content_profiles(d, d.train_pos, u) @ d.content_items.T.toarray())
            fv = foldin_vectors(arr["item_emb"], d.train_pos, u)
            zf = zscore_rows(fv @ arr["item_emb"].T + arr["item_bias"])
            has_cf = np.asarray(d.train_pos[u].sum(axis=1)).ravel() > 0
            cache.append((u, zc, zf, has_cf))

        def hyb_objective(trial):
            w = {"content": trial.suggest_float("content", 0, 1), "cf": trial.suggest_float("cf", 0, 1),
                 "pop": trial.suggest_float("pop", 0, 1)}
            tot = sum(w.values()) or 1.0
            w = {a: b / tot for a, b in w.items()}
            m = Metrics(k, len(d.items))
            for u, zc, zf, has_cf in cache:
                m.add(blend(zc, zf, z_pop_row, w, has_cf), d.train_seen[u], d.val_pos[u])
            return m.result()[f"ndcg@{k}"]

        s2 = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
        s2.optimize(hyb_objective, n_trials=p["tune"]["hybrid_trials"])
        tot = sum(s2.best_params.values()) or 1.0
        weights = {a: round(b / tot, 4) for a, b in s2.best_params.items()}
        print("best hybrid weights", weights, round(s2.best_value, 4))

        mlflow.log_params({f"best_lightfm_{a}": b for a, b in best_lfm.items()})
        mlflow.log_params({f"best_w_{a}": b for a, b in weights.items()})
        mlflow.log_metric("best_val_ndcg10_lightfm", s1.best_value)
        mlflow.log_metric("best_val_ndcg10_hybrid", s2.best_value)

    REPORTS.mkdir(exist_ok=True)
    out = {
        "lightfm": best_lfm, "weights": weights,
        "val_ndcg10_lightfm": round(s1.best_value, 4), "val_ndcg10_hybrid": round(s2.best_value, 4),
        "lightfm_trials": [{"params": t.params, "value": round(t.value, 4)} for t in s1.trials],
        "hybrid_trials": len(s2.trials),
    }
    (REPORTS / "best_params.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
