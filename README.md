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

## For judges: five checks, no key, no network, five minutes

**In the browser, no install:** https://archtum66-dev.github.io/sealed-dossier/ replays the recorded run and re-checks all three receipts inside the page: both SHA-256 hashes, the EIP-191 signature (signer recovered in the page), the receipt hash and the chain. The same page is `web/index.html`; `python web/build.py --check` shows that it is a fresh build of `fixtures/run1/`.

| # | Command | What you see |
|---|---|---|
| 1 | `python -m pytest -q` | **65 tests**, standard library only. They include crypto vectors made with `eth-account` (Keccak-256, EIP-191 signatures, address recovery) and a local mock of the API. |
| 2 | `python -m sealed ask "Welche Mängel wurden gemeldet, wann, und wie hat die Vermieterin reagiert?" --folder examples/dossier --entities examples/entities.json --dry-run` | The **exact request** that would leave the machine, with every name replaced, plus the SHA-256 of the request bytes. No network call. |
| 3 | `python -m sealed demo` | Replay of the recorded run in `fixtures/run1/`: what was sent, the signature check, the restored answer, the receipt chain. All re-checked offline. |
| 4 | `python -m sealed verify fixtures/run1/0001` | Recomputes both hashes, recovers the signer from the signature, checks the receipt hash. |
| 5 | `python -m sealed attest fixtures/run1/0001` | The receipt's **stored** attestation report, checked offline: the Intel TDX quote's report data binds the signer and the nonce of that run, the GPU evidence carries the same nonce, the compose manifest matches `mr_config`: level `quote_binds_signer`. With `--network` (and `pip install dcap-qvl`) also the Intel quote signature and NVIDIA's verdict: level **`full`**. |

Python 3.10 or newer. Nothing to install: run the commands from the repository root.
Full attestation (Intel TDX, NVIDIA GPU) of all three receipts: `fixtures/attestation-check/2026-11-07_sealed_attest.txt`, explained in [`docs/ATTESTATION_CHECK.md`](docs/ATTESTATION_CHECK.md).
The sample case in `examples/` is **invented**.

## Status, stated plainly

