#!/usr/bin/env python3
"""X.com のクッキーを cookies.json 形式に変換して保存する

【使い方】
1. Chrome で X.com を開き、いいねさせたいアカウントに切り替える
2. DevTools (F12) → Network タブを開く
3. ページをリロードして x.com へのリクエストをクリック
4. Headers → Request Headers → cookie: の値をコピー
5. 以下を実行してペーストし、Enter × 2:

   python3 save_cookies.py --out cookies_knzw.json

アカウントごとに繰り返す（切り替え → コピー → 実行）。
"""

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="cookies_knzw.json",
                        help="出力ファイル名 (デフォルト: cookies_knzw.json)")
    parser.add_argument("--cookie-string",
                        help="DevTools からコピーしたクッキー文字列（省略時は対話入力）")
    return parser.parse_args()


def read_cookie_string(arg_value: str | None) -> str:
    if arg_value:
        return arg_value

    try:
        clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
        if clip and "auth_token" in clip:
            print(f"クリップボードからクッキーを読み込みました（{len(clip)} 文字）")
            return clip
    except FileNotFoundError:
        pass

    print("DevTools の Request Headers → cookie: の値をペーストして Enter × 2:")
    lines = []
    while True:
        line = input()
        if not line:
            break
        lines.append(line)
    return " ".join(lines)


def parse_cookie_string(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()

    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        if not name:
            continue

        secure    = name in ("auth_token", "ct0", "twid", "des_opt_in")
        http_only = name in ("auth_token",)

        cookies.append({
            "name":     name,
            "value":    value,
            "domain":   ".x.com",
            "path":     "/",
            "expires":  -1,
            "httpOnly": http_only,
            "secure":   secure,
            "sameSite": "None" if secure else "Lax",
        })

    return cookies


def secret_name(out_path: Path) -> str:
    stem = out_path.stem  # e.g. "cookies_knzw"
    suffix = stem.removeprefix("cookies_").upper()
    return f"X_COOKIES_{suffix}"


def main() -> None:
    args = parse_args()
    out_file = Path(args.out)

    raw = read_cookie_string(args.cookie_string)
    if not raw:
        print("クッキー文字列が空です。")
        sys.exit(1)

    cookies = parse_cookie_string(raw)
    if not cookies:
        print("クッキーを解析できませんでした。")
        sys.exit(1)

    auth_names = [c["name"] for c in cookies if "auth" in c["name"].lower()]
    if not auth_names:
        print("⚠️  auth_token が見つかりません。正しい文字列かどうか確認してください。")

    storage_state = {"cookies": cookies, "origins": []}
    out_file.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2))

    encoded = base64.b64encode(out_file.read_bytes()).decode()
    sname = secret_name(out_file)

    print(f"保存: {out_file} ({len(cookies)} 件, 認証: {auth_names})")
    print(f"\n=== GitHub Secret「{sname}」に設定する値 ===")
    print(encoded)
    print("=" * 60)
    print(f"\n（コマンド一発でコピーする場合）")
    print(f"base64 -i {out_file} | tr -d '\\n' | pbcopy")


if __name__ == "__main__":
    main()
