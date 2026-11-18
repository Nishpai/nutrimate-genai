"""The recommendation engine used by the API.

Order of work for every request:
  1. Hard constraints (diet, allergies, restrictions, calorie and time limits) remove
     recipes first. A removed recipe never gets a score, so no score can bring it back.
  2. Content, LightFM fold-in and popularity scores are computed for the remaining
     recipes and blended with the tuned weights.
  3. The top candidates are reranked by the XGBoost model.
  4. Each result gets plain reasons built from data (never from the language model).
The catalogue is read from MySQL at startup, so nutrition values match the database.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd

from nutrimate_core import constraints as cons
from nutrimate_core.paths import MODELS, REPORTS
from nutrimate_core.recsys import (
    affinity_matrix,
    blend,
    category_codes,
    item_static,
    rerank_matrix,
    slug,
    zscore_rows,
)

from .. import db
from ..config import get_settings
from ..metrics import MODEL_LOADED, RECOMMEND_SECONDS

log = logging.getLogger("nutrimate.engine")
N_CANDIDATES = 100


@dataclass
class UserState:
    liked: list[int] = field(default_factory=list)       # recipe ids
    disliked: list[int] = field(default_factory=list)
    cuisines: list[str] = field(default_factory=list)    # preferred cuisines from the profile
    goal: str | None = None
    per_meal_kcal: float | None = None


class Engine:
    def __init__(self):
        self.ready = False
        self.error: str | None = None
        self.catalogue: pd.DataFrame | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        with self._lock:
            t0 = time.time()
            rows = db.all_rows("SELECT * FROM recipes ORDER BY recipe_id")
            cat = pd.DataFrame(rows)
            if cat.empty:
                raise RuntimeError("The recipes table is empty. Run python -m backend.scripts.load_catalogue")
            for c in ["keywords", "ingredients", "instructions", "description", "allergens_found"]:
                cat[c] = cat[c].fillna("")
            for c in ["is_eggetarian", "is_vegetarian", "is_vegan", "in_cf_data"]:
                cat[c] = cat[c].astype(bool)
            num = ["total_minutes", "calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g",
                   "sodium_mg", "sat_fat_g", "mean_rating"]
            cat[num] = cat[num].astype(float)
            cat["search_text"] = [cons.recipe_text(n, i, s) for n, i, s in
                                  zip(cat.name, cat.ingredients, cat.instructions)]
            cat["breakfast_fit"] = cons.breakfast_fit_column(cat).to_numpy()
            self.catalogue = cat.reset_index(drop=True)
            self.index_of = pd.Series(np.arange(len(cat)), index=cat.recipe_id)

            self.content = joblib.load(MODELS / "content.joblib")
            rows_c = pd.Series(np.arange(len(self.content.item_ids)), index=self.content.item_ids)
            # content rows in catalogue order (catalogue and model come from the same data)
            self.content_rows = rows_c.reindex(cat.recipe_id).to_numpy()
            if np.isnan(self.content_rows.astype(float)).any():
                raise RuntimeError("content model does not match the catalogue; rerun the pipeline")
            self.content_matrix = self.content.matrix[self.content_rows.astype(int)]

            lf = np.load(MODELS / "lightfm.npz")
            pos = pd.Series(np.arange(len(lf["item_ids"])), index=lf["item_ids"]).reindex(cat.recipe_id)
            self.has_cf_item = pos.notna().to_numpy()
            dim = lf["item_emb"].shape[1]
            self.item_emb = np.zeros((len(cat), dim), dtype=np.float32)
            self.item_bias = np.zeros(len(cat), dtype=np.float32)
            idx = pos.dropna().astype(int)
            self.item_emb[self.has_cf_item] = lf["item_emb"][idx.to_numpy()]
            self.item_bias[self.has_cf_item] = lf["item_bias"][idx.to_numpy()]

            pop = pd.read_parquet(MODELS / "popularity.parquet").set_index("recipe_id").liked_count
            self.pop = pop.reindex(cat.recipe_id).fillna(0).to_numpy(dtype=np.float32)
            self.z_pop = zscore_rows(np.log1p(self.pop)[None, :])[0]

            import xgboost as xgb
            self.reranker = xgb.Booster()
            self.reranker.load_model(str(MODELS / "reranker.json"))

            best = json.loads((REPORTS / "best_params.json").read_text())
            self.weights = best["weights"]
            # the evaluate step decides on validation data whether the reranker helps;
            # RERANKER=on or RERANKER=off in .env overrides that decision
            metrics_file = REPORTS / "metrics.json"
            auto = False
            if metrics_file.exists():
                auto = bool(json.loads(metrics_file.read_text()).get("reranker", {}).get("enabled_in_app"))
            choice = get_settings().reranker.lower()
            self.use_reranker = auto if choice == "auto" else choice == "on"
            self.static = item_static(cat)
            self.cui_codes, self.cuisines = category_codes(cat.cuisine)
            self.meal_codes, self.meals = category_codes(cat.meal_type)
            self.ready, self.error = True, None
            for m in ("content", "lightfm", "reranker"):
                MODEL_LOADED.labels(m).set(1)
            log.info("engine loaded %d recipes in %.1fs", len(cat), time.time() - t0)

    def info(self) -> dict:
        if not self.ready:
            return {"ready": False, "error": self.error}
        return {"ready": True, "recipes": int(len(self.catalogue)), "weights": self.weights,
                "reranker": self.use_reranker,
                "cf_items": int(self.has_cf_item.sum()), "candidates": N_CANDIDATES}

    # ------------------------------------------------------------------ scoring
    def _indices(self, ids) -> list[int]:
        return [int(self.index_of[i]) for i in ids if i in self.index_of.index]

    def preference_text(self, state: UserState) -> str:
        parts = []
        for c in state.cuisines:
            parts += [f"cuisine_{slug(c)}", f"tag_{slug(c)}"]
        if state.goal in ("lose", "gain"):
            parts.append("tag_high_protein")
        if state.goal == "lose":
            parts.append("tag_low_cholesterol tag_healthy")
        return " ".join(parts)

    def score_all(self, state: UserState) -> dict:
        liked, disliked = self._indices(state.liked), self._indices(state.disliked)
        prof = self.content.profile([self.content_rows[i] for i in liked],
                                    [self.content_rows[i] for i in disliked],
                                    self.preference_text(state) or None)
        content = self.content.scores(prof)[self.content_rows.astype(int)] if prof is not None \
            else np.zeros(len(self.catalogue), dtype=np.float32)
        liked_cf = [i for i in liked if self.has_cf_item[i]]
        disliked_cf = [i for i in disliked if self.has_cf_item[i]]
        if liked_cf:
            u = self.item_emb[liked_cf].mean(axis=0)
            if disliked_cf:
                u = u - 0.5 * self.item_emb[disliked_cf].mean(axis=0)
            cf = self.item_emb @ u + self.item_bias
        else:
            cf = np.zeros(len(self.catalogue), dtype=np.float32)
        return {"content": content.astype(np.float32), "cf": cf.astype(np.float32), "liked": liked,
                "disliked": disliked, "has_cf": bool(liked_cf), "has_content": prof is not None}

    def recommend(self, state: UserState, c: cons.Constraints, k: int = 12, exclude_ids=(),
                  restrict_ids=None, meal_types: list[str] | None = None,
                  require_nutrition: bool = False, rerank: bool = True, breakfast: bool = False) -> dict:
        """Ranked recipes that pass every hard constraint.

        breakfast=True (or meal_type "breakfast" in the constraints) keeps recipes that
        nutrimate_core.meals rates as a breakfast. If fewer than k pass under the user's
        rules, light dishes rated "maybe" are added after them and marked
        breakfast_fallback, so a strict vegan with allergies still gets a plan."""
        t0 = time.perf_counter()
        cat = self.catalogue
        if c.meal_type == "breakfast":
            breakfast = True
        if meal_types or breakfast:
            c = cons.Constraints(**{**c.__dict__, "meal_type": None})
        kept, removed = cons.filter_recipes(cat, c)
        mask = np.zeros(len(cat), dtype=bool)
        mask[kept.index.to_numpy()] = True
        if meal_types:
            mask &= cat.meal_type.isin(meal_types).to_numpy()
        fallback = np.zeros(len(cat), dtype=bool)
        breakfast_note = None
        if breakfast:
            fit = cat.breakfast_fit.to_numpy()
            strict = mask & (fit == "yes")
            nut_ok = cat[["calories_kcal", "protein_g", "carbs_g", "fat_g"]].notna().all(axis=1).to_numpy()
            n_strict = int((strict & nut_ok).sum()) if require_nutrition else int(strict.sum())
            removed["not a breakfast dish"] = int((mask & ~strict).sum())
            if n_strict < k:
                fallback = mask & (fit == "maybe")
                if fallback.any():
                    breakfast_note = (f"Only {n_strict} breakfast recipes pass your rules, so light dishes not "
                                      "tagged as breakfast are added after them and marked as a fallback.")
            mask = strict | fallback
        if require_nutrition:
            mask &= cat[["calories_kcal", "protein_g", "carbs_g", "fat_g"]].notna().all(axis=1).to_numpy()
        blocked = set(self._indices(list(exclude_ids)))
        s = self.score_all(state)
        blocked.update(s["liked"])  # already liked: shown in history, not recommended again
        blocked.update(s["disliked"])
        if blocked:
            mask[list(blocked)] = False
        if restrict_ids is not None:
            r = np.zeros(len(cat), dtype=bool)
            r[self._indices(restrict_ids)] = True
            mask &= r
        n_pass = int(mask.sum())
        if n_pass == 0:
            RECOMMEND_SECONDS.observe(time.perf_counter() - t0)
            return {"items": [], "passed": 0, "removed": removed, "mode": "none"}

        zc = zscore_rows(s["content"], mask)[0]
        zf = zscore_rows(s["cf"], mask)[0]
        zp = zscore_rows(self.z_pop, mask)[0]
        hybrid = blend(zc[None], zf[None], zp[None], self.weights, s["has_cf"])[0]
        if not s["has_content"] and not s["has_cf"]:
            hybrid = zp  # nothing known about the user yet: popularity only
        hyb = np.where(mask, hybrid, -np.inf)
        if fallback.any():
            hyb = np.where(fallback, hyb - 1e3, hyb)  # every real breakfast ranks above a fallback
        n_cand = min(N_CANDIDATES, n_pass)
        cand = np.argsort(-hyb)[:n_cand]
        final = hyb[cand]
        mode = "hybrid"
        if rerank and self.use_reranker and n_cand > 1:
            import xgboost as xgb
            rows = [s["liked"]]
            ca = affinity_matrix(rows, self.cui_codes, len(self.cuisines))
            if not s["liked"] and state.cuisines:  # cold start: use the stated cuisines
                for cu in state.cuisines:
                    if cu in self.cuisines:
                        ca[0, self.cuisines.index(cu)] = 1.0 / len(state.cuisines)
            ma = affinity_matrix(rows, self.meal_codes, len(self.meals))
            X = rerank_matrix(self.static, zc[None], zf[None], zp[None], hybrid[None], cand[None],
                              ca, ma, self.cui_codes, self.meal_codes)
            final = self.reranker.predict(xgb.DMatrix(X)) - 1e3 * fallback[cand]
            order = np.argsort(-final)
            cand, final = cand[order], final[order]
            mode = "hybrid+xgboost"
        top = cand[:k]
        items = []
        for rank, i in enumerate(top):
            items.append({
                "recipe": self.recipe_card(i),
                "score": round(float(final[rank]), 4),
                "components": {"content": round(float(zc[i]), 3), "cf": round(float(zf[i]), 3),
                               "popularity": round(float(zp[i]), 3), "hybrid": round(float(hybrid[i]), 3)},
                "reasons": self.reasons(i, s, state, c),
                **({"breakfast_fallback": True} if fallback[i] else {}),
            })
        RECOMMEND_SECONDS.observe(time.perf_counter() - t0)
        out = {"items": items, "passed": n_pass, "removed": removed, "mode": mode,
               "personalised": s["has_cf"] or s["has_content"]}
        if breakfast_note:
            out["breakfast_note"] = breakfast_note
        return out

    # ------------------------------------------------------------------ output
    def recipe_card(self, i: int) -> dict:
        r = self.catalogue.iloc[i]
        return recipe_card(r)

    def reasons(self, i: int, s: dict, state: UserState, c: cons.Constraints) -> list[str]:
        r = self.catalogue.iloc[i]
        out = []
        if s["liked"]:
            sims = (self.content_matrix[s["liked"]] @ self.content_matrix[i].T).toarray().ravel()
            j = int(np.argmax(sims))
            if sims[j] > 0.15:
                out.append(f"Similar to {self.catalogue.iloc[s['liked'][j]]['name']}, which you liked")
        if r.cuisine in state.cuisines:
            out.append(f"Matches your {r.cuisine} preference")
        if pd.notna(r.protein_g) and r.protein_g >= 20:
            out.append(f"High protein: {r.protein_g:.0f} g per serving")
        if state.per_meal_kcal and pd.notna(r.calories_kcal) and r.calories_kcal <= state.per_meal_kcal:
            out.append(f"{r.calories_kcal:.0f} kcal fits your per-meal budget of about {state.per_meal_kcal:.0f} kcal")
        if r.n_ratings >= 20 and pd.notna(r.mean_rating):
            out.append(f"Rated {r.mean_rating:.1f} by {int(r.n_ratings)} Food.com users")
        if c.exclude:
            out.append("Not found in listed ingredients: " + ", ".join(
                cons.GROUP_LABELS.get(cons.normalize_exclusion(e), e) for e in c.exclude))
        elif c.diet != "any":
            out.append(f"Fits your {c.diet} diet, based on the listed ingredients")
        return out[:4]

    def check(self, recipe_id: int, c: cons.Constraints) -> list[str]:
        i = self.index_of.get(recipe_id)
        if i is None:
            return ["unknown recipe"]
        return cons.check_recipe(self.catalogue.iloc[int(i)], c)


def _num(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def recipe_card(r) -> dict:
    return {
        "recipe_id": int(r["recipe_id"]), "name": r["name"], "cuisine": r["cuisine"],
        "meal_type": r["meal_type"], "category": r["category"],
        "total_minutes": _num(r["total_minutes"]), "servings": None if pd.isna(r["servings"]) else int(r["servings"]),
        "calories_kcal": _num(r["calories_kcal"]), "protein_g": _num(r["protein_g"]),
        "carbs_g": _num(r["carbs_g"]), "fat_g": _num(r["fat_g"]), "fiber_g": _num(r["fiber_g"]),
        "is_vegetarian": bool(r["is_vegetarian"]), "is_vegan": bool(r["is_vegan"]),
        "is_eggetarian": bool(r["is_eggetarian"]),
        "allergens": [a for a in str(r["allergens_found"]).split("|") if a],
        "mean_rating": _num(r["mean_rating"]), "n_ratings": int(r["n_ratings"]),
        "nutrition_status": r["nutrition_status"],
    }


engine = Engine()
