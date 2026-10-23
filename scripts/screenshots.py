"""Capture app screenshots with headless Chromium (Playwright).

Start the app first:   streamlit run app.py --server.port 8517
Then:                  python scripts/screenshots.py http://localhost:8517
Needs:                 pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MEDIA = DOCS / "media"


def wait_idle(page, ms=1500):
    page.wait_for_load_state("networkidle")
    try:
        page.wait_for_selector("[data-testid='stStatusWidget']", state="detached", timeout=60000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def main(url: str = "http://localhost:8517"):
    DOCS.mkdir(exist_ok=True)
    MEDIA.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, color_scheme="dark")
        page.goto(url)
        page.wait_for_selector("text=Task list", timeout=60000)
        wait_idle(page, 2500)
        page.screenshot(path=str(DOCS / "app_input.png"))
        page.screenshot(path=str(MEDIA / "04_app_input_1920x1080.png"))

        page.get_by_role("button", name="Balance the line").click()
        page.wait_for_selector("text=Method comparison", timeout=120000)
        wait_idle(page, 3000)
        main_area = page.locator("section[data-testid='stMain'], section.main").first

        def shot_section(text: str, path: Path, offset: int = -90):
            el = page.get_by_text(text, exact=True).first
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(600)
            # scroll so the heading sits at the top of the viewport
            page.evaluate(
                """([t, off]) => {
                    const h = [...document.querySelectorAll('h1,h2,h3')].find(e => e.innerText.trim() === t);
                    if (!h) return;
                    let sc = h.closest('[data-testid="stMain"]') || document.scrollingElement;
                    const top = h.getBoundingClientRect().top;
                    (sc.scrollBy ? sc : window).scrollBy(0, top + off);
                    window.scrollBy(0, top + off);
                }""",
                [text, offset],
            )
            page.wait_for_timeout(1200)
            page.screenshot(path=str(path))

        shot_section("Method comparison", DOCS / "app_comparison.png")
        shot_section("Balanced line", DOCS / "app_balanced.png")
        page.screenshot(path=str(MEDIA / "05_app_before_after_1920x1080.png"))
        page.get_by_role("tab", name="Station Gantt").click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(DOCS / "app_gantt.png"))
        _ = main_area
        browser.close()
    print("screenshots written to", DOCS)


if __name__ == "__main__":
    main(*sys.argv[1:])
