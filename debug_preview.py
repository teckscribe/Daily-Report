"""Debug: inspect WhatsApp Web attach menu. Does NOT send anything."""
import sys
import time
from playwright.sync_api import sync_playwright
from config import DATA_DIR, OUTPUT_DIR

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(DATA_DIR / "whatsapp_session"),
        headless=False,
        channel="chrome" if sys.platform == "win32" else None,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.new_page()
    page.goto("https://web.whatsapp.com/send?phone=919633889430", timeout=90000)
    page.wait_for_selector("footer", timeout=90000)
    time.sleep(4)

    print("FOOTER BUTTONS:")
    for b in page.locator("footer button, footer [role='button']").all():
        try:
            print("  ", b.get_attribute("aria-label"), b.get_attribute("title"), b.is_visible())
        except Exception:
            pass
    print("ALL FILE INPUTS (before):")
    for i in page.locator("input[type='file']").all():
        print("  accept=", i.get_attribute("accept"), "multiple=", i.get_attribute("multiple"))

    btn = page.locator("footer button[aria-label='Attach'], footer [title='Attach']").first
    print("attach count:", btn.count())
    if btn.count() == 0:
        btn = page.locator("footer button").first
    btn.click()
    time.sleep(2)
    page.screenshot(path=str(OUTPUT_DIR / "dbg_menu.png"))
    print("ALL FILE INPUTS (menu open):")
    for i in page.locator("input[type='file']").all():
        try:
            parent_txt = i.evaluate("e => (e.closest('li,[role=menuitem],[role=button],div')||e.parentElement).innerText")
        except Exception:
            parent_txt = "?"
        print("  accept=", i.get_attribute("accept"), "| parent:", (parent_txt or "")[:60].replace("\n", " "))
    for m in page.locator("[role='menuitem'], li[role], [role='application'] li").all():
        try:
            print("MENU:", m.inner_text()[:40].replace("\n", " "), m.is_visible())
        except Exception:
            pass
    page.keyboard.press("Escape")
    time.sleep(1)
    ctx.close()
