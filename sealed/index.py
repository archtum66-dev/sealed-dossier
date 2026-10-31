"""SQLite FTS5 index over dossier text files."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "can",
        "her",
        "was",
        "one",
        "our",
        "out",
        "day",
        "get",
        "has",
        "him",
        "his",
        "how",
        "man",
        "new",
        "now",
        "old",
        "see",
        "two",
        "way",
        "who",
        "boy",
        "did",
        "its",
        "let",
        "put",
        "say",
        "she",
        "too",
        "use",
        "der",
        "die",
        "das",
        "und",
        "ist",
        "nicht",
        "ein",
        "eine",
        "einer",
        "einem",
        "einen",
        "sie",
        "ich",
        "wir",
        "mit",
        "von",
        "auf",
        "für",
        "den",
        "dem",
        "des",
        "als",
        "auch",
        "bei",
        "nur",
        "oder",
        "war",
        "aus",
        "nach",
        "noch",
        "wie",
        "zum",
        "zur",
        "über",
        "unter",
    }
)


@dataclass(frozen=True)
class Chunk:
    file: str
    n: int
    text: str
    score: float


def _check_fts5(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE _fts5_probe USING fts5(x, tokenize='unicode61 remove_diacritics 2')"
        )
        conn.execute("DROP TABLE _fts5_probe")
    except sqlite3.OperationalError as exc:
        raise RuntimeError("SQLite FTS5 is required") from exc


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentences(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    chunks: list[str] = []
    rest = paragraph
    while len(rest) > max_chars:
        cut = rest.rfind(". ", 0, max_chars + 1)
        if cut == -1:
            chunks.append(rest[:max_chars])
            rest = rest[max_chars:]
        else:
            chunks.append(rest[: cut + 1].strip())
            rest = rest[cut + 2 :].lstrip()
    if rest:
        chunks.append(rest)
    return chunks


def _merge_paragraphs(paragraphs: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_sentences(para, max_chars))
            continue
        if not current:
            current = para
        elif len(current) + 2 + len(para) <= max_chars:
            current = current + "\n\n" + para
        else:
            chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks


def _chunk_file(text: str, max_chars: int) -> list[str]:
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []
    return _merge_paragraphs(paragraphs, max_chars)


_SUFFIXES = ("ungen", "ung", "ern", "en", "er", "es", "e", "n", "s")


def _stem(word: str) -> str:
    """Cut one common German ending so that 'Schimmels' also finds 'Schimmel'."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 5:
            return word[: -len(suffix)]
    return word


def _match_expression(terms: list[str]) -> str:
    parts: list[str] = []
    for term in terms:
        parts.append(f'"{term}"')
        stem = _stem(term)
        if len(stem) >= 4:
            parts.append(f'"{stem}"*')
    return " OR ".join(dict.fromkeys(parts))


def _query_terms(query: str) -> list[str]:
    words = re.findall(r"\w+", query.lower(), flags=re.UNICODE)
    return [w for w in words if len(w) >= 3 and w not in STOP_WORDS]


class Index:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    def build(
        self,
        folder: str | Path,
        extensions: tuple[str, ...] = (".txt", ".md"),
        max_chars: int = 900,
    ) -> dict:
        root = Path(folder)
        if self._db_path.exists():
            self._db_path.unlink()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            _check_fts5(conn)
            conn.execute(
                "CREATE VIRTUAL TABLE chunks USING fts5("
                "file UNINDEXED, n UNINDEXED, text, "
                "tokenize='unicode61 remove_diacritics 2'"
                ")"
            )
            file_count = 0
            chunk_count = 0
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in extensions:
                    continue
                rel = path.relative_to(root).as_posix()
                raw = path.read_text(encoding="utf-8", errors="replace")
                pieces = _chunk_file(raw, max_chars)
                if not pieces:
                    continue
                file_count += 1
                for idx, piece in enumerate(pieces, start=1):
                    conn.execute(
                        "INSERT INTO chunks(file, n, text) VALUES (?, ?, ?)",
                        (rel, idx, piece),
                    )
                    chunk_count += 1
            conn.commit()
        finally:
            conn.close()
        return {"files": file_count, "chunks": chunk_count}

    def search(self, query: str, k: int = 5) -> list[Chunk]:
        terms = _query_terms(query)
        if not terms:
            return []
        match_expr = _match_expression(terms)
        conn = sqlite3.connect(self._db_path)
        try:
            _check_fts5(conn)
            rows = conn.execute(
                "SELECT file, n, text, bm25(chunks) AS rank "
                "FROM chunks WHERE chunks MATCH ? "
                "ORDER BY rank LIMIT ?",
                (match_expr, k),
            ).fetchall()
        finally:
            conn.close()
        return [
            Chunk(file=row[0], n=int(row[1]), text=row[2], score=float(-row[3]))
            for row in rows
        ]
