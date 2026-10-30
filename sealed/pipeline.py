"""End-to-end ask flow: index, pseudonymise, chat, verify, receipt."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from sealed.index import Index
from sealed.nearai import DEFAULT_MODEL, NearAI
from sealed.pseudo import Pseudonymizer, load_entities
from sealed.receipt import save_receipt
from sealed.verify import attestation_status, verify_signature

SYSTEM_MESSAGE = (
    "You are an analysis and drafting assistant for legal documents. "
    "Answer only from the numbered excerpts. Cite the excerpts you use as "
    "[S1], [S2] and so on. If the excerpts do not contain the answer, say so. "
    "Placeholders such as [PERSON_1] stand for real names; keep them unchanged. "
    "You give no legal advice. Answer in the language of the question."
)


class LeakError(Exception):
    """Sensitive data would leave the machine."""


class PolicyError(Exception):
    """Model tier not allowed."""


class VerificationError(Exception):
    """API signature verification failed."""


def build_request(
    question: str,
    chunks,
    pseudonymizer: Pseudonymizer,
    model: str,
    max_tokens: int,
) -> tuple[dict, list[dict]]:
    pseudo_q = pseudonymizer.apply(question)
    sources: list[dict] = []
    lines: list[str] = [f"Question: {pseudo_q}", "", "Excerpts:"]
    for idx, chunk in enumerate(chunks, start=1):
        pseudo_text = pseudonymizer.apply(chunk.text)
        sources.append({"file": chunk.file, "chunk": chunk.n})
        lines.append(f"[S{idx}] {pseudo_text}")
        if idx < len(chunks):
            lines.append("")
    user_content = "\n".join(lines)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    return body, sources


def _leak_check(pseudonymizer: Pseudonymizer, *texts: str) -> None:
    kinds: list[str] = []
    for text in texts:
        for kind in pseudonymizer.leaks(text):
            if kind not in kinds:
                kinds.append(kind)
    if kinds:
        raise LeakError(f"leak detected: {', '.join(kinds)}")


def _format_excerpts(chunks) -> str:
    parts: list[str] = []
    for chunk in chunks:
        parts.append(f"{chunk.file}\t{chunk.n}\t{chunk.text}")
    return "\n".join(parts) + ("\n" if parts else "")


def ask(
    question: str,
    folder: str | Path,
    entities_path: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    k: int = 5,
    receipts_dir: str | Path = ".sealed/receipts",
    db_path: str | Path = ".sealed/index.db",
    api: NearAI | None = None,
    dry_run: bool = False,
    allow_incognito: bool = False,
    max_tokens: int = 2000,
    rebuild: bool = True,
) -> dict:
    entities = load_entities(entities_path)
    pseudo = Pseudonymizer(entities)
    index = Index(db_path)
    if rebuild:
        index.build(folder)
    chunks = index.search(question, k=k)
    body, sources = build_request(question, chunks, pseudo, model, max_tokens)
    request_json = json.dumps(body)
    user_msg = body["messages"][1]["content"]
    _leak_check(pseudo, SYSTEM_MESSAGE, user_msg)
    if dry_run:
        return {
            "dry_run": True,
            "request_body": request_json,
            "sources": sources,
            "replaced": pseudo.counts,
        }
    client = api or NearAI(os.environ.get("NEARAI_API_KEY"))
    tier = client.tier(model)
    if tier in ("incognito", "unknown") and not allow_incognito:
        raise PolicyError(f"model tier not allowed: {tier}")
    chat_result = client.chat(
        model,
        body["messages"],
        max_tokens=max_tokens,
        temperature=0,
    )
    sig = client.signature(chat_result.chat_id, model)
    verification = verify_signature(
        chat_result.request_body, chat_result.response_text, sig
    )
    if not verification["ok"]:
        raise VerificationError("signature verification failed")
    nonce = secrets.token_hex(32)
    signing_address = sig.get("signing_address", "")
    attestation_report = None
    attestation_level = "not_checked"
    try:
        attestation_report = client.attestation_report(model, nonce, signing_address)
        attestation_level = attestation_status(
            attestation_report, signing_address
        )["level"]
    except Exception:
        attestation_level = "not_checked"
    answer = pseudo.restore(chat_result.content)
    excerpts = _format_excerpts(chunks)
    receipt_dir = save_receipt(
        receipts_dir,
        model=model,
        model_tier=tier,
        chat_result=chat_result,
        signature_payload=sig,
        verification=verification,
        attestation_report=attestation_report,
        attestation_level=attestation_level,
        replaced=pseudo.counts,
        sources=sources,
        answer=answer,
        excerpts=excerpts,
    )
    return {
        "answer": answer,
        "receipt_dir": str(receipt_dir),
        "verification": verification,
        "attestation_level": attestation_level,
        "sources": sources,
        "replaced": pseudo.counts,
        "chat_id": chat_result.chat_id,
    }
