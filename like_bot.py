#!/usr/bin/env python3
"""X.com いいね巡回ボット（Playwright + セッションクッキー）"""

import asyncio
import os
import random
import sys
from pathlib import Path
from urllib.parse import quote

import yaml
from playwright.async_api import async_playwright, BrowserContext, Page


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


async def verify_login(page: Page, account: str) -> bool:
    await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3_000)
    if "/login" in page.url:
        raise RuntimeError(f"[{account}] セッションが切れています。cookies を更新してください。")
    return True


async def like_visible_posts(page: Page, max_likes: int, delay_range: tuple, label: str) -> int:
    liked = 0
    processed: set[str] = set()
    no_new_streak = 0

    while liked < max_likes:
        buttons = await page.query_selector_all('[data-testid="like"]')
        new_buttons = []
        for btn in buttons:
            box = await btn.bounding_box()
            if box:
                key = f"{box['x']:.0f},{box['y']:.0f}"
                if key not in processed:
                    processed.add(key)
                    new_buttons.append(btn)

        if not new_buttons:
            no_new_streak += 1
            if no_new_streak >= 3:
                break
            prev_h = await page.evaluate("document.documentElement.scrollHeight")
            await page.evaluate("window.scrollBy(0, 700)")
            await page.wait_for_timeout(2_500)
            new_h = await page.evaluate("document.documentElement.scrollHeight")
            if new_h == prev_h:
                break
            continue

        no_new_streak = 0
        for btn in new_buttons:
            if liked >= max_likes:
                break
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                liked += 1
                await asyncio.sleep(random.uniform(*delay_range))
            except Exception:
                pass

        await page.evaluate("window.scrollBy(0, 500)")
        await page.wait_for_timeout(2_000)

    print(f"  [{label}] {liked} 件いいね")
    return liked


async def like_from_search(page: Page, keyword: str, max_likes: int, delay_range: tuple) -> int:
    url = f"https://x.com/search?q={quote(keyword)}&f=live"
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(4_000)
    return await like_visible_posts(page, max_likes, delay_range, f"検索: {keyword}")


async def like_from_user_timeline(page: Page, username: str, max_likes: int, delay_range: tuple) -> int:
    url = f"https://x.com/{username}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(4_000)
    return await like_visible_posts(page, max_likes, delay_range, f"TL: @{username}")


async def run_account(cookies_path: Path, config: dict, account: str) -> int:
    max_likes   = config.get("max_likes_per_run", 20)
    keywords    = config.get("keywords", [])
    target_users = config.get("target_users", [])
    delay_range = (config.get("delay_min", 3), config.get("delay_max", 8))

    sources = [("keyword", k) for k in keywords] + [("user", u) for u in target_users]
    likes_per_source = max(1, max_likes // len(sources)) if sources else 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context: BrowserContext = await browser.new_context(
            storage_state=str(cookies_path),
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        await verify_login(page, account)
        print(f"[{account}] ログイン確認OK")

        total = 0
        for source_type, source in sources:
            try:
                if source_type == "keyword":
                    total += await like_from_search(page, source, likes_per_source, delay_range)
                else:
                    total += await like_from_user_timeline(page, source, likes_per_source, delay_range)
            except Exception as e:
                print(f"  ERROR [{source}]: {e}", file=sys.stderr)
            await asyncio.sleep(random.uniform(8, 15))

        await browser.close()
    return total


async def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "config/knzw.yml")
    config = load_config(config_path)
    account = config.get("account", "knzw")

    cookies_path = Path(f"cookies_{account}.json")
    if not cookies_path.exists():
        print(f"ERROR: {cookies_path} が見つかりません。", file=sys.stderr)
        sys.exit(1)

    total = await run_account(cookies_path, config, account)
    print(f"[{account}] 完了: 合計 {total} 件いいね")


if __name__ == "__main__":
    asyncio.run(main())