- **Done and tested offline:** search, pseudonymiser with leak check, API client, signature verification, receipts with hash chain, CLI, replay.
- **Recorded live run on NEAR AI Cloud (31 Oct 2026):** `fixtures/run1/`, three questions on the invented sample case, model `Qwen/Qwen3.8-27B` in the **confidential** tier. All three signatures verify, the receipt chain is intact, and no listed name, AHV number, IBAN, e-mail or phone number was in any request. Cost of these three calls: about one US cent (3,875 input and 7,685 output tokens at USD 0.04 and 1.35 per million tokens). Attestation level of every receipt: `report_lists_signer`. **How it was recorded, honestly:** the first live run used a limit of 2,000 tokens; the model spends most of them on reasoning, so two answers came back cut off or empty. We raised the limit and improved the search, ran again, and answers 1 and 2 were good. Answer 3 (a request to draft legal reasoning) again ended empty after 6,000 reasoning tokens, so it was replaced by a simpler extraction question and asked with `--resume`. The two discarded attempts are not part of the chain; the receipts in `fixtures/run1/` are the ones listed here, unchanged.
- **Attestation:** at run time the tool fetches the attestation report with a fresh random nonce, checks that the signer of the answer is listed in it and stores the report in the receipt (`report_lists_signer`). Afterwards `python -m sealed attest <receipt>` checks that **stored** report: offline (standard library) that the TDX quote's report data binds the signer and the run's nonce, that the GPU evidence carries the same nonce and that the compose manifest matches `mr_config`; with `--network` also the Intel quote signature and TCB status (through `dcap-qvl`, as NEAR AI's official verifier does) and NVIDIA's verdict on the GPU evidence. On 7 Nov 2026 all three receipts reached level **`full`** with signer `0x835a…aa26`; a fresh report gave the same signer and level. Limits: NVIDIA's answer is read from its token without checking the token's signature (as in the official verifier); the Intel check needs the optional `dcap-qvl` and network. Details and the earlier run of the official verifier: [`docs/ATTESTATION_CHECK.md`](docs/ATTESTATION_CHECK.md).
- **Limits** of the pseudonymiser, of the TEE and of the whole approach: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Who it is for, and what comes next

- **Who:** lawyers, fiduciaries and advisors who want AI help on case files but cannot send client names to a cloud model.
- **What changes for them:** the names never leave the machine, and each answer comes with a receipt that anyone can check offline: both hashes, the signer, the hash chain and the attestation report stored with it.
- **Where it stands:** a command-line tool and a browser replay, with one recorded live run of three questions on an invented case. It is not a product yet, and the name replacement only covers what the user lists (see `docs/THREAT_MODEL.md`).
- **Next steps (not started):** (1) suggest names found in the dossier for the user to confirm, so fewer names are missed; (2) a simple desktop front end for people who do not use a command line; (3) export a receipt chain as one file for the case record.

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
               attest.py                 TDX quote parsing, full attestation check (attest)
               receipt.py, pipeline.py, cli.py
tests/         65 offline tests, mock of the NEAR AI API, crypto vectors
examples/      invented sample case, run_live.py
docs/          SPEC.md, NEARAI_API.md, THREAT_MODEL.md
fixtures/      model list snapshot (30 Oct 2026), run1/ (recorded live run)
web/           index.html (browser replay of run1), build.py, index.template.html
```

## Libraries and tools

- **Runtime:** Python standard library only (`urllib`, `sqlite3` with FTS5, `hashlib`, `json`, `re`). The cryptography (Keccak-256, secp256k1 recovery) is plain Python in `sealed/`, checked against `eth-account` vectors.
- **Browser replay (`web/`):** one self-contained HTML file. Its Keccak-256 and secp256k1 code is a JavaScript port of `sealed/keccak.py` and `sealed/secp256k1.py`; SHA-256 comes from the browser (WebCrypto). No third-party code, no network request.
- **Development:** `pytest`.
- **Service:** NEAR AI Cloud (OpenAI-compatible chat API, signature and attestation endpoints). Default model `Qwen/Qwen3.8-27B` (confidential tier in the model list of 30 Oct 2026).
- **Optional for `attest --network`:** `dcap-qvl` (Intel TDX quote verification with collateral from Intel PCS, the library NEAR AI's verifier uses) and NVIDIA's remote attestation service `nras.attestation.nvidia.com`.
- Reference for the verification format: `nearai/nearai-cloud-verifier` (MIT), used as documentation, not as code. Its output for our model is stored in `fixtures/attestation-check/`.

## AI assistance

Built with AI assistance, disclosed here:

- **Cursor (Composer model)** wrote the first implementation from a written specification (`docs/SPEC.md`).
- **Claude (Anthropic)** wrote the specification and the documents, reviewed the result, and fixed defects found in review (e-mail addresses cut apart by name replacement, receipts that would break on Windows line endings, a verification check that would have failed on real API responses, an overlong Keccak module (480 lines) replaced by a 60-line one).
- Correctness rests on tests, on `eth-account` as an independent reference for random inputs, and on the author's review. The author set the scope and decided what to build.

## Related project

The author has one other, independent hackathon project: **Terra matcher**, a non-custodial order matcher with a NEAR testnet escrow (track `defi`), submitted separately: https://github.com/archtum66-dev/terra-matcher

## Licence

**PolyForm Noncommercial License 1.0.0**, see `LICENSE`. Any noncommercial use is allowed. The author also explicitly permits the organizers and judges of NEAR HACKATHON to read, run, test and evaluate this repository. Commercial use needs a separate licence from the author: open an issue on this repository.

Required Notice: Copyright (c) 2026 Andreas Grobe

Versions up to commit `6b288c1` (7 November 2026) were published under the MIT License; copies obtained under those terms keep them.

Not legal advice; the tool is an aid for analysis and drafting.
