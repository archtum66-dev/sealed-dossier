# Sealed Dossier: specification (binding for the implementation)

**Purpose.** Ask a question about a local dossier (a folder of text files) and have a private AI answer it, such that (1) real names, addresses, numbers and case numbers never leave the machine, (2) the model runs in a trusted execution environment (NEAR AI Cloud), (3) every answer comes with a receipt that anyone can re-verify offline: the signed hashes of the exact request and response, and the signing address.

**Not a lawyer.** The tool is an analysis and drafting aid. It gives no legal advice. A TEE does not replace professional secrecy duties.

## Layout

```
sealed/__init__.py   sealed/__main__.py   sealed/cli.py        argparse CLI, entry point main(argv=None) -> int
sealed/keccak.py     sealed/secp256k1.py                       pure-Python crypto, no dependencies
sealed/pseudo.py     sealed/index.py                           pseudonymiser, SQLite FTS5 search
sealed/nearai.py     sealed/verify.py   sealed/receipt.py      API client, verification, receipts
sealed/pipeline.py                                              ask flow
sealed/data/models_snapshot.json                                copy of fixtures/models_snapshot_2026-10-30.json (offline fallback)
tests/                                                          pytest, offline, stdlib mock server in tests/mock_nearai.py
examples/, fixtures/run1/, README.md, docs/THREAT_MODEL.md        written by the maintainer, NOT part of the first implementation round
```

## 1. `sealed/keccak.py`

`keccak256(data: bytes) -> bytes`: Keccak-f[1600], rate 136 bytes, capacity 512, **padding byte 0x01 ... 0x80** (original Keccak, as used by Ethereum; not `hashlib.sha3_256`). Verified by `tests/vectors/crypto_vectors.json` key `keccak256` (fields `input_hex`, `keccak256`).

## 2. `sealed/secp256k1.py`

- `eip191_hash(text: str) -> bytes`: `keccak256(b"\x19Ethereum Signed Message:\n" + str(len(b)).encode() + b)` with `b = text.encode("utf-8")`.
- `recover_address(message_hash: bytes, signature_hex: str) -> str`: signature `0x` + 130 hex chars (`r||s||v`, `v` in {27, 28, 0, 1}); returns the lowercase `0x` + 40 hex address. Raise `ValueError` for malformed input or when no valid point exists. Reject `r` or `s` outside `1..n-1`.
- `address_from_private_key(priv: int) -> str` (lowercase, `0x`).
- `personal_sign(text: str, priv: int) -> str`: for tests and the mock server only. Deterministic nonce `k` (RFC 6979 with HMAC-SHA256, or any deterministic derivation), **low-s** normalised, `v` = 27 or 28, returns `0x` + 130 hex. Must satisfy `recover_address(eip191_hash(text), personal_sign(text, priv)) == address_from_private_key(priv)`.
- Constants: p = 2^256 - 2^32 - 977, n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141, G the standard base point. Use Jacobian or affine arithmetic with `pow(x, -1, p)`. Speed is not a goal (a recovery may take up to a second).
- Verified by `tests/vectors/crypto_vectors.json` keys `personal_sign` (fields `text`, `message_hash`, `signature`, `address`) and `address_from_private_key`. Also test: `v` given as 0/1 recovers the same address; flipping one bit of the signature or the text changes (or breaks) the address.

## 3. `sealed/pseudo.py`

```python
class Pseudonymizer:
    def __init__(self, entities: dict[str, list]) -> None
    def apply(self, text: str) -> str
    def restore(self, text: str) -> str
    def leaks(self, text: str) -> list[str]
    @property
    def counts(self) -> dict[str, int]      # number of distinct placeholders per kind
    def mapping(self) -> dict[str, str]     # placeholder -> original (stays local, never sent or stored in receipts)
def load_entities(path) -> dict             # reads JSON, validates, raises ValueError with a clear message
```

