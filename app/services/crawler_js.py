from playwright.async_api import async_playwright
from typing import Optional


async def crawl_with_playwright(url: str) -> Optional[str]:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until='networkidle', timeout=30000)
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        print(f"Playwright crawl failed for {url}: {e}")
        return None
