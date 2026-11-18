"""The assistant as a LangGraph state machine.

    parse_intent -> retrieve (FAISS) -> fetch (MySQL) -> compute (Python) -> respond (Gemini or template)

Only the last node may call Gemini, and it only receives the facts the compute node
produced. Every nutrition number in a reply comes from MySQL through Python arithmetic.
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from nutrimate_core import constraints as cons
from nutrimate_core import parser as req_parser
from nutrimate_core.nutrition import clean, percent_of, scale, total

from .. import db
from ..metrics import ASSISTANT_REPLIES
from ..services.engine import engine
from ..services.users import base_constraints, targets, user_state
from . import llm
from .retriever import fetch_records, retriever

KEYS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]
LABELS = {"calories_kcal": ("kcal", "calories"), "protein_g": ("g", "protein"), "carbs_g": ("g", "carbs"),
          "fat_g": ("g", "fat"), "fiber_g": ("g", "fibre")}


class State(TypedDict, total=False):
    question: str
    user_id: int
    profile: dict
    intent: str
    items: list[dict]
    request: dict
    hits: list[dict]
    records: dict
    facts: dict
    cards: list[dict]
    answer: str
    mode: str
    model: str | None
    validation: dict
    steps: list[dict]
    tx: Any


# ------------------------------------------------------------------ parsing helpers
LOOKUP = re.compile(r"\b(how (much|many)|calories|kcal|protein|carbs?|carbohydrates?|fat|fib(re|er)|"
                    r"nutrition|nutrients?|macros?|sugar|sodium)\b")
COMPARE = re.compile(r"\b(compare|vs\.?|versus|difference between|better than|or)\b")
TARGETS = re.compile(r"\b(my (daily )?(targets?|goals?|budget)|how (much|many) .* (should|do) i (eat|have|need)|"
                     r"left (for|today)|remaining|how am i doing|today'?s? (intake|total))\b")
RECOMMEND = re.compile(r"\b(suggest|recommend|ideas?|what (can|should) i (eat|cook|have|make)|give me|options?|"
                       r"dinner|lunch|breakfast|snacks?|meals?|recipes?)\b")
FILLER = re.compile(
    r"\b(how (much|many)|what(?:'s| is| are)?|is|are|there|in|of|the|a|an|one|calories|kcal|protein|carbs?|"
    r"carbohydrates?|fat|fib(re|er)|nutrition|nutrients?|macros?|sugar|sodium|does|do|have|has|contain|"
    r"contains|tell me|about|please|compare|vs\.?|versus|difference between|and|for|me|value|values|"
    r"facts|info|information|amount|something|anything|dish|recipe|high|low|rich|good|healthy|much|many|it|i|eat)\b|[?!.]")
UNIT = r"(g|gm|gms|grams?|kg|ml)"
WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "half": 0.5}


def _phrase_items(text: str) -> list[dict]:
    """'2 rotis and 150 g paneer' -> [{phrase: 'rotis', count: 2}, {phrase: 'paneer', grams: 150}]"""
    text = text.lower().replace("+", " and ")
    parts = re.split(r",|\band\b|\bvs\.?\b|\bversus\b|\bor\b", text)
    items = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        grams = count = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*" + UNIT + r"\b", part)
        if m:
            grams = float(m.group(1)) * (1000 if m.group(2) == "kg" else 1)
            part = part[: m.start()] + " " + part[m.end():]
        else:
            m = re.search(r"\b(\d+(?:\.\d+)?|a|an|one|two|three|four|half)\s+(?:(?:bowls?|cups?|pieces?|plates?|"
                          r"servings?|katoris?|glass(?:es)?|slices?)\s+(?:of\s+)?)?(?=[a-z])", part)
            if m:
                tok = m.group(1)
                count = float(tok) if tok[0].isdigit() else WORD_NUM[tok]
                part = part[: m.start()] + " " + part[m.end():]
        phrase = re.sub(r"\s+", " ", FILLER.sub(" ", part)).strip(" -'")
        if len(phrase) >= 2:
            items.append({"phrase": phrase, "grams": grams, "count": count})
    return items[:4]


def best_matches(phrase: str, doc_type: str | None) -> list[dict]:
    """FAISS hits re-ordered so names that contain the asked words, and fewer extra words,
    come first (for 'paneer', plain paneer beats 'paneer in butter sauce')."""
    words = {w.rstrip("s") for w in re.findall(r"[a-z]+", phrase.lower())}
    hits = retriever.search(phrase, k=8, doc_type=doc_type)
    for h in hits:
        name_words = {w.rstrip("s") for w in re.findall(r"[a-z]+", h["name"].lower())}
        overlap = len(words & name_words) / max(len(words), 1)
        extra = len(name_words - words)
        h["rank_score"] = round(h["score"] + 0.25 * overlap - 0.015 * extra, 4)
    return sorted(hits, key=lambda h: -h["rank_score"])


def parse_intent(state: State) -> State:
    q = state["question"].strip()
    ql = q.lower()
    items = []
    if TARGETS.search(ql):
        intent = "targets"
    elif re.search(r"\b(compare|vs\.?|versus|difference between)\b", ql):
        intent = "compare"
        items = _phrase_items(re.sub(r"\b(compare|difference between)\b", " ", ql))
    elif LOOKUP.search(ql) and not RECOMMEND.search(ql.replace("meal", "")):
        intent = "lookup"
        items = _phrase_items(ql)
    elif RECOMMEND.search(ql):
        intent = "recommend"
    else:
        intent = "search"
    if intent in ("lookup", "compare") and not items:
        intent = "search"
    return {"intent": intent, "items": items}


def retrieve(state: State) -> State:
    intent = state["intent"]
    if intent == "targets":
        return {"hits": []}
    if not retriever.ready:
        raise RuntimeError("semantic index not loaded")
    hits = []
    if intent in ("lookup", "compare"):
        for it in state["items"]:
            # weighed amounts and comparisons are about plain foods first; dishes come
            # from the recipe side when no food is a close match
            prefer_food = bool(it.get("grams")) or intent == "compare"
            found = best_matches(it["phrase"], "food" if prefer_food else None)
            if prefer_food and (not found or found[0]["rank_score"] < 0.55):
                found = best_matches(it["phrase"], None)
            if found:
                it["match"] = found[0]
                it["alternatives"] = [f["name"] for f in found[1:3]]
                hits.append(found[0])
    elif intent == "recommend":
        hits = retriever.search(state["question"], k=60, doc_type="recipe")
    else:  # search
        hits = retriever.search(state["question"], k=5)
    return {"hits": hits}


def fetch(state: State) -> State:
    refs = [(h["doc_type"], h["item_id"]) for h in state.get("hits", [])]
    return {"records": fetch_records(state["tx"], refs) if refs else {}}


def _portion(rec: dict, kind: str, it: dict) -> tuple[dict, str]:
    """Nutrition for the asked portion, computed from MySQL values."""
    if kind == "recipe":
        n = it.get("count") or 1
        vals = scale({k: rec.get(k) for k in KEYS}, n, KEYS)
        return vals, f"{n:g} serving{'s' if n != 1 else ''} (Food.com per-serving values)"
    per100 = {"calories_kcal": rec.get("kcal_100g"), "protein_g": rec.get("protein_100g"),
              "carbs_g": rec.get("carbs_100g"), "fat_g": rec.get("fat_100g"), "fiber_g": rec.get("fiber_100g")}
    if it.get("grams"):
        return scale(per100, it["grams"] / 100, KEYS), f"{it['grams']:g} g"
    if it.get("count") and clean(rec.get("kcal_serving")) is not None:
        serving = {"calories_kcal": rec.get("kcal_serving"), "protein_g": rec.get("protein_serving"),
                   "carbs_g": rec.get("carbs_serving"), "fat_g": rec.get("fat_serving"),
                   "fiber_g": rec.get("fiber_serving")}
        n = it["count"]
        return scale(serving, n, KEYS), f"{n:g} x {rec.get('serving_unit') or 'serving'}"
    return scale(per100, 1, KEYS), "100 g"


def _r(v, d=1):
    v = clean(v)
    return None if v is None else round(v, d)


def _warnings(profile: dict, kind: str, rec: dict) -> list[str]:
    c = base_constraints(profile)
    if kind == "recipe" and engine.ready:
        return [f"{rec['name']}: {p}" for p in engine.check(int(rec["recipe_id"]), c)]
    text = str(rec.get("name", "")).lower()
    out = []
    for term in c.exclude:
        if cons.term_matches(text, term):
            out.append(f"{rec['name']}: mentions {term}")
    if c.diet != "any" and cons.has_meat_or_fish(text):
        out.append(f"{rec['name']}: contains meat or fish")
    return out


def compute(state: State) -> State:
    intent, profile, t = state["intent"], state["profile"], state["tx"]
    tg = targets(profile)
    recs = state.get("records", {})
    facts: dict = {"intent": intent}
    cards: list[dict] = []
    if intent in ("lookup", "compare"):
        rows, warnings = [], []
        for it in state["items"]:
            m = it.get("match")
            if not m:
                rows.append({"asked_for": it["phrase"], "found": False})
                continue
            rec = recs.get((m["doc_type"], m["item_id"]))
            if rec is None:
                continue
            vals, portion = _portion(rec, m["doc_type"], it)
            row = {"asked_for": it["phrase"], "matched": rec["name"], "type": m["doc_type"], "portion": portion,
                   "source": rec.get("source"), **{k: _r(v) for k, v in vals.items()},
                   "match_score": m["score"]}
            if intent == "lookup" and tg["calories_kcal"]:
                row["percent_of_daily_calories"] = percent_of(vals["calories_kcal"], tg["calories_kcal"])
                row["percent_of_daily_protein"] = percent_of(vals["protein_g"], tg["protein_g"])
            rows.append(row)
            warnings += _warnings(profile, m["doc_type"], rec)
            cards.append({"type": m["doc_type"], "id": m["item_id"], "name": rec["name"], "portion": portion,
                          **{k: _r(v) for k, v in vals.items()}})
        facts["items"] = rows
        found = [r for r in rows if r.get("matched")]
        if intent == "lookup" and len(found) > 1:
            tot = total(found, KEYS, label_key="matched")
            facts["total"] = tot["totals"]
            facts["total_complete"] = tot["complete"]
        if intent == "compare" and len(found) >= 2:
            a, b = found[0], found[1]
            facts["difference_first_minus_second"] = {
                k: (None if a.get(k) is None or b.get(k) is None else round(a[k] - b[k], 1)) for k in KEYS}
            facts["note"] = "Values are for the portions shown (recipes per serving, foods per 100 g unless a weight was given)."
        facts["warnings"] = warnings
    elif intent == "recommend":
        result = req_parser.parse(state["question"])
        req = result["request"]
        c = req_parser.to_constraints(req, base_constraints(profile))
        st = user_state(t, state["user_id"], profile)
        ids = [int(h["item_id"]) for h in state.get("hits", [])]
        rec = engine.recommend(st, c, k=5, restrict_ids=ids) if ids else {"items": []}
        source = "semantic match ranked by your model"
        if len(rec["items"]) < 3:
            rec = engine.recommend(st, c, k=5)
            source = "your model (few semantic matches passed your rules)"
        ids = [it["recipe"]["recipe_id"] for it in rec["items"]]
        db_rows = fetch_records(t, [("recipe", str(i)) for i in ids])  # authoritative values
        facts["rules_applied"] = c.describe()
        facts["notes"] = result["notes"]
        facts["ranking"] = source
        facts["recipes"] = []
        for it in rec["items"]:
            r = db_rows[("recipe", str(it["recipe"]["recipe_id"]))]
            facts["recipes"].append({"name": r["name"], "cuisine": r["cuisine"], "meal_type": r["meal_type"],
                                     "minutes": _r(r["total_minutes"], 0),
                                     **{k: _r(r[k]) for k in KEYS}, "why": it["reasons"][:2]})
            cards.append({"type": "recipe", "id": str(r["recipe_id"]), "name": r["name"], "portion": "1 serving",
                          **{k: _r(r[k]) for k in KEYS}})
        if not rec["items"]:
            facts["no_results"] = "No recipe passed all of the rules. Try relaxing a limit."
    elif intent == "targets":
        today = date.today()
        row = t.one("""SELECT SUM(calories_kcal) AS calories_kcal, SUM(protein_g) AS protein_g,
                              SUM(carbs_g) AS carbs_g, SUM(fat_g) AS fat_g, SUM(fiber_g) AS fiber_g, COUNT(*) AS n
                       FROM meal_logs WHERE user_id = %s AND log_date = %s""", (state["user_id"], today))
        eaten = {k: _r(row[k]) or 0.0 for k in KEYS}
        facts["date"] = today.isoformat()
        facts["daily_targets"] = {k: tg[k] for k in KEYS}
        facts["eaten_today"] = eaten
        facts["meals_logged_today"] = int(row["n"])
        facts["remaining"] = {k: (None if tg[k] is None else max(round(tg[k] - eaten[k], 1), 0.0)) for k in KEYS}
        over = {k: round(eaten[k] - tg[k], 1) for k in KEYS if tg[k] is not None and eaten[k] > tg[k]}
        if over:
            facts["over_target_by"] = over
        facts["target_method"] = "Mifflin-St Jeor estimate from the profile, or the user's own numbers"
    else:  # search
        facts["matches"] = []
        for h in state.get("hits", []):
            rec = recs.get((h["doc_type"], h["item_id"]))
            if rec is None:
                continue
            if h["doc_type"] == "recipe":
                vals, basis = {k: _r(rec[k]) for k in KEYS}, "per serving"
            else:
                vals = {"calories_kcal": _r(rec["kcal_100g"]), "protein_g": _r(rec["protein_100g"]),
                        "carbs_g": _r(rec["carbs_100g"]), "fat_g": _r(rec["fat_100g"]),
                        "fiber_g": _r(rec["fiber_100g"])}
                basis = "per 100 g"
            facts["matches"].append({"name": rec["name"], "type": h["doc_type"], "basis": basis, **vals})
            cards.append({"type": h["doc_type"], "id": h["item_id"], "name": rec["name"], "portion": basis, **vals})
    return {"facts": facts, "cards": cards}


def _fmt(v, unit):
    return "unknown" if v is None else f"{v:g} {unit}"


def template_answer(facts: dict) -> str:
    """Deterministic answer used without Gemini, or when Gemini's reply fails validation."""
    intent = facts["intent"]
    lines = []
    if intent in ("lookup", "compare"):
        for r in facts.get("items", []):
            if not r.get("matched"):
                lines.append(f"I could not find '{r['asked_for']}' in the database.")
                continue
            vals = ", ".join(f"{_fmt(r[k], LABELS[k][0])} {LABELS[k][1]}" for k in KEYS)
            lines.append(f"{r['matched']} ({r['portion']}): {vals}.")
        if facts.get("total"):
            t = facts["total"]
            lines.append("Total: " + ", ".join(f"{_fmt(t[k], LABELS[k][0])} {LABELS[k][1]}" for k in KEYS) +
                         ("." if facts.get("total_complete") else " (some values are unknown, so this is partial)."))
        diff = facts.get("difference_first_minus_second")
        if diff and diff.get("protein_g") is not None:
            items = [r for r in facts["items"] if r.get("matched")]
            lines.append(f"{items[0]['matched']} has {abs(diff['protein_g']):g} g "
                         f"{'more' if diff['protein_g'] >= 0 else 'less'} protein than {items[1]['matched']}"
                         f" for these portions.")
    elif intent == "recommend":
        if facts.get("no_results"):
            lines.append(facts["no_results"])
        if facts.get("rules_applied"):
            lines.append("Rules applied: " + ", ".join(facts["rules_applied"]) + ".")
        for n, r in enumerate(facts.get("recipes", []), 1):
            lines.append(f"{n}. {r['name']}: {_fmt(r['calories_kcal'], 'kcal')}, {_fmt(r['protein_g'], 'g')} protein"
                         f" per serving.")
    elif intent == "targets":
        tg, eaten, rem = facts["daily_targets"], facts["eaten_today"], facts["remaining"]
        if tg["calories_kcal"] is None:
            lines.append("You have not set a calorie target yet. Add it in Settings to track what is left.")
        else:
            over = facts.get("over_target_by", {})
            left = (f"you are {_fmt(over['calories_kcal'], 'kcal')} over it" if "calories_kcal" in over
                    else f"{_fmt(rem['calories_kcal'], 'kcal')} remain")
            lines.append(f"Today you have logged {_fmt(eaten['calories_kcal'], 'kcal')} of your "
                         f"{_fmt(tg['calories_kcal'], 'kcal')} target, so {left}.")
            if tg["protein_g"] is not None:
                p_left = (f"{_fmt(over['protein_g'], 'g')} over" if "protein_g" in over
                          else f"{_fmt(rem['protein_g'], 'g')} left")
                lines.append(f"Protein: {_fmt(eaten['protein_g'], 'g')} of {_fmt(tg['protein_g'], 'g')} ({p_left}).")
    else:
        for r in facts.get("matches", [])[:5]:
            lines.append(f"{r['name']} ({r['basis']}): {_fmt(r['calories_kcal'], 'kcal')}, "
                         f"{_fmt(r['protein_g'], 'g')} protein.")
        if not lines:
            lines.append("I could not find anything matching that. Try naming a food or a dish.")
    for w in facts.get("warnings", []):
        lines.append(f"Warning for your profile: {w}.")
    return "\n".join(lines)


