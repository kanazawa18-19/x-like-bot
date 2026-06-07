#!/usr/bin/env python3
"""X.com に自動ログインして cookie を取得・保存する

必要な環境変数:
  X_USERNAME_KNZW / X_PASSWORD_KNZW / X_TOTP_KNZW (任意)
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

try:
    import pyotp
    _HAS_PYOTP = True
except ImportError:
    _HAS_PYOTP = False

ACCOUNTS = [
    {
        "account":      "knzw",
        "username_env": "X_USERNAME_KNZW",
        "password_env": "X_PASSWORD_KNZW",
        "totp_env":     "X_TOTP_KNZW",
        "out":          "cookies_knzw.json",
    },
]


async def login(page: Page, username: str, password: str, totp_secret: str | None) -> None:
    await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(2_000)

    await page.get_by_label("Phone, email, or username").fill(username)
    await page.get_by_role("button", name="Next").click()
    await page.wait_for_timeout(2_000)

    confirm = page.get_by_label("Enter your phone number or username")
    if await confirm.count() > 0:
        await confirm.fill(username)
        await page.get_by_role("button", name="Next").click()
        await page.wait_for_timeout(2_000)

    await page.get_by_label("Password", exact=True).fill(password)
    await page.get_by_role("button", name="Log in").click()
    await page.wait_for_timeout(3_000)

    otp_input = None
    for sel in [
        "input[autocomplete='one-time-code']",
        "[data-testid='ocfEnterTextTextInput']",
    ]:
        el = page.locator(sel).first
        if await el.count() > 0:
            otp_input = el
            break

    if otp_input is not None:
        if not totp_secret:
            raise RuntimeError(
                "2FA が要求されましたが X_TOTP_KNZW が未設定です。\n"
                "  - 認証アプリ（TOTP）を使っている場合: 秘密鍵を Secrets に設定してください。\n"
                "  - SMS 認証の場合: 認証アプリ（TOTP）に切り替えを推奨します。"
            )
        if not _HAS_PYOTP:
            raise RuntimeError("pyotp が未インストールです: pip install pyotp")
        code = pyotp.TOTP(totp_secret).now()
        await otp_input.fill(code)
        await page.get_by_role("button", name="Next").click()
        await page.wait_for_timeout(2_000)

    if "flow/login" in page.url or page.url.endswith("/login"):
        raise RuntimeError(f"ログイン失敗 (URL: {page.url})")


async def refresh_account(acc: dict) -> None:
    name     = acc["account"]
    username = os.environ.get(acc["username_env"], "").strip()
    password = os.environ.get(acc["password_env"], "").strip()
    totp     = os.environ.get(acc["totp_env"], "").strip() or None

    if not username or not password:
        raise RuntimeError(f"環境変数 {acc['username_env']} / {acc['password_env']} が未設定です")

    print(f"[{name}] ログイン中 ({username}) ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="ja-JP")
        page    = await context.new_page()

        await login(page, username, password, totp)

        all_cookies = await context.cookies()
        target = [
            c for c in all_cookies
            if c["name"] in ("auth_token", "ct0") and "x.com" in c.get("domain", "")
        ]

        if not any(c["name"] == "auth_token" for c in target):
            raise RuntimeError("auth_token が取得できませんでした")

        storage = {
            "cookies": [
                {
                    "name":     c["name"],
                    "value":    c["value"],
                    "domain":   c["domain"],
                    "path":     c.get("path", "/"),
                    "expires":  c.get("expires", -1),
                    "httpOnly": c.get("httpOnly", False),
                    "secure":   c.get("secure", True),
                    "sameSite": c.get("sameSite", "None"),
                }
                for c in target
            ],
            "origins": [],
        }

        Path(acc["out"]).write_text(json.dumps(storage, ensure_ascii=False, indent=2))
        print(f"[{name}] cookie 保存完了: {acc['out']} ({len(target)} 件)")
        await browser.close()


async def main() -> None:
    failed = []
    for acc in ACCOUNTS:
        try:
            await refresh_account(acc)
        except Exception as e:
            print(f"[{acc['account']}] エラー: {e}", file=sys.stderr)
            failed.append(acc["account"])

    if failed:
        sys.exit(1)

    print("cookie 更新完了")


if __name__ == "__main__":
    asyncio.run(main())
