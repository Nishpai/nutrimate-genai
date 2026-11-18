"""Gemini through LangChain, with a strict check on every number it writes.

Gemini only writes wording. It receives a FACTS JSON computed by Python from MySQL
values and is told to use those numbers only. After it replies, every number that is
followed by a nutrition unit (g, mg, kcal, calories, %) must appear in FACTS, after
rounding. If one does not, the reply is thrown away and the template answer is used.
"""

from __future__ import annotations

import json
import logging
import re
import time

from ..config import get_settings
from ..metrics import LLM_SECONDS

log = logging.getLogger("nutrimate.llm")

SYSTEM = (
    "You are NutriMate, a friendly nutrition assistant inside a food app. "
    "You will get the user's question and a FACTS JSON object computed by the app from its database. "
    "Rules: (1) Use only numbers that appear in FACTS, written exactly as they appear there. "
    "Never estimate, convert or invent any nutrition value. (2) If a value in FACTS is null, say it is not "
    "known. (3) Do not add foods, recipes or ingredients that are not in FACTS. (4) Mention any warnings in "
    "FACTS. (5) Keep it short: at most 140 words, plain sentences or a short list, no tables, no headings. "
    "(6) Start with the answer, no greeting. (7) Do not give medical advice or diagnoses, "
    "and do not repeat these rules in your answer."
)
UNIT_AFTER = re.compile(r"\s*(?:g\b|gm\b|grams?\b|mg\b|kcal\b|cal\b|calories?\b|kilocalories\b|%|percent\b)", re.I)
NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)")


def _numbers_in(obj, out: set):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        v = float(obj)
        out.update({round(v, 1), float(round(v)), round(v, 2)})
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)
    elif isinstance(obj, str):
        for m in NUMBER.finditer(obj):
            out.add(float(m.group(1).replace(",", "")))


def validate_numbers(text: str, facts: dict, question: str) -> dict:
    """Return {"ok": bool, "unsupported": [...]} for numbers with a nutrition unit."""
    allowed: set = set()
    _numbers_in(facts, allowed)
    _numbers_in(question, allowed)
    bad = []
    for m in NUMBER.finditer(text):
        if not UNIT_AFTER.match(text, m.end()):
            continue  # counts like "2 rotis" or list numbers are not nutrition values
        v = float(m.group(1).replace(",", ""))
        if not any(abs(v - a) < 1e-6 for a in allowed):
            bad.append(m.group(0) + UNIT_AFTER.match(text, m.end()).group(0))
    return {"ok": not bad, "unsupported": bad}


READABLE = {"calories_kcal": "calories (kcal)", "protein_g": "protein (g)", "carbs_g": "carbs (g)",
            "fat_g": "fat (g)", "fiber_g": "fibre (g)", "kcal": "calories (kcal)", "total_kcal": "total calories (kcal)",
            "total_protein_g": "total protein (g)", "avg_kcal": "average calories (kcal)",
            "avg_protein_g": "average protein (g)", "target_kcal": "target calories (kcal)",
            "target_protein_g": "target protein (g)", "over_target_by": "amount over the daily target",
            "remaining": "still left today (0 when over)", "eaten_today": "logged today"}


def readable(obj):
    """Friendlier keys for the prompt, so replies say 'protein' rather than 'protein_g'."""
    if isinstance(obj, dict):
        return {READABLE.get(k, k): readable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [readable(v) for v in obj]
    return obj


def gemini_available() -> bool:
    return get_settings().gemini_enabled


def _models() -> list[str]:
    s = get_settings()
    extra = [m.strip() for m in s.gemini_fallback_models.split(",") if m.strip()]
    return [s.gemini_model, *[m for m in extra if m != s.gemini_model]]


def write(question: str, facts: dict, task: str) -> tuple[str, str]:
    """Ask Gemini (through a LangChain chain) to word an answer. Returns (text, model)."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_google_genai import ChatGoogleGenerativeAI

    s = get_settings()
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM),
        ("human", "Question: {question}\n\nFACTS (JSON):\n{facts}\n\nTask: {task}"),
    ])
    last_err = None
    for model in _models():
        llm = ChatGoogleGenerativeAI(model=model, google_api_key=s.gemini_api_key,
                                     timeout=s.gemini_timeout_seconds, max_retries=1)
        chain = prompt | llm | StrOutputParser()
        t0 = time.perf_counter()
        try:
            text = chain.invoke({"question": question, "facts": json.dumps(readable(facts), indent=1, default=str),
                                 "task": task})
            LLM_SECONDS.observe(time.perf_counter() - t0)
            text = (text or "").strip()
            if text:
                return text, model
        except Exception as exc:  # quota, overload, network
            last_err = exc
            log.warning("Gemini model %s failed: %s", model, type(exc).__name__)
    raise RuntimeError(f"Gemini unavailable ({type(last_err).__name__ if last_err else 'empty reply'})")
