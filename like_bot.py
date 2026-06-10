#!/usr/bin/env python3
"""X.com いいね巡回ボット（Playwright + セッションクッキー）"""

import asyncio
import base64
import os
import random
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml
from nacl import encoding, public as nacl_public
from playwright.async_api import async_playwright, BrowserContext, Page


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


async def human_delay(base_range: tuple) -> None:
    r = random.random()
    if r < 0.05:
        # 5%: ふと手が止まる（2〜4分）
        wait = random.uniform(120, 240)
        print(f"    [休憩 {wait:.0f}秒]")
    elif r < 0.15:
        # 10%: じっくり読む（1〜2分）
        wait = random.uniform(60, 120)
    else:
        # 85%: 通常ディレイ（設定値ベース＋ランダムゆらぎ）
        base = random.uniform(*base_range)
        wait = base * random.uniform(0.7, 1.3)
    await asyncio.sleep(wait)


async def human_scroll(page: Page) -> None:
    scroll_amount = random.randint(300, 800)
    await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
    await page.wait_for_timeout(random.randint(1_500, 3_500))

    # 15%の確率で少し読み返す
    if random.random() < 0.15:
        back = random.randint(100, 300)
        await page.evaluate(f"window.scrollBy(0, -{back})")
        await page.wait_for_timeout(random.randint(800, 2_000))


async def like_visible_posts(page: Page, max_likes: int, delay_range: tuple, label: str) -> int:
    liked = 0
    processed: set[str] = set()
    no_new_streak = 0
    skip_rate = 0.25  # 25%はスルー（全部いいねしない）

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
            await human_scroll(page)
            new_h = await page.evaluate("document.documentElement.scrollHeight")
            if new_h == prev_h:
                break
            continue

        no_new_streak = 0
        for btn in new_buttons:
            if liked >= max_likes:
                break

            # ランダムにスルー
            if random.random() < skip_rate:
                continue

            try:
                await btn.scroll_into_view_if_needed()
                # クリック前に少しホバー（人間らしい挙動）
                box = await btn.bounding_box()
                if box:
                    await page.mouse.move(
                        box["x"] + box["width"] / 2 + random.uniform(-4, 4),
                        box["y"] + box["height"] / 2 + random.uniform(-4, 4),
                    )
                    await page.wait_for_timeout(random.randint(200, 900))
                await btn.click()
                liked += 1
                await human_delay(delay_range)
            except Exception:
                pass

        await human_scroll(page)

    print(f"  [{label}] {liked} 件いいね")
    return liked


async def like_from_search(page: Page, keyword: str, max_likes: int, delay_range: tuple) -> int:
    url = f"https://x.com/search?q={quote(keyword)}&f=live"
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(random.randint(3_000, 6_000))
    return await like_visible_posts(page, max_likes, delay_range, f"検索: {keyword}")


async def like_from_user_timeline(page: Page, username: str, max_likes: int, delay_range: tuple) -> int:
    url = f"https://x.com/{username}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(random.randint(3_000, 6_000))
    return await like_visible_posts(page, max_likes, delay_range, f"TL: @{username}")


async def run_account(cookies_path: Path, config: dict, account: str) -> int:
    max_likes    = config.get("max_likes_per_run", 20)
    keywords     = config.get("keywords", [])
    target_users = config.get("target_users", [])
    delay_range  = (config.get("delay_min", 40), config.get("delay_max", 70))

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

        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(3_000)
        if "/login" in page.url:
            raise RuntimeError(f"[{account}] セッションが切れています。cookies を更新してください。")
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
            # ソース間も人間らしい間隔
            await asyncio.sleep(random.uniform(15, 40))

        # セッション終了前にクッキーを保存
        await context.storage_state(path=str(cookies_path))
        await browser.close()
    return total


async def update_github_secret(cookies_path: Path, secret_name: str) -> None:
    token = os.environ.get("GH_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
            r = await client.get(
                f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
                headers=headers, timeout=15
            )
            r.raise_for_status()
            kd = r.json()
            pub = nacl_public.PublicKey(kd["key"].encode(), encoding.Base64Encoder)
            encrypted = base64.b64encode(nacl_public.SealedBox(pub).encrypt(cookies_path.read_text(encoding="utf-8").encode("utf-8"))).decode()
            await client.put(
                f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}",
                headers=headers,
                json={"encrypted_value": encrypted, "key_id": kd["key_id"]},
                timeout=15
            )
        print(f"GitHub Secret {secret_name} を自動更新しました")
    except Exception as e:
        print(f"Secret 自動更新失敗（続行）: {e}", file=sys.stderr)


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
    await update_github_secret(cookies_path, f"X_COOKIES_{account.upper()}")


if __name__ == "__main__":
    asyncio.run(main())
