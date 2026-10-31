# Sealed Dossier

**Ask an AI about a case file. The names stay on your machine. Every answer comes with a receipt that anyone can check offline.**

Track: **Privacy & Private AI** (`privacy`). Built on **NEAR AI Cloud** (private inference in a trusted execution environment, TEE).

## The problem

Lawyers, fiduciaries and advisors want AI help with case files.
They cannot paste client names, addresses and case numbers into a cloud chatbot.
And afterwards they cannot prove what was sent, to which model, and what came back.

## What Sealed Dossier does

```
dossier (local text files)
   │  1. search: the few excerpts that matter                    (SQLite full-text index, local)
   ▼
   │  2. replace names, addresses, IDs, case numbers             (placeholders like [PERSON_1])
   │  3. leak check: refuse to send if anything listed is left
   ▼
NEAR AI Cloud (model in a TEE)  ──►  answer + signature over the hashes of request and response
   │
   ▼  4. check the signature, restore the names locally, store a receipt
answer  +  receipt (hash chain, verifiable offline)
```

**Where NEAR is used:** the model runs on **NEAR AI Cloud**. Its API signs the hash of the exact request and of the exact response (`/v1/signature`) and publishes an attestation report (`/v1/attestation/report`). Sealed Dossier checks the signature, stores everything in a receipt, and uses a confidential-tier model by default (models that run outside a TEE are refused unless you pass `--allow-incognito`).

## For judges: four checks, no key, no network, five minutes

| # | Command | What you see |
|---|---|---|
| 1 | `python -m pytest -q` | **55 tests**, standard library only. They include crypto vectors made with `eth-account` (Keccak-256, EIP-191 signatures, address recovery) and a local mock of the API. |
| 2 | `python -m sealed ask "Welche Mängel wurden gemeldet, wann, und wie hat die Vermieterin reagiert?" --folder examples/dossier --entities examples/entities.json --dry-run` | The **exact request** that would leave the machine, with every name replaced, plus the SHA-256 of the request bytes. No network call. |
| 3 | `python -m sealed demo` | Replay of the recorded run in `fixtures/run1/`: what was sent, the signature check, the restored answer, the receipt chain. All re-checked offline. |
| 4 | `python -m sealed verify fixtures/run1/0001` | Recomputes both hashes, recovers the signer from the signature, checks the receipt hash. |

Python 3.10 or newer. Nothing to install: run the commands from the repository root.
The sample case in `examples/` is **invented**.

## Status, stated plainly

- **Done and tested offline:** search, pseudonymiser with leak check, API client, signature verification, receipts with hash chain, CLI, replay.
- **Recorded live run on NEAR AI Cloud:** not yet in this repository. `python examples/run_live.py` records it (needs an API key; three questions cost well under one US cent at the listed model prices). Until `fixtures/run1/` exists, `sealed demo` says so and exits.
- **Attestation:** the tool fetches the attestation report with a fresh random nonce and checks that the signer of the answer is listed in it. It does **not** verify the Intel TDX quote or the NVIDIA GPU evidence. The receipt therefore says `report_lists_signer`, never "verified". For the full check use NEAR AI's official verifier (`nearai/nearai-cloud-verifier`) on the stored `attestation.json`.
- **Limits** of the pseudonymiser, of the TEE and of the whole approach: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Use it on your own dossier

```
export NEARAI_API_KEY=...          # from https://cloud.near.ai ; never put it in the repository
python -m sealed models            # models and tiers, confidential first
python -m sealed ask "Your question" --folder my-dossier --entities my-entities.json --dry-run
python -m sealed ask "Your question" --folder my-dossier --entities my-entities.json
python -m sealed verify .sealed/receipts/0001
python -m sealed chain .sealed/receipts
```

`my-entities.json` lists what must not leave the machine (see `examples/entities.json`): persons, organisations, places, case numbers, each with aliases.
Always run `--dry-run` first and **read the request**: a name that is not listed is not replaced.
Built-in patterns also catch Swiss AHV numbers, IBANs, e-mail addresses, phone numbers and case numbers like `MI.2026.14`.

Exit codes: `0` ok, `2` usage or missing input, `3` leak or policy refusal, `4` network or API error, `5` verification failed.

## What a receipt contains

| File | Content | Share it? |
|---|---|---|
| `receipt.json` | model, tier, chat id, request and response hash, signer, attestation level, number of replacements per kind, hash of the previous receipt | yes |
| `request.json`, `response.txt` | the exact bytes that were hashed (names already replaced) | yes |
| `signature.json`, `attestation.json` | what the API returned | yes |
| `answer.md`, `excerpts.txt` | the answer with names restored, and the original excerpts | **no, local only** |

## Layout

```
sealed/        keccak.py, secp256k1.py   pure-Python crypto (no dependencies)
               pseudo.py, index.py       pseudonymiser, full-text search
               nearai.py, verify.py      API client, signature and attestation checks
               receipt.py, pipeline.py, cli.py
tests/         55 offline tests, mock of the NEAR AI API, crypto vectors
examples/      invented sample case, run_live.py
docs/          SPEC.md, NEARAI_API.md, THREAT_MODEL.md
fixtures/      model list snapshot (30 Oct 2026), run1/ (recorded live run)
```

## Libraries and tools

- **Runtime:** Python standard library only (`urllib`, `sqlite3` with FTS5, `hashlib`, `json`, `re`). The cryptography (Keccak-256, secp256k1 recovery) is plain Python in `sealed/`, checked against `eth-account` vectors.
- **Development:** `pytest`.
- **Service:** NEAR AI Cloud (OpenAI-compatible chat API, signature and attestation endpoints). Default model `Qwen/Qwen3.8-27B` (confidential tier in the model list of 30 Oct 2026).
- Reference for the verification format: `nearai/nearai-cloud-verifier` (MIT), used as documentation, not as code.

## AI assistance

Built with AI assistance, disclosed here:

- **Cursor (Composer model)** wrote the first implementation from a written specification (`docs/SPEC.md`).
- **Claude (Anthropic)** wrote the specification and the documents, reviewed the result, and fixed defects found in review (e-mail addresses cut apart by name replacement, receipts that would break on Windows line endings, a verification check that would have failed on real API responses, an overlong Keccak module (480 lines) replaced by a 60-line one).
- Correctness rests on tests, on `eth-account` as an independent reference for random inputs, and on the author's review. The author set the scope and decided what to build.

## Related project

The author has one other, independent hackathon project: **Terra matcher**, a non-custodial order matcher with a NEAR testnet escrow (track `defi`), submitted separately: https://github.com/archtum66-dev/terra-matcher

## Licence

MIT, see `LICENSE`. Not legal advice; the tool is an aid for analysis and drafting.
