"""Shared pieces for tuning and evaluation: the user-item matrices and the metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp

from nutrimate_core.paths import PROCESSED, REPORTS, params
from nutrimate_core.recsys import ContentModel


@dataclass
class Data:
    recipes: pd.DataFrame          # full catalogue
    items: pd.DataFrame            # recipes that have ratings (the CF item space)
    users: np.ndarray
    train_pos: sp.csr_matrix       # rating >= 4 in train
    train_seen: sp.csr_matrix      # any rating in train
    val_pos: sp.csr_matrix
    val_seen: sp.csr_matrix
    test_pos: sp.csr_matrix
    content: ContentModel
    content_items: sp.csr_matrix   # content matrix rows for self.items
    pop: np.ndarray                # train positive count per item


def _matrix(df, n_users, n_items):
    return sp.csr_matrix((np.ones(len(df), dtype=np.float32), (df.u.to_numpy(), df.i.to_numpy())),
                         shape=(n_users, n_items))


def load_data() -> Data:
    rel = params()["split"]["relevant_rating"]
    recipes = pd.read_parquet(PROCESSED / "recipes.parquet")
    split = pd.read_parquet(PROCESSED / "split.parquet")
    items = recipes[recipes.in_cf_data].reset_index(drop=True)
    item_index = pd.Series(np.arange(len(items)), index=items.recipe_id)
    users = np.sort(split.user_id.unique())
    user_index = pd.Series(np.arange(len(users)), index=users)
    split = split.assign(u=split.user_id.map(user_index).to_numpy(), i=split.recipe_id.map(item_index).to_numpy())
    nu, ni = len(users), len(items)
    m = {}
    for part in ("train", "val", "test"):
        s = split[split.split == part]
        m[part + "_seen"] = _matrix(s, nu, ni)
        m[part + "_pos"] = _matrix(s[s.rating >= rel], nu, ni)
    content = ContentModel().fit(recipes)
    rows = pd.Series(np.arange(len(recipes)), index=recipes.recipe_id)[items.recipe_id].to_numpy()
    pop = np.asarray(m["train_pos"].sum(axis=0)).ravel()
    return Data(recipes, items, users, m["train_pos"], m["train_seen"], m["val_pos"], m["val_seen"],
                m["test_pos"], content, content.matrix[rows], pop)


def content_profiles(d: Data, pos: sp.csr_matrix, user_idx) -> np.ndarray:
    """Mean content vector of each user's liked items, L2-normalised (dense, users x dim)."""
    sub = pos[user_idx]
    counts = np.maximum(np.asarray(sub.sum(axis=1)).ravel(), 1)
    prof = sp.diags(1.0 / counts) @ sub @ d.content_items
    prof = np.asarray(prof.todense(), dtype=np.float32)
    n = np.linalg.norm(prof, axis=1, keepdims=True)
    n[n == 0] = 1
    return prof / n


def foldin_vectors(item_emb: np.ndarray, pos: sp.csr_matrix, user_idx) -> np.ndarray:
    sub = pos[user_idx]
    counts = np.maximum(np.asarray(sub.sum(axis=1)).ravel(), 1)
    return np.asarray((sp.diags(1.0 / counts) @ sub) @ item_emb, dtype=np.float32)


class Metrics:
    """Accumulates precision, recall, NDCG and hit rate at k, plus catalogue coverage."""

    def __init__(self, k: int, n_items: int):
        self.k, self.n_items = k, n_items
        self.p, self.r, self.n, self.h = [], [], [], []
        self.recommended: set[int] = set()
        self.discount = 1.0 / np.log2(np.arange(2, k + 2))

    def add(self, scores: np.ndarray, seen: sp.csr_matrix, relevant: sp.csr_matrix):
        scores = scores.copy()
        seen = seen.tocoo()
        scores[seen.row, seen.col] = -np.inf
        top = np.argpartition(-scores, self.k, axis=1)[:, : self.k]
        order = np.take_along_axis(scores, top, axis=1).argsort(axis=1)[:, ::-1]
        top = np.take_along_axis(top, order, axis=1)
        rel = relevant.tolil().rows
        for u in range(scores.shape[0]):
            truth = set(rel[u])
            if not truth:
                continue
            hits = np.array([i in truth for i in top[u]], dtype=float)
            self.p.append(hits.sum() / self.k)
            self.r.append(hits.sum() / len(truth))
            ideal = self.discount[: min(len(truth), self.k)].sum()
            self.n.append((hits * self.discount).sum() / ideal)
            self.h.append(float(hits.any()))
            self.recommended.update(top[u].tolist())

    def result(self) -> dict:
        return {
            f"precision@{self.k}": round(float(np.mean(self.p)), 4),
            f"recall@{self.k}": round(float(np.mean(self.r)), 4),
            f"ndcg@{self.k}": round(float(np.mean(self.n)), 4),
            f"hit_rate@{self.k}": round(float(np.mean(self.h)), 4),
            "coverage": round(len(self.recommended) / self.n_items, 4),
            "users": len(self.n),
        }


def load_best_params() -> dict:
    path = REPORTS / "best_params.json"
    p = params()
    best = {"lightfm": dict(p["lightfm"]), "weights": {"content": 0.3, "cf": 0.5, "pop": 0.2}}
    if path.exists():
        saved = json.loads(path.read_text())
        best["lightfm"].update(saved.get("lightfm", {}))
        best["weights"].update(saved.get("weights", {}))
    return best
