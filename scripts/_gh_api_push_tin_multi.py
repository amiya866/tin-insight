#!/usr/bin/env python3
"""Push several site files to wangziquan-del/tin-insight via gh Contents API.

github.com is blocked from this machine; api.github.com works, so we bypass
git push with per-file PUTs. Each PUT creates a commit with the same message.
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

REPO = "wangziquan-del/tin-insight"
BRANCH = "main"
BASE = Path(__file__).resolve().parent.parent
FILES = [
    "index.html",
    "social.json",
    "scripts/build_social_snapshot.py",
    "scripts/_gh_api_push_tin_multi.py",
    ".github/workflows/pages.yml",
]
MSG = "feat: 市场情绪板块 social.json 静态回退层——Worker 不可达时前端自动加载 CI 快照（抖音沪锡缓存）"


def gh(args, input_data=None):
    return subprocess.run(
        ["gh", "api"] + args, input=input_data,
        capture_output=True, text=True, encoding="utf-8",
    )


def remote_sha(path: str) -> str | None:
    result = gh([f"repos/{REPO}/contents/{path}?ref={BRANCH}"])
    if result.returncode != 0:
        if "Not Found" in result.stderr:
            return None
        print(f"get sha failed {path}:", result.stderr[:300])
        sys.exit(1)
    return json.loads(result.stdout)["sha"]


def main() -> None:
    for path in FILES:
        local = BASE / path
        if not local.exists():
            print("skip missing:", path)
            continue
        body = {
            "message": MSG,
            "content": base64.b64encode(local.read_bytes()).decode(),
            "branch": BRANCH,
        }
        sha = remote_sha(path)
        if sha:
            body["sha"] = sha
        result = gh(
            ["-X", "PUT", f"repos/{REPO}/contents/{path}", "--input", "-"],
            input_data=json.dumps(body),
        )
        if result.returncode != 0:
            print(f"FAIL {path}:", result.stderr[:500])
            sys.exit(1)
        commit = json.loads(result.stdout)["commit"]["sha"]
        print("OK", path, "->", commit[:10])


if __name__ == "__main__":
    main()