`entities` maps a kind (`person`, `org`, `place`, `case`, `other`) to a list; each item is a string or a list of strings (aliases of one thing; all map to the same placeholder, the first is the canonical one). Placeholders look like `[PERSON_1]`, `[ORG_1]`, `[PLACE_1]`, `[CASE_1]`, `[OTHER_1]`, numbered per kind in order of first appearance in the **texts passed to `apply`** within one `Pseudonymizer` instance. The same original (case-insensitive) always gets the same placeholder.

Matching rules for listed entities: case-insensitive; spaces inside an entity match any run of whitespace (including newlines); the match must not start or end inside a word (use `(?<!\w)` and `(?!\w)`, `\w` unicode-aware); an optional genitive `s` after the entity is part of the match (`Musters` -> `[PERSON_1]`); longest alias first so that `Hans Muster` wins over `Muster`.

Built-in patterns, always applied after the listed entities, each with its own kind:

| Kind | Placeholder | Pattern (case-insensitive) |
|---|---|---|
| AHV | `[AHV_n]` | `756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}` |
| IBAN | `[IBAN_n]` | `CH\d{2}(?:\s?[0-9A-Z]{4}){4}\s?[0-9A-Z]` (Swiss IBAN, with or without spaces) |
| EMAIL | `[EMAIL_n]` | `[\w.+-]+@[\w-]+(?:\.[\w-]+)+` |
| PHONE | `[PHONE_n]` | `(?:\+41\|0041\|0)\s?\d{2}[\s.]?\d{3}[\s.]?\d{2}[\s.]?\d{2}` (not preceded or followed by a digit) |
| CASE | `[CASE_n]` | `\b[A-Z]{1,4}\.\d{4}\.\d{1,6}\b` (e.g. `MI.2026.14`) |

`restore` replaces every placeholder known to this instance by its canonical original, longest placeholder first; unknown placeholders stay unchanged. Round trip: `restore(apply(t)) == t` except for case differences of matched entities and dropped genitive `s` (document this in a test, do not hide it).

`leaks(text)` returns the list of kinds/strings still detectable in `text` (every listed alias, every built-in pattern, **excluding** text inside placeholders). On a correctly pseudonymised text it returns `[]`.

## 4. `sealed/index.py`

```python
@dataclass(frozen=True)
class Chunk:  file: str; n: int; text: str; score: float     # file relative to the folder, POSIX slashes; n = 1-based chunk number
class Index:
    def __init__(self, db_path: str | Path) -> None
    def build(self, folder: str | Path, extensions=(".txt", ".md"), max_chars: int = 900) -> dict   # {"files": int, "chunks": int}
    def search(self, query: str, k: int = 5) -> list[Chunk]
```

SQLite FTS5 table with tokenizer `unicode61 remove_diacritics 2`; `build` recreates the index. Chunking: split a file at blank lines, then merge consecutive paragraphs while the chunk stays <= `max_chars`; a single longer paragraph is split at sentence ends (`. `), and as a last resort at `max_chars`. Query: lowercase words of 3 or more letters, minus a short German and English stop-word list, joined with `OR`, each word quoted for FTS5; no usable word -> `[]`. Order by `bm25`, best first; `score` is the positive relevance (`-bm25`). If FTS5 is not compiled in, raise `RuntimeError("SQLite FTS5 is required")`. Files that are not valid UTF-8 are read with `errors="replace"`.

## 5. `sealed/nearai.py`

```python
DEFAULT_BASE_URL = "https://cloud-api.near.ai"
DEFAULT_MODEL = "Qwen/Qwen3.8-27B"
@dataclass
class ChatResult: chat_id: str; model: str; request_body: str; response_text: str; content: str
class ApiError(Exception): ...        # message never contains the API key
class NearAI:
    def __init__(self, api_key: str | None, base_url: str | None = None, timeout: float = 120.0) -> None
    def list_models(self) -> list[dict]
    def tier(self, model_id: str, models: list[dict] | None = None) -> str    # "confidential" | "attested_3p" | "incognito" | "unknown"
    def chat(self, model: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0) -> ChatResult
    def signature(self, chat_id: str, model: str) -> dict
    def attestation_report(self, model: str, nonce: str, signing_address: str) -> dict
```