TASKS = {
    "lookup": "Answer the question using the item values (and total if present). Mention the portion basis.",
    "compare": "Compare the items for the user's question. Use the difference values given.",
    "recommend": "Briefly introduce these recipes and why they suit the user. Mention rules applied.",
    "targets": "Tell the user where they stand today against their targets.",
    "search": "Summarise the closest matches found.",
}


def respond(state: State) -> State:
    facts = state["facts"]
    fallback = template_answer(facts)
    if llm.gemini_available():
        try:
            text, model = llm.write(state["question"], facts, TASKS.get(state["intent"], TASKS["search"]))
            check = llm.validate_numbers(text, facts, state["question"])
            if check["ok"]:
                ASSISTANT_REPLIES.labels("gemini").inc()
                return {"answer": text, "mode": "gemini", "model": model, "validation": check}
            ASSISTANT_REPLIES.labels("fallback_rejected").inc()
            return {"answer": fallback, "mode": "fallback", "model": model,
                    "validation": {**check, "reason": "Gemini used a number that is not in the database facts"}}
        except Exception as exc:
            ASSISTANT_REPLIES.labels("fallback_error").inc()
            return {"answer": fallback, "mode": "fallback", "model": None,
                    "validation": {"ok": True, "reason": f"Gemini unavailable: {exc}"}}
    ASSISTANT_REPLIES.labels("fallback_no_key").inc()
    return {"answer": fallback, "mode": "fallback", "model": None,
            "validation": {"ok": True, "reason": "No GEMINI_API_KEY set, template answer"}}


