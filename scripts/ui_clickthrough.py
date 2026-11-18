"""Optional UI click-through with Playwright. Visits every page, uses the main controls and
saves a screenshot of each step. Needs the API on :8000 and Vite on :5173 (or the built SPA
served by the API, then pass --base http://127.0.0.1:8000).

    pip install playwright && playwright install chromium
    python scripts/ui_clickthrough.py --out shots
"""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

DEMO = (os.getenv("SEED_DEMO_EMAIL", "demo@example.com"), os.getenv("SEED_DEMO_PASSWORD", "demo12345"))
ADMIN = (os.getenv("SEED_ADMIN_EMAIL", "admin@example.com"), os.getenv("SEED_ADMIN_PASSWORD", "admin12345"))


class Run:
    def __init__(self, page: Page, base: str, out: Path):
        self.page, self.base, self.out, self.n = page, base, out, 0
        self.problems: list[str] = []
        page.on("console", lambda m: m.type == "error" and self.problems.append(f"console: {m.text[:200]}"))
        page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        page.on("response", lambda r: r.status >= 500 and self.problems.append(f"HTTP {r.status} {r.url}"))

    def shot(self, name: str, full: bool = True):
        self.n += 1
        self.page.wait_for_timeout(1200)
        path = self.out / f"{self.n:02d}_{name}.png"
        self.page.screenshot(path=str(path), full_page=full)
        print("saved", path.name)

    def go(self, path: str):
        self.page.goto(self.base + path)
        self.page.wait_for_load_state("networkidle")

    def login(self, email: str, password: str):
        self.go("/login")
        self.page.evaluate("localStorage.clear()")
        self.go("/login")
        self.page.get_by_label("Email").fill(email)
        self.page.get_by_label("Password").fill(password)
        self.page.get_by_role("button", name="Sign in").click()
        self.page.wait_for_url("**/dashboard")
        self.page.wait_for_load_state("networkidle")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5173")
    ap.add_argument("--out", default="shots")
    ap.add_argument("--channel", default=None, help="e.g. chrome to use an installed Chrome")
    ap.add_argument("--short", action="store_true", help="only the recommendations and planner pages")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(20_000)
        r = Run(page, args.base, out)
        try:
            short_flow(r, page) if args.short else flow(r, page, browser, args, out)
        except Exception:
            page.screenshot(path=str(out / "FAILED.png"), full_page=True)
            raise


def recommendations_step(r, page):
    r.go("/recommendations")
    expect(page.get_by_text("recipes passed your rules")).to_be_visible()
    r.shot("recommendations")
    page.get_by_role("button", name="Like", exact=True).first.click()
    page.wait_for_timeout(500)
    # breakfast filter: only recipes rated as a breakfast, plus a calorie limit
    page.get_by_role("combobox").first.click()
    page.get_by_role("option", name="Breakfast").click()
    page.get_by_placeholder("Any").first.fill("500")
    page.get_by_role("button", name="Apply filters").click()
    expect(page.get_by_text("at most 500 kcal per serving").first).to_be_visible()
    expect(page.get_by_text("meal type: breakfast").first).to_be_visible()
    r.shot("recommendations_filtered")
    page.locator("h3").first.click()
    expect(page.get_by_text("Nutrition per serving")).to_be_visible()
    r.shot("recipe_detail_dialog", full=False)
    page.keyboard.press("Escape")


def planner_step(r, page):
    r.go("/planner")
    page.get_by_role("radio", name="One week").click()
    page.get_by_role("button", name="Generate plan").click()
    expect(page.get_by_text("Plan overview")).to_be_visible(timeout=120_000)
    r.shot("planner_week")
    page.get_by_role("button", name="Swap lunch").first.click()
    expect(page.get_by_text("Swapped lunch")).to_be_visible()
    page.get_by_role("button", name="Save plan").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Viewing saved plan")).to_be_visible()
    page.get_by_role("button", name="Log").first.click()
    expect(page.get_by_text("meals for today")).to_be_visible()
    r.shot("planner_saved")


def short_flow(r, page):
    """Only the recommendations and planner pages, saved under the same numbers as the
    full run (10 to 12 and 14 to 15), for a quick check after a change to either."""
    r.login(*DEMO)
    r.n = 9
    recommendations_step(r, page)
    r.n = 13
    planner_step(r, page)
    print("Problems seen:" if r.problems else "No console errors, page errors or 5xx responses.")
    for x in r.problems:
        print("  " + x)


