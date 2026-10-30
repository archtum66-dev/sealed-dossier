"""Command-line interface for sealed dossier."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sealed.index import Index
from sealed.nearai import DEFAULT_MODEL, ApiError, NearAI
from sealed.pipeline import (
    LeakError,
    PolicyError,
    VerificationError,
    ask,
)
from sealed.receipt import verify_chain, verify_receipt
from sealed.verify import parse_signed_text

_TIER_ORDER = {"confidential": 0, "attested_3p": 1, "incognito": 2, "unknown": 3}


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)


def _cmd_index(args: argparse.Namespace) -> int:
    index = Index(args.db)
    stats = index.build(args.folder)
    print(f"files={stats['files']} chunks={stats['chunks']}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    if args.dry_run:
        result = ask(
            args.question,
            args.folder,
            args.entities,
            model=args.model,
            k=args.k,
            receipts_dir=args.receipts,
            db_path=args.db,
            dry_run=True,
            max_tokens=args.max_tokens,
            rebuild=True,
        )
        print(result["request_body"])
        print("leak check passed", file=sys.stderr)
        for src in result["sources"]:
            print(f"{src['file']} chunk {src['chunk']}", file=sys.stderr)
        return 0
    api_key = os.environ.get("NEARAI_API_KEY")
    if not api_key:
        _print_error("NEARAI_API_KEY is not set")
        return 2
    api = NearAI(api_key, base_url=args.base_url)
    try:
        result = ask(
            args.question,
            args.folder,
            args.entities,
            model=args.model,
            k=args.k,
            receipts_dir=args.receipts,
            db_path=args.db,
            api=api,
            allow_incognito=args.allow_incognito,
            max_tokens=args.max_tokens,
            rebuild=True,
        )
    except LeakError as exc:
        _print_error(str(exc))
        return 3
    except PolicyError as exc:
        _print_error(str(exc))
        return 3
    except VerificationError as exc:
        _print_error(str(exc))
        return 5
    except ApiError as exc:
        _print_error(str(exc))
        return 4
    except (ValueError, FileNotFoundError) as exc:
        _print_error(str(exc))
        return 2
    for src in result["sources"]:
        print(f"{src['file']} chunk {src['chunk']}", file=sys.stderr)
    print(result["answer"])
    signer = result["verification"].get("signer", "")
    print(f"signature OK, signer {signer}", file=sys.stderr)
    print(f"attestation: {result['attestation_level']}", file=sys.stderr)
    print(result["receipt_dir"], file=sys.stderr)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    result = verify_receipt(args.path)
    for name, ok in sorted(result["checks"].items()):
        print(f"{name}: {'OK' if ok else 'FAIL'}")
    print(f"signer: {result['signer']}")
    return 0 if result["ok"] else 5


def _cmd_chain(args: argparse.Namespace) -> int:
    result = verify_chain(args.dir)
    if result["ok"]:
        print(f"chain ok ({result['count']} receipts)")
        return 0
    for problem in result["problems"]:
        _print_error(problem)
    return 5


def _cmd_models(args: argparse.Namespace) -> int:
    api = NearAI(None, base_url=args.base_url)
    try:
        models = api.list_models()
    except ApiError as exc:
        _print_error(str(exc))
        return 4
    rows = []
    for entry in models:
        model_id = entry.get("id", "")
        tier = api.tier(model_id, models)
        pricing = entry.get("pricing") or {}
        rows.append((tier, model_id, pricing))
    rows.sort(key=lambda r: (_TIER_ORDER.get(r[0], 9), r[1]))
    for tier, model_id, pricing in rows:
        inp = pricing.get("input", "?")
        out = pricing.get("output", "?")
        print(f"{tier}\t{model_id}\tinput={inp} output={out}")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    fixture = Path(args.fixture)
    if not fixture.is_dir():
        _print_error(f"fixture folder not found: {fixture}")
        return 2
    request_path = fixture / "request.json"
    signature_path = fixture / "signature.json"
    answer_path = fixture / "answer.md"
    if not request_path.is_file() or not signature_path.is_file():
        _print_error("fixture missing request.json or signature.json")
        return 2
    request_body = request_path.read_text(encoding="utf-8")
    print(request_body)
    signature_payload = json.loads(signature_path.read_text(encoding="utf-8"))
    req_h, resp_h = parse_signed_text(signature_payload["text"])
    print(f"request hash: {req_h}")
    print(f"response hash: {resp_h}")
    result = verify_receipt(fixture)
    for name, ok in sorted(result["checks"].items()):
        print(f"{name}: {'OK' if ok else 'FAIL'}")
    if answer_path.is_file():
        print(answer_path.read_text(encoding="utf-8").rstrip())
    return 0 if result["ok"] else 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sealed")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build dossier search index")
    p_index.add_argument("folder")
    p_index.add_argument("--db", default=".sealed/index.db")
    p_index.set_defaults(func=_cmd_index)

    p_ask = sub.add_parser("ask", help="ask a question about the dossier")
    p_ask.add_argument("question")
    p_ask.add_argument("--folder", "-F", required=True)
    p_ask.add_argument("--entities", "-E", required=True)
    p_ask.add_argument("--model", default=DEFAULT_MODEL)
    p_ask.add_argument("--k", type=int, default=5)
    p_ask.add_argument("--receipts", default=".sealed/receipts")
    p_ask.add_argument("--db", default=".sealed/index.db")
    p_ask.add_argument("--dry-run", action="store_true")
    p_ask.add_argument("--allow-incognito", action="store_true")
    p_ask.add_argument("--base-url")
    p_ask.add_argument("--max-tokens", type=int, default=2000)
    p_ask.set_defaults(func=_cmd_ask)

    p_verify = sub.add_parser("verify", help="verify a receipt offline")
    p_verify.add_argument("path")
    p_verify.set_defaults(func=_cmd_verify)

    p_chain = sub.add_parser("chain", help="verify a receipt chain")
    p_chain.add_argument("dir")
    p_chain.set_defaults(func=_cmd_chain)

    p_models = sub.add_parser("models", help="list models and tiers")
    p_models.add_argument("--base-url")
    p_models.set_defaults(func=_cmd_models)

    p_demo = sub.add_parser("demo", help="replay a stored fixture run")
    p_demo.add_argument("--fixture", default="fixtures/run1")
    p_demo.set_defaults(func=_cmd_demo)

    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
