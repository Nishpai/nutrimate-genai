"""Recommendation scoring shared by the offline pipeline and the API.

The same functions build the content profile, fold a user into the LightFM space,
blend the scores and build the reranker features, so what was evaluated offline is
what the app runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler, normalize

CONTENT_NUTRIENTS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]
NUTRIENT_WEIGHT = 0.35   # weight of the scaled nutrient block next to the TF-IDF block



def slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(s).lower())


def item_text(df: pd.DataFrame) -> list[str]:
    """Text describing a recipe for TF-IDF: name, tags, ingredients, cuisine and meal type."""
    out = []
    for name, kw, ing, cui, mt in zip(df["name"], df["keywords"].fillna(""), df["ingredients"].fillna(""),
                                      df["cuisine"].fillna(""), df["meal_type"].fillna("")):
        tags = " ".join("tag_" + slug(k) for k in str(kw).split("|") if k)
        ings = " ".join(slug(i) for i in str(ing).split("|") if i)
        out.append(f"{name} {name} {tags} {ings} cuisine_{slug(cui)} meal_{slug(mt)}")
    return out


class ContentModel:
    """TF-IDF over recipe text plus scaled nutrients. Scores are cosine similarities."""

    def __init__(self, max_features: int = 30000):
        self.vectorizer = TfidfVectorizer(min_df=2, max_features=max_features, sublinear_tf=True,
                                          token_pattern=r"(?u)\b\w\w+\b")
        self.scaler = StandardScaler()
        self.item_ids: np.ndarray | None = None
        self.matrix: sp.csr_matrix | None = None

    def fit(self, recipes: pd.DataFrame) -> ContentModel:
        tfidf = self.vectorizer.fit_transform(item_text(recipes))
        self.matrix = self._combine(tfidf, recipes, fit=True)
        self.item_ids = recipes["recipe_id"].to_numpy()
        return self

    def _combine(self, tfidf, recipes, fit=False):
        nut = recipes[CONTENT_NUTRIENTS].astype(float)
        # unknown nutrients get the column median for similarity only; they are never shown
        nut = nut.fillna(nut.median() if fit else pd.Series(self.scaler.mean_, index=CONTENT_NUTRIENTS))
        z = self.scaler.fit_transform(nut) if fit else self.scaler.transform(nut)
        z = np.clip(z, -3, 3) * NUTRIENT_WEIGHT / np.sqrt(len(CONTENT_NUTRIENTS))
        return normalize(sp.hstack([tfidf, sp.csr_matrix(z)]).tocsr())

    def text_vector(self, text: str) -> sp.csr_matrix:
        v = self.vectorizer.transform([text])
        pad = sp.csr_matrix((1, len(CONTENT_NUTRIENTS)))
        return normalize(sp.hstack([v, pad]).tocsr())

    def profile(self, liked_idx, disliked_idx=(), text: str | None = None) -> np.ndarray | None:
        """User vector: mean of liked rows minus half the mean of disliked rows, plus text."""
        parts = []
        if len(liked_idx):
            parts.append(np.asarray(self.matrix[list(liked_idx)].mean(axis=0)).ravel())
        if len(disliked_idx):
            parts.append(-0.5 * np.asarray(self.matrix[list(disliked_idx)].mean(axis=0)).ravel())
        if text:
            parts.append(self.text_vector(text).toarray().ravel())
        if not parts:
            return None
        u = np.sum(parts, axis=0)
        n = np.linalg.norm(u)
        return u / n if n > 0 else None

    def scores(self, profile: np.ndarray | None) -> np.ndarray:
        if profile is None:
            return np.zeros(self.matrix.shape[0], dtype=np.float32)
        return np.asarray(self.matrix @ profile, dtype=np.float32).ravel()

    def batch_scores(self, profiles: np.ndarray) -> np.ndarray:
        """profiles: (n_users, dim) dense. Returns (n_users, n_items)."""
        return np.asarray((self.matrix @ profiles.T).T, dtype=np.float32)


def fold_in(item_emb: np.ndarray, liked_idx, disliked_idx=()) -> np.ndarray | None:
    """LightFM user vector for someone outside the training data: mean of liked item
    embeddings minus half the mean of disliked ones. The offline evaluation measures
    this exact path next to LightFM's own trained user vectors."""
    if not len(liked_idx):
        return None
    u = item_emb[list(liked_idx)].mean(axis=0)
    if len(disliked_idx):
        u = u - 0.5 * item_emb[list(disliked_idx)].mean(axis=0)
    return u