def flow(r, page, browser, args, out):

    # Public pages and sign up with onboarding
    r.go("/login")
    r.shot("login")
    r.go("/register")
    email = f"newuser{int(time.time())}@example.com"
    page.get_by_label("Full name").fill("Asha Rao")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill("password123")
    r.shot("register")
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url("**/onboarding")
    page.get_by_role("combobox").nth(0).click()
    page.get_by_role("option", name="Female").click()
    inputs = page.locator("input[type=number]")
    inputs.nth(0).fill("27")
    inputs.nth(1).fill("162")
    inputs.nth(2).fill("58")
    page.get_by_role("combobox").nth(1).click()
    page.get_by_role("option", name="Moderate").click()
    page.get_by_role("combobox").nth(2).click()
    page.get_by_role("option", name="Lose").click()
    r.shot("onboarding_1_body")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Vegetarian").click()
    page.get_by_role("button", name="Peanut").click()
    page.get_by_placeholder("e.g. mushroom, coriander").fill("mushroom")
    page.get_by_role("button", name="Add", exact=True).click()
    r.shot("onboarding_2_diet")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Indian").click()
    page.get_by_role("button", name="Thai").click()
    r.shot("onboarding_3_preferences")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Estimate targets").click()
    expect(page.get_by_text("Mifflin-St Jeor: BMR")).to_be_visible()
    r.shot("onboarding_4_targets")
    page.get_by_role("button", name="Finish setup").click()
    page.wait_for_url("**/dashboard")
    page.wait_for_load_state("networkidle")
    r.shot("new_user_dashboard_empty")

    # Demo user: all user pages
    r.login(*DEMO)
    r.shot("dashboard")
    page.get_by_role("radio", name="30d").click()
    page.wait_for_load_state("networkidle")
    r.shot("dashboard_30d")

    recommendations_step(r, page)

    r.go("/assistant")
    box = page.get_by_placeholder("e.g. How much protein is in 200 g of chickpeas?")
    for q in ["How many calories are in 150 g of cooked rice?",
              "Suggest a high protein dinner under 600 kcal",
              "How much protein do I have left today?"]:
        box.fill(q)
        box.press("Enter")
        expect(page.get_by_text("Looking up the database")).to_be_hidden(timeout=120_000)
    page.get_by_text("How this was answered").last.click()
    r.shot("assistant", full=False)

    planner_step(r, page)

    r.go("/explorer")
    page.get_by_placeholder("Search foods").fill("chickpea")
    page.wait_for_timeout(800)
    page.wait_for_load_state("networkidle")
    r.shot("explorer_foods")
    page.get_by_role("button", name="Add to compare").nth(0).click()
    page.get_by_role("button", name="Add to compare").nth(1).click()
    page.locator("tbody tr").first.click()
    expect(page.get_by_role("dialog").get_by_text("Per 100 g", exact=True)).to_be_visible()
    r.shot("food_detail", full=False)
    page.keyboard.press("Escape")
    page.get_by_role("tab", name="Recipes").click()
    page.wait_for_load_state("networkidle")
    r.shot("explorer_recipes")
    page.get_by_role("button", name="Compare", exact=True).first.click()
    page.get_by_role("button", name="Compare 3").click()
    expect(page.get_by_text("Side by side")).to_be_visible()
    page.wait_for_timeout(800)
    r.shot("explorer_compare", full=False)
    page.keyboard.press("Escape")
    page.get_by_role("tab", name="Smart search").click()
    page.get_by_placeholder("Describe it").fill("warm comforting lentil soup")
    page.get_by_role("button", name="Search", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    r.shot("explorer_smart_search")

    r.go("/log")
    page.get_by_role("button", name="Add entry").first.click()
    page.get_by_placeholder("Search a food or recipe").fill("banana")
    page.locator("[role=dialog] button:has-text('Banana')").first.click()
    page.get_by_role("button", name="Add entry").last.click()
    expect(page.get_by_text("Added to your log")).to_be_visible()
    page.wait_for_load_state("networkidle")
    r.shot("nutrition_log")

    r.go("/history")
    r.shot("history_activity")
    for tab in ["Taste profile", "Recommendations", "Conversations", "Logged days", "Profile changes"]:
        page.get_by_role("tab", name=tab).click()
        page.wait_for_load_state("networkidle")
        r.shot("history_" + tab.lower().replace(" ", "_"))

    r.go("/settings")
    r.shot("settings")
    page.get_by_role("button", name="Save changes").first.click()
    expect(page.get_by_text("Settings saved")).to_be_visible()

    # Admin
    r.login(*ADMIN)
    r.go("/admin")
    r.shot("admin_overview")
    r.go("/admin/datasets")
    tmp = Path(tempfile.mkdtemp()) / "sample_foods.csv"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Food Name", "Category", "Energy (kcal)", "Protein (g)", "Carbohydrate (g)", "Total Fat (g)", "Fibre (g)"])
        w.writerow(["Sprouted moong salad", "Salads", 110, 7.5, 16, 1.2, 4.1])
        w.writerow(["Roasted makhana", "Snacks", 350, 9.7, 77, 0.1, "NA"])
        w.writerow(["Curd rice", "Rice dishes", 140, 3.9, 22, 3.8, ""])
    page.locator("input[type=file]").set_input_files(str(tmp))
    page.get_by_placeholder("Display name (optional)").fill("UI sample foods")
    page.get_by_role("button", name="Upload", exact=True).click()
    expect(page.get_by_text("Uploaded.")).to_be_visible()
    row = page.locator("tr", has_text="UI sample foods").first
    row.get_by_role("button", name="Clean & profile").click()
    expect(row.get_by_text("Cleaned")).to_be_visible(timeout=120_000)
    row.get_by_role("button", name="Import foods").click()
    expect(page.get_by_text("Imported:").first).to_be_visible(timeout=120_000)
    page.wait_for_timeout(1500)
    r.shot("admin_datasets_jobs")
    row.get_by_role("button", name="UI sample foods").click()
    r.shot("admin_dataset_profile", full=False)
    page.keyboard.press("Escape")
    r.go("/admin/models")
    r.shot("admin_models_ranking")
    for tab in ["Cold start & rules", "Tuning & reranker", "MLflow runs", "Data & index"]:
        page.get_by_role("tab", name=tab).click()
        page.wait_for_timeout(600)
        r.shot("admin_models_" + tab.split()[0].lower())

    # Mobile layout
    mob = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    mp = mob.new_page()
    mr = Run(mp, args.base, out)
    mr.n = r.n
    mr.login(*DEMO)
    mr.shot("mobile_dashboard", full=False)
    mp.get_by_role("button", name="Open menu").click()
    mr.shot("mobile_menu", full=False)
    problems = r.problems + mr.problems
    browser.close()
    print(f"{mr.n} screenshots in {out}")
    if problems:
        print("Problems seen:")
        for x in problems:
            print(" ", x)
    else:
        print("No console errors, page errors or 5xx responses.")

if __name__ == "__main__":
    main()