Use `urllib.request` only. `base_url` falls back to env `NEARAI_BASE_URL`, then the default; strip a trailing slash. `chat` follows `docs/NEARAI_API.md` exactly (body via `json.dumps(body)`, response text decoded as UTF-8 once, `request_body` and `response_text` returned unmodified). Map HTTP errors, timeouts and bad JSON to `ApiError` with a short message (status code, first 200 characters of the body, never headers). `tier` uses `owned_by` as in `docs/NEARAI_API.md`; if `models` is None it calls `list_models()` and, on `ApiError`, falls back to `sealed/data/models_snapshot.json`. `list_models` returns the `data` array. `signature` and `attestation_report` return the parsed JSON; `attestation_report` is sent without the key.

## 6. `sealed/verify.py`

```python
def sha256_text(text: str) -> str
def parse_signed_text(text: str) -> tuple[str, str]                  # (request_hash, response_hash); ValueError unless 2 or 3 colon parts of which the last two are 64 lowercase hex chars
def verify_signature(request_body: str, response_text: str, sig: dict) -> dict
def attestation_status(report: dict | None, signing_address: str) -> dict
```

`verify_signature` returns `{"request_hash_ok": bool, "response_hash_ok": bool, "signature_ok": bool, "signer": "0x...", "ok": bool}` where `ok` is all three. `signature_ok` means the recovered address equals `sig["signing_address"]` (case-insensitive). A malformed payload gives all flags false and `signer` empty, never an exception.

**Attestation status** (`attestation_status`) returns `{"level": <one of the three strings>, "detail": str}`:
- `"not_checked"`: `report` is None.
- `"report_lists_signer"`: the report (single object or any item of `model_attestations`) names `signing_address`. This is **only a structural check**: it does *not* verify the TDX quote, the GPU evidence or the nonce binding.
- `"signer_missing"`: a report exists but does not list the signer.
The level `"verified_by_official_verifier"` is reserved for a later version and must not be produced by this code.

## 7. `sealed/receipt.py`

A receipt directory holds numbered subdirectories `0001`, `0002`, ... each with:
`receipt.json`, `request.json` (the exact `request_body`), `response.txt` (the exact `response_text`), `signature.json` (the payload from the API), `attestation.json` (optional, the report), `answer.md` (restored answer, local only), `excerpts.txt` (what was cut from the dossier: file, chunk, original text; local only).

