"""Run with a local server on :8000; requires playwright and Chromium."""
from pathlib import Path

from playwright.sync_api import sync_playwright

artifacts = Path(__file__).parents[2] / "qa"
artifacts.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 950})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8000")
    page.locator("#list .item").first.wait_for()
    assert page.locator("#list .item").count() == 60
    print("Library:", page.locator("#libraryCount").inner_text())
    page.locator("#loadMore").click()
    page.wait_for_function("document.querySelectorAll('#list .item').length === 120")
    page.locator("#list .item").first.click()
    page.locator("#capText").wait_for()
    page.screenshot(path=str(artifacts / "desktop.png"), full_page=True)
    page.locator("#btnBatch").click()
    page.locator("#bLimit").fill("2")
    page.locator("#bGo").click()
    page.locator("#bOut a").first.wait_for()
    with page.expect_download() as download:
        page.locator("#bOut a").first.click()
    assert download.value.suggested_filename.endswith(".zip")
    page.keyboard.press("Escape")
    page.locator("#btnBackups").click()
    page.locator("#backupList .dupe").first.wait_for()
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 390, "height": 844})
    with page.expect_response(lambda r: "/api/titles?" in r.url and "q=comedy" in r.url):
        page.locator("#q").fill("comedy")
    page.wait_for_function("document.querySelector('#libraryCount').textContent !== '120 of 599 matching titles'")
    page.locator("#list .item").first.click()
    page.locator("#capText").wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(artifacts / "mobile.png"), full_page=True)
    print("Browser errors:", errors)
    assert not errors
    browser.close()
