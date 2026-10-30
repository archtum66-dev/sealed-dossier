"""Pseudonymise dossier text before it leaves the machine."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VALID_KINDS = frozenset({"person", "org", "place", "case", "other"})

_KIND_TO_PREFIX = {
    "person": "PERSON",
    "org": "ORG",
    "place": "PLACE",
    "case": "CASE",
    "other": "OTHER",
}

_BUILTIN_PATTERNS: list[tuple[str, str, int]] = [
    (
        "AHV",
        r"756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}",
        re.IGNORECASE,
    ),
    (
        "IBAN",
        r"CH\d{2}(?:\s?[0-9A-Z]{4}){4}\s?[0-9A-Z]",
        re.IGNORECASE,
    ),
    (
        "EMAIL",
        r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
        re.IGNORECASE,
    ),
    (
        "PHONE",
        r"(?<!\d)(?:\+41|0041|0)\s?\d{2}[\s.]?\d{3}[\s.]?\d{2}[\s.]?\d{2}(?!\d)",
        re.IGNORECASE,
    ),
    (
        "CASE",
        r"\b[A-Z]{1,4}\.\d{4}\.\d{1,6}\b",
        0,
    ),
]

_PLACEHOLDER_RE = re.compile(r"\[[A-Z]+_\d+\]")


def load_entities(path: str | Path) -> dict[str, list]:
    """Load and validate an entities JSON file."""
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read entities file: {p}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in entities file: {p}") from exc
    if not isinstance(data, dict):
        raise ValueError("entities root must be a JSON object")
    out: dict[str, list] = {}
    for kind, items in data.items():
        if kind not in VALID_KINDS:
            raise ValueError(f"unknown entity kind: {kind!r}")
        if not isinstance(items, list):
            raise ValueError(f"entities for {kind!r} must be a list")
        normalised: list = []
        for item in items:
            if isinstance(item, str):
                if not item.strip():
                    raise ValueError(f"empty entity string in {kind!r}")
                normalised.append(item)
            elif isinstance(item, list):
                if not item:
                    raise ValueError(f"empty alias list in {kind!r}")
                aliases = []
                for alias in item:
                    if not isinstance(alias, str) or not alias.strip():
                        raise ValueError(f"invalid alias in {kind!r}")
                    aliases.append(alias)
                normalised.append(aliases)
            else:
                raise ValueError(f"invalid entity entry in {kind!r}")
        out[kind] = normalised
    return out


def _entity_regex(alias: str) -> re.Pattern[str]:
    parts = alias.split()
    if parts:
        inner = r"\s+".join(re.escape(part) for part in parts)
    else:
        inner = re.escape(alias)
    pattern = rf"(?<!\w){inner}(?:s)?(?!\w)"
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


class Pseudonymizer:
    """Replace known entities and sensitive patterns with numbered placeholders."""

    def __init__(self, entities: dict[str, list]) -> None:
        self._entities = entities
        self._next_num: dict[str, int] = {}
        self._original_to_placeholder: dict[str, str] = {}
        self._placeholder_to_canonical: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._rules: list[tuple[re.Pattern[str], str, str]] = []
        for kind, items in entities.items():
            prefix = _KIND_TO_PREFIX[kind]
            expanded: list[tuple[str, str]] = []
            for item in items:
                if isinstance(item, str):
                    expanded.append((item, item))
                else:
                    canonical = item[0]
                    for alias in item:
                        expanded.append((alias, canonical))
            expanded.sort(key=lambda pair: len(pair[0]), reverse=True)
            for alias, canonical in expanded:
                self._rules.append((_entity_regex(alias), kind, canonical))

        self._builtin: list[tuple[str, re.Pattern[str]]] = []
        for name, pat, flags in _BUILTIN_PATTERNS:
            self._builtin.append((name, re.compile(pat, flags)))

    def _counter_key(self, kind: str) -> str:
        if kind in ("case", "CASE"):
            return "CASE"
        return kind

    def _placeholder_for(self, kind: str, canonical: str) -> str:
        key = canonical.casefold()
        if key in self._original_to_placeholder:
            return self._original_to_placeholder[key]
        prefix = _KIND_TO_PREFIX.get(kind, kind.upper())
        ck = self._counter_key(kind)
        num = self._next_num.get(ck, 0) + 1
        self._next_num[ck] = num
        ph = f"[{prefix}_{num}]"
        self._original_to_placeholder[key] = ph
        self._placeholder_to_canonical[ph] = canonical
        self._counts[kind] = self._counts.get(kind, 0) + 1
        return ph

    def _builtin_placeholder(self, kind: str, matched: str) -> str:
        ck = self._counter_key(kind)
        num = self._next_num.get(ck, 0) + 1
        self._next_num[ck] = num
        ph = f"[{kind}_{num}]"
        self._placeholder_to_canonical[ph] = matched
        self._counts[kind] = self._counts.get(kind, 0) + 1
        return ph

    def _apply_entities(self, text: str) -> str:
        if not self._rules:
            return text
        matches: list[tuple[int, int, str, str, str]] = []
        for regex, kind, canonical in self._rules:
            for m in regex.finditer(text):
                matches.append((m.start(), m.end(), kind, canonical, m.group(0)))
        matches.sort(key=lambda t: (t[0], -(t[1] - t[0])))
        chosen: list[tuple[int, int, str, str, str]] = []
        occupied: list[tuple[int, int]] = []
        for start, end, kind, canonical, matched in matches:
            overlap = False
            for o_start, o_end in occupied:
                if start < o_end and end > o_start:
                    overlap = True
                    break
            if overlap:
                continue
            chosen.append((start, end, kind, canonical, matched))
            occupied.append((start, end))
        chosen.sort(key=lambda t: t[0], reverse=True)
        out = text
        for start, end, kind, canonical, _matched in chosen:
            ph = self._placeholder_for(kind, canonical)
            out = out[:start] + ph + out[end:]
        return out

    def _apply_builtins(self, text: str) -> str:
        out = text
        for kind, regex in self._builtin:
            def repl(m: re.Match[str], *, _kind: str = kind) -> str:
                return self._builtin_placeholder(_kind, m.group(0))

            out = regex.sub(repl, out)
        return out

    def apply(self, text: str) -> str:
        out = self._apply_entities(text)
        return self._apply_builtins(out)

    def restore(self, text: str) -> str:
        out = text
        placeholders = sorted(
            self._placeholder_to_canonical.keys(),
            key=len,
            reverse=True,
        )
        for ph in placeholders:
            out = out.replace(ph, self._placeholder_to_canonical[ph])
        return out

    def leaks(self, text: str) -> list[str]:
        stripped = _PLACEHOLDER_RE.sub(" ", text)
        found: list[str] = []
        for regex, kind, _canonical in self._rules:
            if regex.search(stripped) and kind not in found:
                found.append(kind)
        for kind, regex in self._builtin:
            if regex.search(stripped) and kind not in found:
                found.append(kind)
        return found

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def mapping(self) -> dict[str, str]:
        return dict(self._placeholder_to_canonical)
