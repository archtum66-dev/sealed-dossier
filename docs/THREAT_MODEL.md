# Threat model: what Sealed Dossier protects, and what it does not

Sealed Dossier sends **excerpts of a dossier** to a **language model that runs inside a trusted execution environment (TEE)** and gives you back **proof of what was exchanged**. This page states the limits, so that nobody relies on more than the tool does.

## What is protected

| Asset | How | Where you can check it |
|---|---|---|
| **Names, addresses, case numbers, IDs** in the dossier | Replaced by placeholders (`[PERSON_1]`, `[CASE_1]`, ...) **before** anything leaves the machine. A leak check refuses to send if a listed entity or a built-in pattern is still in the text. | `sealed ask --dry-run` prints the exact request; `tests/test_pseudo.py`, `tests/test_pipeline.py` |
| **Question and excerpts** while the model reads them | The model runs on NEAR AI Cloud in a TEE; the operator of the cloud is meant not to see prompts or answers. | NEAR AI attestation (see below) |
| **Integrity of the exchange** | The service signs the hash of the exact request and of the exact response. The tool recomputes both hashes and recovers the signer from the signature. | `sealed verify <receipt>` works **offline** |
| **Order of the work log** | Each receipt contains the hash of the previous one. A changed receipt, or one removed from the middle of the chain, breaks it. Removing the newest receipt cannot be detected. | `sealed chain <dir>` |

## What is NOT protected

**1. Names you did not list.**
The pseudonymiser is **rule-based**: it knows the entities in your `entities.json` and a few patterns (AHV number, Swiss IBAN, e-mail, phone, case number).
A name that is missing from the list **leaves the machine in clear text**.
Mitigation: run `--dry-run` first and read the request. Nothing else can replace that look.

**2. Facts that identify the case without a name.**
A rare event, an amount, a date and a small village can point to one case. Placeholders do not hide that.
Send as few excerpts as needed (`--k`).

**3. Which parts of the dossier matter.**
The excerpts you send show what your question is about. The TEE protects them from the operator; it does not make them disappear from the model.

**4. The meaning of the attestation.**
`sealed` checks that the signature matches the signing address and that the hashes match. It also checks, **structurally**, whether a returned attestation report names that address.
It does **not** verify the Intel TDX quote or the NVIDIA GPU evidence itself, and it does not check the nonce binding.
The receipt says so: the level is `report_lists_signer`, never "verified". The full check is NEAR AI's official verifier (`nearai/nearai-cloud-verifier`); it fetches a fresh report and does not check a stored one. Its result for the signer of the recorded run (31 Oct 2026) is in `docs/ATTESTATION_CHECK.md`. It shows the signing key is bound to an Intel TDX enclave and an NVIDIA GPU attestation at the time of the check, not at the second of each run.
Also: trust in a TEE is trust in the **hardware vendors** and in the **published measurements**. It is not trust in nothing.

**5. Incognito models.**
Some models on the platform are served through a third party with a weaker promise. `sealed` **refuses** them unless you pass `--allow-incognito`. The receipt records the tier.

**6. A compromised computer.**
Anyone with access to your machine reads the dossier, `excerpts.txt` and `answer.md`. These two files are **local only** and must not be shared. Receipts without these two files contain only placeholders.

**7. Wrong answers.**
Language models make mistakes and invent sources. The prompt asks for citations `[S1]`, `[S2]` that point to your excerpts, and the answer shows which file and chunk each one is. **Check every citation.** The tool is an aid for analysis and drafting; it gives **no legal advice**.

**8. Professional secrecy.**
Lawyers in Switzerland are bound by **Art. 321 StGB** and **Art. 13 BGFA**. Using any external service is the lawyer's decision and responsibility (client consent, instructions, contract with the provider). **A TEE and a receipt do not decide that question.**

## Secrets

- The API key is read **only** from the environment variable `NEARAI_API_KEY`. In `examples/run_live.py` it may also come from a key file that the user created outside the repository (`NEARAI_API_KEY_FILE`, default `nearai-key.txt` in the home folder) or be typed or pasted into a prompt (kept in memory, screen cleared afterwards). The tool never writes the key anywhere, never prints it, and it is never part of a receipt or an error message.
- The repository contains **no real data**: the sample case is invented, and the test keys are public sample keys that protect nothing.

## Out of scope for this version

- Anchoring the receipt chain on a blockchain (a timestamp from a third party). The chain proves order, not time.
- Verifying TDX and GPU evidence inside this tool (use the official verifier).
- Encrypted storage of the local index and receipts (use disk encryption).
- OCR and PDF extraction: the tool reads plain text files (`.txt`, `.md`).