def _timed(name, fn):
    def wrapper(state: State) -> State:
        t0 = time.perf_counter()
        out = fn(state)
        steps = list(state.get("steps", []))
        detail = {"parse_intent": lambda o: o.get("intent"),
                  "retrieve": lambda o: f"{len(o.get('hits', []))} FAISS hits",
                  "fetch": lambda o: f"{len(o.get('records', {}))} rows from MySQL",
                  "compute": lambda o: "deterministic nutrition maths",
                  "respond": lambda o: o.get("mode")}[name](out)
        steps.append({"node": name, "ms": round(1000 * (time.perf_counter() - t0), 1), "detail": detail})
        out["steps"] = steps
        return out
    return wrapper


def build_graph():
    g = StateGraph(State)
    for name, fn in [("parse_intent", parse_intent), ("retrieve", retrieve), ("fetch", fetch),
                     ("compute", compute), ("respond", respond)]:
        g.add_node(name, _timed(name, fn))
    g.add_edge(START, "parse_intent")
    g.add_edge("parse_intent", "retrieve")
    g.add_edge("retrieve", "fetch")
    g.add_edge("fetch", "compute")
    g.add_edge("compute", "respond")
    g.add_edge("respond", END)
    return g.compile()


GRAPH = build_graph()


def ask(t: db.Tx, user_id: int, profile: dict, question: str) -> dict:
    out = GRAPH.invoke({"question": question, "user_id": user_id, "profile": profile, "tx": t, "steps": []})
    return {k: out.get(k) for k in ("answer", "mode", "model", "intent", "facts", "cards", "validation", "steps")}
