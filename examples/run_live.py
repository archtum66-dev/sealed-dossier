#!/usr/bin/env python3
"""Record a live run of the sample case on NEAR AI Cloud into fixtures/run1/.

Needs an API key from https://cloud.near.ai. The key is read from the environment variable
NEARAI_API_KEY; if it is not set, you are asked for it (input hidden). It is kept in memory only.
Three questions cost a few US cents. The receipts of the run are the replay used by `sealed demo`.

    python examples/run_live.py [--model MODEL] [--out fixtures/run1] [--base-url URL]
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sealed.nearai import DEFAULT_MODEL, ApiError, NearAI  # noqa: E402
from sealed.pipeline import LeakError, PolicyError, VerificationError, ask  # noqa: E402
from sealed.receipt import verify_chain  # noqa: E402

QUESTIONS = [
    "Welche Mängel wurden gemeldet, wann, und wie hat die Vermieterin reagiert?",
    "Welche Fristen und Daten ergeben sich aus dem Dossier, und welche Punkte sind noch offen?",
    "Formuliere drei Sätze zur Begründung der Mietzinsherabsetzung, nur gestützt auf das Dossier.",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", default=str(ROOT / "fixtures" / "run1"))
    parser.add_argument("--base-url")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"{out} already holds a run; move it away first.", file=sys.stderr)
        return 2
    key = os.environ.get("NEARAI_API_KEY") or getpass.getpass("NEAR AI Cloud API key (hidden): ")
    if not key:
        print("no API key given", file=sys.stderr)
        return 2
    api = NearAI(key, base_url=args.base_url)
    work = Path(tempfile.mkdtemp(prefix="sealed-live-"))
    try:
        for number, question in enumerate(QUESTIONS, start=1):
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
