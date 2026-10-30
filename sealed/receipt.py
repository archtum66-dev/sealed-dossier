"""Persist and verify sealed-dossier receipts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sealed.verify import sha256_text, verify_signature

_RECEIPT_DIR_RE = re.compile(r"^\d{4}$")
_ZERO_HASH = "0" * 64


def _canonical_receipt_json(obj: dict) -> str:
    copy = {k: v for k, v in obj.items() if k != "receipt_sha256"}
    return json.dumps(copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _receipt_hash(obj: dict) -> str:
    return sha256_text(_canonical_receipt_json(obj))


def _listed_receipt_dirs(root: Path) -> list[tuple[int, Path]]:
    dirs: list[tuple[int, Path]] = []
    if not root.is_dir():
        return dirs
    for child in root.iterdir():
        if child.is_dir() and _RECEIPT_DIR_RE.match(child.name):
            if (child / "receipt.json").is_file():
                dirs.append((int(child.name), child))
    return dirs


def _next_receipt_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    nums = [num for num, _child in _listed_receipt_dirs(root)]
    n = max(nums, default=0) + 1
    return root / f"{n:04d}"


def _prev_receipt_hash(root: Path) -> str:
    dirs = _listed_receipt_dirs(root)
    if not dirs:
        return _ZERO_HASH
    _num, last = max(dirs, key=lambda t: t[0])
    data = json.loads((last / "receipt.json").read_text(encoding="utf-8"))
    return data["receipt_sha256"]


def save_receipt(
    root: str | Path,
    *,
    model: str,
    model_tier: str,
    chat_result,
    signature_payload: dict,
    verification: dict,
    attestation_report: dict | None,
    attestation_level: str,
    replaced: dict[str, int],
    sources: list[dict],
    answer: str,
    excerpts: str,
) -> Path:
    root_path = Path(root)
    dest = _next_receipt_dir(root_path)
    dest.mkdir(parents=True, exist_ok=False)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    receipt_core = {
        "schema": "sealed-dossier/receipt/1",
        "created_utc": created,
        "model": model,
        "model_tier": model_tier,
        "chat_id": chat_result.chat_id,
        "request_sha256": sha256_text(chat_result.request_body),
        "response_sha256": sha256_text(chat_result.response_text),
        "signing_address": signature_payload.get("signing_address", ""),
        "signature_ok": bool(verification.get("ok")),
        "attestation_level": attestation_level,
        "replaced": replaced,
        "sources": sources,
        "prev_receipt_sha256": _prev_receipt_hash(root_path),
    }
    receipt_core["receipt_sha256"] = _receipt_hash(receipt_core)
    (dest / "receipt.json").write_text(
        json.dumps(receipt_core, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (dest / "request.json").write_text(chat_result.request_body, encoding="utf-8")
    (dest / "response.txt").write_text(chat_result.response_text, encoding="utf-8")
    (dest / "signature.json").write_text(
        json.dumps(signature_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    if attestation_report is not None:
        (dest / "attestation.json").write_text(
            json.dumps(attestation_report, indent=2) + "\n",
            encoding="utf-8",
        )
    (dest / "answer.md").write_text(answer + "\n", encoding="utf-8")
    (dest / "excerpts.txt").write_text(excerpts, encoding="utf-8")
    return dest


def _load_receipt_dir(path: Path) -> Path:
    if path.is_file() and path.name == "receipt.json":
        return path.parent
    if path.is_dir():
        return path
    raise ValueError("invalid receipt path")


def verify_receipt(path: str | Path) -> dict:
    problems: list[str] = []
    checks: dict[str, bool] = {}
    signer = ""
    try:
        rdir = _load_receipt_dir(Path(path))
        receipt_path = rdir / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        request_body = (rdir / "request.json").read_text(encoding="utf-8")
        response_text = (rdir / "response.txt").read_text(encoding="utf-8")
        signature_payload = json.loads(
            (rdir / "signature.json").read_text(encoding="utf-8")
        )
        checks["receipt_sha256"] = _receipt_hash(receipt) == receipt.get(
            "receipt_sha256", ""
        )
        checks["request_sha256"] = sha256_text(request_body) == receipt.get(
            "request_sha256", ""
        )
        checks["response_sha256"] = sha256_text(response_text) == receipt.get(
            "response_sha256", ""
        )
        verification = verify_signature(request_body, response_text, signature_payload)
        signer = verification.get("signer", "")
        checks["signature"] = bool(verification.get("ok"))
        checks["chat_id"] = receipt.get("chat_id") == signature_payload.get("chat_id")
        checks["signing_address"] = (
            str(receipt.get("signing_address", "")).lower()
            == str(signature_payload.get("signing_address", "")).lower()
        )
        for name, ok in checks.items():
            if not ok:
                problems.append(f"check failed: {name}")
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        problems.append(str(exc))
        checks = {k: False for k in checks} if checks else {"load": False}
        if "load" not in checks:
            checks["load"] = False
    ok = bool(checks) and all(checks.values()) and not problems
    return {"ok": ok, "checks": checks, "signer": signer, "problems": problems}


def verify_chain(root: str | Path) -> dict:
    root_path = Path(root)
    problems: list[str] = []
    if not root_path.is_dir():
        return {"ok": False, "count": 0, "problems": ["receipt root missing"]}
    dirs = sorted(_listed_receipt_dirs(root_path), key=lambda t: t[0])
    expected = 1
    prev_hash = _ZERO_HASH
    for num, rdir in dirs:
        if num != expected:
            problems.append(f"gap in receipt numbering at {num:04d}")
        expected += 1
        receipt = json.loads((rdir / "receipt.json").read_text(encoding="utf-8"))
        if receipt.get("prev_receipt_sha256") != prev_hash:
            problems.append(f"prev hash mismatch in {num:04d}")
        result = verify_receipt(rdir)
        if not result["ok"]:
            problems.append(f"receipt {num:04d} invalid")
        prev_hash = receipt.get("receipt_sha256", "")
    return {"ok": not problems, "count": len(dirs), "problems": problems}