def cf_scores(item_emb, item_bias, user_vec) -> np.ndarray:
    if user_vec is None:
        return np.zeros(item_emb.shape[0], dtype=np.float32)
    return (item_emb @ user_vec + item_bias).astype(np.float32)


def zscore_rows(m: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Standardise each row (user) so different score scales can be blended.
    mask marks the entries that count (candidates); others do not affect mean or std."""
    m = np.atleast_2d(m).astype(np.float32)
    if mask is None:
        mu = m.mean(axis=1, keepdims=True)
        sd = m.std(axis=1, keepdims=True)
    else:
        mask = np.atleast_2d(mask)
        cnt = np.maximum(mask.sum(axis=1, keepdims=True), 1)
        mu = (m * mask).sum(axis=1, keepdims=True) / cnt
        sd = np.sqrt((((m - mu) * mask) ** 2).sum(axis=1, keepdims=True) / cnt)
    sd[sd == 0] = 1.0
    return (m - mu) / sd


def blend(z_content, z_cf, z_pop, weights: dict, has_cf: np.ndarray | bool = True) -> np.ndarray:
    """Weighted ranking. Users with no CF signal get its weight moved to content and popularity."""
    wc, wf, wp = weights["content"], weights["cf"], weights["pop"]
    has_cf = np.asarray(has_cf, dtype=bool).reshape(-1, 1) if np.ndim(has_cf) else bool(has_cf)
    out_with = wc * z_content + wf * z_cf + wp * z_pop
    s = wc + wp
    out_without = (wc / s) * z_content + (wp / s) * z_pop if s > 0 else z_pop
    return np.where(has_cf, out_with, out_without)


STATIC_FEATURES = ["log_n_ratings", "mean_rating", "calories_kcal", "protein_g", "carbs_g", "fat_g",
                   "fiber_g", "log_minutes", "is_vegetarian"]
RERANK_FEATURES = ["z_content", "z_cf", "z_pop", "hybrid", "hybrid_rank", "cuisine_aff", "meal_aff",
                   *STATIC_FEATURES]


def item_static(items: pd.DataFrame) -> np.ndarray:
    """Per-item reranker features. Unknown nutrients stay NaN (XGBoost handles missing values)."""
    return np.column_stack([
        np.log1p(items["n_ratings"].fillna(0).to_numpy(dtype=float)),
        items["mean_rating"].to_numpy(dtype=float),
        *[items[c].to_numpy(dtype=float) for c in ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]],
        np.log1p(items["total_minutes"].to_numpy(dtype=float)),
        items["is_vegetarian"].astype(float).to_numpy(),
    ]).astype(np.float32)


def category_codes(values: pd.Series) -> tuple[np.ndarray, list]:
    cats = sorted(values.fillna("").unique().tolist())
    lookup = {c: i for i, c in enumerate(cats)}
    return values.fillna("").map(lookup).to_numpy(), cats


def affinity_matrix(pos_rows: list, codes: np.ndarray, n_codes: int) -> np.ndarray:
    """For each user, the share of their liked items in each category (cuisine or meal type)."""
    out = np.zeros((len(pos_rows), n_codes), dtype=np.float32)
    for b, items in enumerate(pos_rows):
        if len(items):
            np.add.at(out[b], codes[list(items)], 1.0)
            out[b] /= len(items)
    return out


def rerank_matrix(static, zc, zf, zp, hyb, cand, cuisine_aff, meal_aff, cuisine_codes, meal_codes):
    """Features for candidates. zc, zf, zp, hyb: (users, items). cand: (users, C) item
    indices sorted by hybrid score. Returns (users * C, n_features)."""
    b, c = cand.shape
    rows = np.arange(b)[:, None]
    cols = [
        zc[rows, cand], zf[rows, cand], np.broadcast_to(zp, hyb.shape)[rows, cand], hyb[rows, cand],
        np.broadcast_to(np.arange(c, dtype=np.float32), (b, c)),
        cuisine_aff[rows, cuisine_codes[cand]], meal_aff[rows, meal_codes[cand]],
    ]
    feats = [x.reshape(-1) for x in cols]
    st = static[cand.reshape(-1)]
    return np.column_stack(feats + [st[:, j] for j in range(st.shape[1])]).astype(np.float32)
