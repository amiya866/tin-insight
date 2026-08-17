import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (ROOT / "index.html", ROOT / "quotes.json")
# The public page may name verified content platforms. Keep only internal or
# ambiguous provider labels out of the published snapshot.
FORBIDDEN = ("zhiji", "知几", "智己")


def main() -> None:
    failures = []
    for path in PUBLIC_FILES:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for term in FORBIDDEN:
            if term.lower() in lowered:
                failures.append(f"{path.name}: contains forbidden public label {term!r}")

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const DATA=(\{.*\});\s*const STATIC_HOST=", html, re.S)
    if not match:
        failures.append("index.html: embedded DATA object not found")
    else:
        json.loads(match.group(1))

    json.loads((ROOT / "quotes.json").read_text(encoding="utf-8"))

    if failures:
        raise SystemExit("\n".join(failures))
    print("public labels and embedded JSON: ok")


if __name__ == "__main__":
    main()