`receipt.json` fields (all required): `schema` = `"sealed-dossier/receipt/1"`, `created_utc` (ISO 8601, `Z`), `model`, `model_tier`, `chat_id`, `request_sha256`, `response_sha256`, `signing_address`, `signature_ok` (bool), `attestation_level`, `replaced` (dict kind -> count of distinct placeholders), `sources` (list of `{"file", "chunk"}`), `prev_receipt_sha256` (64 hex chars, 64 zeros for the first), `receipt_sha256`. `receipt_sha256` = SHA-256 over the canonical JSON of the receipt **without** that field (`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8).

```python
def save_receipt(root, *, model, model_tier, chat_result, signature_payload, verification, attestation_report, attestation_level, replaced, sources, answer, excerpts) -> Path   # returns the new subdirectory
def verify_receipt(path) -> dict       # offline; path = receipt dir or receipt.json; {"ok": bool, "checks": {name: bool}, "signer": str, "problems": [str]}
def verify_chain(root) -> dict         # {"ok": bool, "count": int, "problems": [str]}
```

`verify_receipt` recomputes: request/response hashes from the stored files, the signature check from `signature.json`, the `receipt_sha256`, and that `chat_id`/`signing_address` match. `verify_chain` additionally checks that each `prev_receipt_sha256` equals the previous `receipt_sha256` and that numbering has no gaps.

## 8. `sealed/pipeline.py`

```python
def build_request(question, chunks, pseudonymizer, model, max_tokens) -> tuple[dict, list[dict]]   # (request body dict, sources list)
def ask(question, folder, entities_path, *, model=DEFAULT_MODEL, k=5, receipts_dir=".sealed/receipts", db_path=".sealed/index.db",
        api=None, dry_run=False, allow_incognito=False, max_tokens=2000, rebuild=True) -> dict
```

Flow: (1) load entities; (2) build the index (if `rebuild`) and search the **original** question; (3) the `Pseudonymizer` is applied to the question and to every chunk; (4) leak check on every string that goes into the request body: any non-empty `leaks()` -> raise `LeakError` (subclass of `Exception`, message lists kinds only, not the matched text); (5) body: system message, then one user message; (6) `dry_run`: return `{"dry_run": True, "request_body": <json string>, "sources": [...], "replaced": counts}` without any network call; (7) tier check (refuse `incognito` and `unknown` unless `allow_incognito`; raise `PolicyError`); (8) `api.chat`, then `api.signature`, then `verify_signature`; if not `ok` raise `VerificationError` (the answer is not shown); (9) fetch the attestation report with a fresh 32-byte random nonce (64 hex chars) and compute `attestation_status` (an `ApiError` here gives level `not_checked`, not a failure); (10) restore the answer, save the receipt, return `{"answer", "receipt_dir", "verification", "attestation_level", "sources", "replaced", "chat_id"}`.

System message (exactly this text): `You are an analysis and drafting assistant for legal documents. Answer only from the numbered excerpts. Cite the excerpts you use as [S1], [S2] and so on. If the excerpts do not contain the answer, say so. Placeholders such as [PERSON_1] stand for real names; keep them unchanged. You give no legal advice. Answer in the language of the question.`

User message: `Question: <pseudonymised question>\n\nExcerpts:\n[S1] <chunk text>\n\n[S2] <chunk text>` (one block per chunk, in rank order). Excerpt numbers map to `sources`.

## 9. CLI (`python -m sealed ...`, also entry point `sealed`)

| Command | Behaviour |
|---|---|
| `index FOLDER [--db PATH]` | build the index, print `files` and `chunks` |
| `ask QUESTION --folder F --entities E [--model M] [--k N] [--receipts DIR] [--dry-run] [--allow-incognito] [--base-url URL] [--max-tokens N]` | run the flow; print what was cut from the dossier (file and chunk numbers), the restored answer, the verification line (`signature OK, signer 0x...`), the attestation level and the receipt directory. `--dry-run` prints the exact request JSON and `leak check passed`, makes no network call and needs no key. Without `--dry-run` the key comes from `NEARAI_API_KEY`; missing key -> exit 2 with a clear message. |
| `verify PATH` | offline `verify_receipt`; print each check as `OK`/`FAIL` and the signer; exit 0 only if all pass |
| `chain DIR` | offline `verify_chain` |
| `models [--base-url URL]` | list models with tier and prices, confidential first |
| `demo [--fixture DIR]` | replay a stored run (`--fixture` default `fixtures/run1`): show the pseudonymised request, the signed hashes, run `verify_receipt`, show the answer from `answer.md`; make no network call; if the folder is missing print a clear message and exit 2 |

Exit codes: 0 ok; 2 usage or missing input; 3 leak or policy refusal (`LeakError`, `PolicyError`); 4 network or API error; 5 verification failed. Messages go to stderr for errors. Never print the key.

## 10. Tests that must exist (all offline)

`tests/test_keccak.py`, `test_secp256k1.py` (vectors above), `test_pseudo.py` (every rule, aliases, genitive, word boundaries, each built-in pattern, round trip, `leaks`), `test_index.py` (umlauts, ranking, chunk sizes, no usable query), `test_verify.py`, `test_receipt.py` (hash chain, tamper detection for each file), `test_pipeline.py` (dry run sends nothing and the body contains no listed entity or pattern; leak refusal when a pseudonymiser is sabotaged; incognito model refused; full flow against the mock with restored answer and valid receipt; tampered signature -> `VerificationError`), `test_cli.py` (subprocess `python -m sealed`: `ask --dry-run`, `verify`, exit codes). `tests/mock_nearai.py` is a stdlib `http.server` mock of `/v1/models`, `/v1/chat/completions`, `/v1/signature/{id}`, `/v1/attestation/report` that signs with a fixed **test** key via `personal_sign`, requires `Authorization: Bearer test-key`, and has switches to tamper with the response hash or the signer.
