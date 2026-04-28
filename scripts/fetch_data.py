#!/usr/bin/env python3
"""
Chatwork の指定ルームからメッセージを取得し、URL+カテゴリ+OGP情報を
data.json に書き出すスクリプト。GitHub Actions から定期実行される。
"""

import os
import re
import json
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

CHATWORK_API_TOKEN = os.environ["CHATWORK_API_TOKEN"]
CHATWORK_ROOM_ID = os.environ["CHATWORK_ROOM_ID"]

VALID_CATEGORIES = {"Architecture", "Products", "Others"}
URL_PATTERN = re.compile(r'https?://[^\s\[\]<>\"]+')

DATA_FILE = "data.json"
OGP_CACHE_FILE = "ogp_cache.json"


def get_messages():
    headers = {"X-ChatWorkToken": CHATWORK_API_TOKEN}
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    resp = requests.get(url, headers=headers, params={"force": 1}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_entries(messages):
    entries = {}

    for msg in sorted(messages, key=lambda m: m.get("send_time", 0)):
        body = msg.get("body", "")
        lines = body.splitlines()

        for i, line in enumerate(lines):
            for url in URL_PATTERN.findall(line):
                category = "未記入"
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line in VALID_CATEGORIES:
                        category = next_line
                entries[url] = {
                    "url": url,
                    "category": category,
                    "send_time": msg.get("send_time", 0),
                }

    return list(entries.values())


def fetch_ogp(url, cache):
    if url in cache:
        return cache[url]

    ogp = {"title": url, "description": "", "image": ""}
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; OGPFetcher/1.0)"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for prop, key in [
            ("og:title", "title"),
            ("og:description", "description"),
            ("og:image", "image"),
        ]:
            tag = soup.find("meta", property=prop)
            if tag and tag.get("content"):
                ogp[key] = tag["content"].strip()

        if not ogp["title"] or ogp["title"] == url:
            title_tag = soup.find("title")
            if title_tag:
                ogp["title"] = title_tag.text.strip()

    except Exception as e:
        print(f"  OGP取得失敗: {url} — {e}")

    # OGP画像がない場合はmicrolinkでスクリーンショットを取得
    if not ogp["image"]:
        try:
            ml_resp = requests.get(
                "https://api.microlink.io",
                params={"url": url, "screenshot": "true"},
                timeout=15,
            )
            ml_data = ml_resp.json()
            if ml_data.get("status") == "success":
                screenshot = ml_data.get("data", {}).get("screenshot", {})
                if screenshot.get("url"):
                    ogp["image"] = screenshot["url"]
                    print(f"  スクリーンショット取得: {url}")
        except Exception as e:
            print(f"  スクリーンショット取得失敗: {url} — {e}")

    cache[url] = ogp
    return ogp


def main():
    try:
        with open(OGP_CACHE_FILE, encoding="utf-8") as f:
            ogp_cache = json.load(f)
    except FileNotFoundError:
        ogp_cache = {}

    print("Chatwork からメッセージ取得中...")
    messages = get_messages()
    print(f"  {len(messages)} 件のメッセージを取得")

    entries = extract_entries(messages)
    print(f"  {len(entries)} 件のユニークURLを抽出")

    print("OGP情報を取得中...")
    for entry in entries:
        url = entry["url"]
        if url not in ogp_cache:
            print(f"  取得: {url}")
        entry["ogp"] = fetch_ogp(url, ogp_cache)

    with open(OGP_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(ogp_cache, f, ensure_ascii=False, indent=2)

    output = {
        "urls": entries,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"完了: {len(entries)} 件を {DATA_FILE} に保存しました")


if __name__ == "__main__":
    main()
