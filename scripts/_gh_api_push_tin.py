# -*- coding: utf-8 -*-
# github.com 被墙时的绕行部署（tin-insight 版）：gh 走 api.github.com Contents API 直推 index.html。
# 推送内容 = 当前工作区 index.html（CRLF 字节，与远端历史 blob 风格一致）。
import base64
import json
import subprocess
import sys
from pathlib import Path

REPO = "wangziquan-del/tin-insight"
BRANCH = "main"
BASE = Path(__file__).parent.parent  # 脚本在 scripts/ 下，index.html 在仓库根
TARGET = "index.html"
MSG = "chore: 构建日期更新至 2026-08-06 + ITA 2026Q1 中国消费/全球产量/供需平衡三行（API 直推）"


def gh(args, input_data=None):
    return subprocess.run(["gh", "api"] + args, input=input_data,
                          capture_output=True, text=True, encoding="utf-8")


r = gh([f"repos/{REPO}/contents/{TARGET}?ref={BRANCH}"])
if r.returncode != 0:
    print("取远端 sha 失败:", r.stderr[:300]); sys.exit(1)
sha = json.loads(r.stdout)["sha"]
print("远端 sha:", sha[:10])

content = base64.b64encode((BASE / TARGET).read_bytes()).decode()
msg = {"message": MSG, "content": content, "branch": BRANCH, "sha": sha}
r = gh(["-X", "PUT", f"repos/{REPO}/contents/{TARGET}", "--input", "-"],
       input_data=json.dumps(msg))
if r.returncode != 0:
    print("FAIL:", r.stderr[:500]); sys.exit(1)
commit = json.loads(r.stdout)["commit"]["sha"]
print("OK ->", commit)
