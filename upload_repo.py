"""把 elder-guide-github 目录发布到 GitHub（走 REST API，不依赖 git push）。

用法：
    set GITHUB_TOKEN=...   （或用 git credential fill 传入）
    python upload_repo.py
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = pathlib.Path(__file__).parent
REPO = "elder-guide"
DESC = "适老化手机引导图生成器：截图 → 压暗+高亮+箭头引导图，iOS/Android 通用（Python + Pillow + Dify）"
SKIP = {".git", "__pycache__", "logs", ".venv"}
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()


def call(method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "elder-guide-uploader")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"message": raw[:300]}


def main():
    if not TOKEN:
        print("缺少 GITHUB_TOKEN")
        sys.exit(1)

    status, me = call("GET", "/user")
    if status != 200:
        print("token 无效:", status, me)
        sys.exit(1)
    owner = me["login"]
    print("owner:", owner)

    status, body = call("POST", "/user/repos", {
        "name": REPO,
        "description": DESC,
        "private": False,
        "has_issues": True,
        "has_wiki": False,
        "auto_init": False,
    })
    if status == 201:
        print("repo created:", body["html_url"])
    elif status == 422:
        print("repo already exists, continue")
    else:
        print("create failed:", status, body)
        sys.exit(1)

    files = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP for part in rel.parts):
            continue
        if rel.name in {"dify.json", "app-token.txt"}:
            continue
        files.append((rel.as_posix(), path))

    for rel, path in files:
        content = base64.b64encode(path.read_bytes()).decode()
        status, body = call("PUT", f"/repos/{owner}/{REPO}/contents/{rel}", {
            "message": f"Add {rel}",
            "content": content,
            "branch": "main",
        })
        state = "ok" if status in (200, 201) else f"FAIL {status} {body.get('message')}"
        print(f"{state:>28}  {rel}")

    print("\nrepo:", f"https://github.com/{owner}/{REPO}")


if __name__ == "__main__":
    main()
