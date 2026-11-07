"""Build web/index.html: an offline replay of the recorded run in fixtures/run1.

The page embeds the exact bytes of every receipt file (base64) and re-checks them in the
browser: both SHA-256 hashes, the EIP-191 signature (signer recovered with a small
secp256k1 port of sealed/secp256k1.py), the receipt hash and the hash chain.

    python web/build.py           write web/index.html
    python web/build.py --check   exit 1 if web/index.html is not a fresh build

Standard library only.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "fixtures" / "run1"
TEMPLATE = ROOT / "web" / "index.template.html"
OUT = ROOT / "web" / "index.html"
FILES = ("receipt.json", "request.json", "response.txt", "signature.json", "answer.md")
MARKER = "/*__RUN_DATA__*/null"


def build() -> str:
    receipts = []
    for rdir in sorted(p for p in RUN.iterdir() if p.is_dir() and p.name.isdigit()):
        files = {name: base64.b64encode((rdir / name).read_bytes()).decode("ascii") for name in FILES}
        receipts.append({"id": rdir.name, "files": files})
    data = json.dumps({"run": "fixtures/run1", "receipts": receipts}, separators=(",", ":"))
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(MARKER) != 1:
        raise SystemExit("template marker missing")
    return template.replace(MARKER, data)


def main() -> int:
    page = build()
    if "--check" in sys.argv[1:]:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != page:
            print("web/index.html is NOT a fresh build: run python web/build.py")
            return 1
        print("web/index.html matches a fresh build of fixtures/run1")
        return 0
    OUT.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(page.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
