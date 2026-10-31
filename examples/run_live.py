#!/usr/bin/env python3
"""Record a live run of the sample case on NEAR AI Cloud into fixtures/run1/.

Needs an API key from https://cloud.near.ai. The key is taken from, in this order:
1. the environment variable NEARAI_API_KEY,
2. a key file you created yourself outside the repository: the path in NEARAI_API_KEY_FILE, or
   nearai-key.txt in your home folder,
3. a prompt. Paste works (right click or Ctrl+V); the input is visible while you paste, then the
   screen is cleared.
This script never writes the key anywhere and never prints it.
Three questions cost a few US cents. The receipts of the run are the replay used by `sealed demo`.

    python examples/run_live.py [--model MODEL] [--out fixtures/run1] [--base-url URL] [--resume]

--resume continues a run that stopped early: the receipts already there are checked and kept, and
only the missing questions are asked.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sealed.nearai import DEFAULT_MODEL, ApiError, NearAI  # noqa: E402
from sealed.pipeline import LeakError, PolicyError, VerificationError, ask  # noqa: E402
from sealed.receipt import verify_chain  # noqa: E402

def _key_file() -> Path:
    custom = os.environ.get("NEARAI_API_KEY_FILE")
    return Path(custom) if custom else Path.home() / "nearai-key.txt"


def _read_key() -> str:
    key = (os.environ.get("NEARAI_API_KEY") or "").strip()
    if key:
        return key
    path = _key_file()
    if path.is_file():
        key = path.read_text(encoding="utf-8", errors="replace").strip().strip('"').strip("'")
        if key:
            print(f"API key read from {path}", flush=True)
            return key
    return _ask_key()


def _ask_key() -> str:
    """Ask for the key in plain text: a hidden prompt (getpass) does not accept pasting on Windows."""
    print("NEAR AI Cloud API key: paste it here (right click or Ctrl+V) and press Enter.")
    print("The text is visible while you paste; the screen is cleared right after.")
    try:
        key = input("> ").strip().strip('"').strip("'")
    except EOFError:
        return ""
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")
    return key


QUESTIONS = [
    "Welche Mängel wurden gemeldet, wann, und wie hat die Vermieterin reagiert?",
    "Welche Fristen und Termine nennen die Mängelrüge, die Antwort der Vermieterin, der Augenschein und das Schlichtungsgesuch, und was ist noch offen?",
    "Welche Befunde aus dem Augenschein sprechen für eine Herabsetzung des Mietzinses? Nenne höchstens drei Punkte mit Quelle.",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", default=str(ROOT / "fixtures" / "run1"))
    parser.add_argument("--base-url")
    parser.add_argument("--resume", action="store_true", help="continue a run that stopped early")
    args = parser.parse_args(argv)

    out = Path(args.out)
    start = 0
    if out.exists() and any(out.iterdir()):
        if not args.resume:
            print(f"{out} already holds a run; move it away first, or use --resume.", file=sys.stderr)
            return 2
        existing = verify_chain(out)
        if not existing["ok"]:
            print(f"the receipts in {out} do not verify: {existing['problems']}", file=sys.stderr)
            return 5
        start = existing["count"]
        if start >= len(QUESTIONS):
            print(f"{out} already holds all {len(QUESTIONS)} receipts; nothing to resume.", file=sys.stderr)
            return 2
        print(f"resuming after {start} verified receipt(s)", flush=True)
    key = _read_key()
    if not key:
        print("no API key given", file=sys.stderr)
        return 2
    api = NearAI(key, base_url=args.base_url)
    work = Path(tempfile.mkdtemp(prefix="sealed-live-"))
    try:
        for number, question in enumerate(QUESTIONS[start:], start=start + 1):
            print(f"[{number}/{len(QUESTIONS)}] {question}", flush=True)
            result = ask(
                question,
                ROOT / "examples" / "dossier",
                ROOT / "examples" / "entities.json",
                model=args.model,
                receipts_dir=out,
                db_path=work / "index.db",
                api=api,
                k=6,
                max_tokens=12000,
            )
            print(f"    signature OK, attestation level: {result['attestation_level']}", flush=True)
    except (LeakError, PolicyError, VerificationError, ApiError, ValueError, OSError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 4
    chain = verify_chain(out)
    print(f"chain: {'OK' if chain['ok'] else 'FAIL'} ({chain['count']} receipts) in {out}")
    return 0 if chain["ok"] else 5


if __name__ == "__main__":
    sys.exit(main())
