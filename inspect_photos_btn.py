from playwright.sync_api import sync_playwright
import time
from config import DATA_DIR

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(DATA_DIR / "whatsapp_session"),
        headless=False,
        channel="chrome"
    )
    page = ctx.new_page()
    page.goto("https://web.whatsapp.com/send?phone=919633889430")
    page.wait_for_selector("footer", timeout=60000)
    time.sleep(3)
    
    # Click Attach
    attach_btn = page.locator("footer button[aria-label='Attach']").first
    print("Attach button count:", attach_btn.count())
    attach_btn.click()
    time.sleep(2)
    
    # Print all menuitems
    items = page.locator("li, [role='menuitem'], button").all()
    print("Total items:", len(items))
    for it in items:
        try:
            txt = it.inner_text().strip().replace("\n", " ")
            if "Photos & videos" in txt:
                print("Found Photos & videos!")
                print("  Tag:", it.evaluate("e => e.tagName"))
                print("  Attributes:", it.evaluate("e => ({role: e.getAttribute('role'), 'aria-label': e.getAttribute('aria-label'), class: e.className})"))
                inputs = it.locator("input").all()
                print("  Inputs inside:", len(inputs))
                for inp in inputs:
                    print("    Input accept:", inp.get_attribute("accept"))
        except Exception:
            pass
            
    # Also check all input[type='file'] on the entire page
    print("\nAll input[type='file'] on page:")
    for inp in page.locator("input[type='file']").all():
        try:
            acc = inp.get_attribute("accept")
            par = inp.evaluate("e => e.parentElement.outerHTML")
            print(f"  accept='{acc}' | parent: {par[:100]}")
        except Exception as e:
            print("  error:", e)

    page.keyboard.press("Escape")
    time.sleep(1)
    ctx.close()
