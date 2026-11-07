# Attestation check with NEAR AI's official verifier

**Date:** 31 Oct 2026, 10:25 UTC · **Model:** `Qwen/Qwen3.8-27B` (confidential tier) · **Tool:** `nearai/nearai-cloud-verifier` (MIT), commit `94554726fd54`, run as `python py/model_verifier.py --model Qwen/Qwen3.8-27B` with **no API key**.
Raw output (only the public compose manifests are cut): [`fixtures/attestation-check/2026-10-31_model_verifier_output.txt`](../fixtures/attestation-check/2026-10-31_model_verifier_output.txt).

## Result for the model attestation

| Check | Result |
|---|---|
| Intel TDX quote | verified, status `UpToDate`, no advisories |
| Report data binds the signing address | **True** |
| Report data embeds our request nonce (fresh, random) | **True** |
| NVIDIA GPU attestation | payload nonce matches; NVIDIA verdict **True** |
| Compose manifest | its SHA-256 equals `mr_config` of the verified quote: **True** |
| Sigstore provenance of the container images | the search pages exist (HTTP 200); this only shows that entries are reachable |
| Gateway attestation | same checks passed (TDX quote verified, binds address and nonce, `mr_config` matches) |

**Attested signing address:** `0x835ab53d20294ef795906dff21ae4c045336aa26`.
This is the signer in `signature.json` of **all three** recorded receipts in `fixtures/run1/`.

## What this shows, and what it does not

- **Shows:** at the time of the check, the key that signed our answers is bound to a genuine Intel TDX enclave and an NVIDIA GPU attestation, and to a published docker-compose manifest.
- **Does not show:** that this was checked at the second of the run. The verifier asks for a fresh report; it does not check a stored one. The recorded answers were signed earlier on the same day with the same address.
- **Does not show:** that the container images are what the source code says. The Sigstore step only checks that entries can be opened.
- **Sealed Dossier itself** (standard library only) still checks only that the signer is listed in the report, so each receipt says `report_lists_signer`. The full check is the separate run documented here.

## Repeat it

```
git clone https://github.com/nearai/nearai-cloud-verifier.git
cd nearai-cloud-verifier
pip install -r requirements.txt
python py/model_verifier.py --model Qwen/Qwen3.8-27B
python -m sealed verify fixtures/run1/0001      # in this repository: prints the receipt's signer
```

Compare the `Signing address` under "Model attestations" with the `signer` line of `sealed verify`.
Keys can rotate: if the addresses differ, make a new short run and check again.

## 7 Nov 2026: Sealed Dossier checks the stored reports itself

`python -m sealed attest <receipt> --network` (module `sealed/attest.py`) checks the report **stored in each receipt**, the one fetched with the run's own nonce on 31 Oct 2026, not only a fresh one:

| Check | How | 0001 | 0002 | 0003 |
|---|---|---|---|---|
| Report data binds the signer | TDX quote, first 32 bytes of report data = padded signing address | ok | ok | ok |
| Report data embeds the run's nonce | last 32 bytes = `request_nonce` of the stored report | ok | ok | ok |
| GPU evidence uses that nonce | `nvidia_payload.nonce` | ok | ok | ok |
| Compose manifest | `01` + SHA-256(app_compose) = `mr_config_id` of the quote; `mr_td` = TCB info | ok | ok | ok |
| Intel quote signature and TCB | `dcap-qvl` with fresh collateral (network) | `UpToDate` | `UpToDate` | `UpToDate` |
| NVIDIA verdict | NVIDIA remote attestation of the stored GPU evidence (network) | True | True | True |

**Level `full` for all three receipts, signer `0x835ab53d20294ef795906dff21ae4c045336aa26`.** A fresh report (`--model Qwen/Qwen3.8-27B`, own nonce) gave the same signer and level. Output: [`fixtures/attestation-check/2026-11-07_sealed_attest.txt`](../fixtures/attestation-check/2026-11-07_sealed_attest.txt).

- The offline part needs only the standard library and runs in the tests (`tests/test_attest.py`), including tampered signer, nonce and compose manifest.
- Still not shown: that the container images are what the source says (Sigstore is not checked here), and NVIDIA's token signature (read like the official verifier does).
