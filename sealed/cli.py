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
from sealed.verify import sha256_text

_TIER_ORDER = {"confidential": 0, "attested_3p": 1, "incognito": 2, "unknown": 3}


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)


def _cmd_index(args: argparse.Namespace) -> int:
    index = Index(args.db)
    stats = index.build(args.folder)
    print(f"files={stats['files']} chunks={stats['chunks']}")
    return 0


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "nothing replaced"
    return ", ".join(f"{kind}={n}" for kind, n in sorted(counts.items()))


def _cmd_ask(args: argparse.Namespace) -> int:
    api = None
    if not args.dry_run:
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
            dry_run=args.dry_run,
            allow_incognito=args.allow_incognito,
            max_tokens=args.max_tokens,
            rebuild=True,
        )
    except (LeakError, PolicyError) as exc:
        _print_error(str(exc))
        return 3
    except VerificationError as exc:
        _print_error(str(exc))
        return 5
    except ApiError as exc:
        _print_error(str(exc))
        return 4
    except (ValueError, OSError) as exc:
        _print_error(str(exc))
        return 2
    for src in result["sources"]:
        print(f"source: {src['file']} chunk {src['chunk']}", file=sys.stderr)
    print(f"replaced: {_format_counts(result['replaced'])}", file=sys.stderr)
    if args.dry_run:
        # Show the request as readable text; the bytes that would be sent are this
        # same content JSON-encoded, and their hash is printed so it can be compared later.
        body = json.loads(result["request_body"])
        for message in body["messages"]:
            print(f"--- {message['role']} ---")
            print(message["content"])
        print(f"request sha256: {sha256_text(result['request_body'])}", file=sys.stderr)
        print("leak check passed", file=sys.stderr)
        return 0
    print(result["answer"])
    signer = result["verification"].get("signer", "")
    print(f"signature OK, signer {signer}", file=sys.stderr)
    print(f"attestation: {result['attestation_level']}", file=sys.stderr)
    print(f"receipt: {result['receipt_dir']}", file=sys.stderr)
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


def _demo_receipt_dirs(fixture: Path) -> list[Path]:
    if (fixture / "receipt.json").is_file():
        return [fixture]
    return sorted(
        child
        for child in fixture.iterdir()
        if child.is_dir() and (child / "receipt.json").is_file()
    )


def _cmd_demo(args: argparse.Namespace) -> int:
    """Replay a stored run offline: no network, no key. Everything shown is re-checked."""
    fixture = Path(args.fixture)
    if not fixture.is_dir():
        _print_error(
            f"fixture folder not found: {fixture} (record a run with: python examples/run_live.py)"
        )
        return 2
    receipt_dirs = _demo_receipt_dirs(fixture)
    if not receipt_dirs:
        _print_error(f"no receipts in {fixture}")
        return 2
    all_ok = True
    for rdir in receipt_dirs:
        receipt = json.loads((rdir / "receipt.json").read_text(encoding="utf-8"))
        request = json.loads((rdir / "request.json").read_bytes().decode("utf-8"))
        print(f"===== {rdir.name}: model {receipt['model']} ({receipt['model_tier']}) =====")
        print("What left the machine (names already replaced):")
        print(request["messages"][-1]["content"])
        print()
        result = verify_receipt(rdir)
        all_ok = all_ok and result["ok"]
        for name, ok in sorted(result["checks"].items()):
            print(f"  {name}: {'OK' if ok else 'FAIL'}")
        print(f"  signer: {result['signer']}")
        print(f"  attestation level: {receipt['attestation_level']}")
        answer_path = rdir / "answer.md"
        if answer_path.is_file():
            print()
            print("Answer (names restored on this machine):")
            print(answer_path.read_bytes().decode("utf-8").rstrip())
        print()
    if len(receipt_dirs) > 1 or fixture != receipt_dirs[0]:
        chain = verify_chain(fixture)
        print(f"chain: {'OK' if chain['ok'] else 'FAIL'} ({chain['count']} receipts)")
        all_ok = all_ok and chain["ok"]
    return 0 if all_ok else 5


def _print_attest(label: str, result: dict) -> None:
    print(f"{label}")
    print(f"  signer  {result['signer']}")
    print(f"  nonce   {result['nonce']}")
    for name, ok in result["checks"].items():
        detail = result["details"].get(name, "")
        print(f"  {'ok  ' if ok else 'FAIL'}    {name}{(': ' + detail) if detail else ''}")
    print(f"  level   {result['level']}")


def _cmd_attest(args: argparse.Namespace) -> int:
    from sealed import attest

    results = []
    if args.model:
        nonce = attest.new_nonce()
        try:
            report = attest.fetch_report(args.model, nonce)
        except (OSError, ValueError) as exc:
            _print_error(f"attestation report: {exc}")
            return 4
        for i, item in enumerate(report.get("model_attestations") or [], start=1):
            res = attest.check_attestation(item, nonce, network=True)
            _print_attest(f"fresh report for {args.model}, model attestation #{i}", res)
            results.append(res)
    else:
        if not args.receipt:
            _print_error("give a receipt directory or --model")
            return 2
        rdir = Path(args.receipt)
        try:
            receipt = json.loads((rdir / "receipt.json").read_text(encoding="utf-8"))
            report = json.loads((rdir / "attestation.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _print_error(f"cannot read receipt: {exc}")
            return 2
        signer = str(receipt.get("signing_address", "")).lower()
        items = [
            a for a in report.get("model_attestations") or []
            if str(a.get("signing_address", "")).lower() == signer
        ]
        if not items:
            _print_error("the stored report does not list the receipt's signer")
            return 5
        res = attest.check_attestation(items[0], network=args.network)
        _print_attest(f"stored report of receipt {rdir}", res)
        if not args.network:
            print("  (Intel quote signature and NVIDIA verdict not checked: add --network)")
        results.append(res)
    if not results:
        _print_error("no model attestation in the report")
        return 5
    wanted = "full" if (args.network or args.model) else "quote_binds_signer"
    return 0 if all(r["level"] == wanted for r in results) else 5


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
    p_ask.add_argument("--max-tokens", type=int, default=6000)
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

    p_attest = sub.add_parser(
        "attest", help="check the attestation of a receipt's signer (TDX, GPU, compose)"
    )
    p_attest.add_argument("receipt", nargs="?", help="receipt directory (uses its stored report)")
    p_attest.add_argument("--network", action="store_true",
                          help="also check the Intel quote signature (dcap-qvl) and NVIDIA's verdict")
    p_attest.add_argument("--model", help="fetch a fresh report for this model instead (network)")
    p_attest.set_defaults(func=_cmd_attest)

    p_demo = sub.add_parser("demo", help="replay a stored fixture run")
    p_demo.add_argument("--fixture", default="fixtures/run1")
    p_demo.set_defaults(func=_cmd_demo)

    for stream in (sys.stdout, sys.stderr):
        # Dossiers contain umlauts; never crash on a console with a legacy code page.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
