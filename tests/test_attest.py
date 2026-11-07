"""Attestation checks on the reports stored in the recorded run (offline, no network)."""

from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sealed import attest
from sealed.cli import main

RUN = Path(__file__).resolve().parent.parent / "fixtures" / "run1"


def _model_attestation(receipt: str) -> dict:
    report = json.loads((RUN / receipt / "attestation.json").read_text(encoding="utf-8"))
    return report["model_attestations"][0]


class AttestTests(unittest.TestCase):
    def test_parse_tdx_quote_fields(self) -> None:
        quote = attest.parse_tdx_quote(bytes.fromhex(_model_attestation("0001")["intel_quote"]))
        self.assertEqual(quote["version"], 4)
        self.assertEqual(quote["tee_type"], 0x81)
        self.assertEqual(len(bytes.fromhex(quote["report_data"])), 64)
        self.assertEqual(len(bytes.fromhex(quote["mr_config_id"])), 48)
        with self.assertRaises(ValueError):
            attest.parse_tdx_quote(b"\x00" * 100)

    def test_stored_reports_bind_signer_and_nonce(self) -> None:
        for receipt in ("0001", "0002", "0003"):
            signer = json.loads((RUN / receipt / "receipt.json").read_text(encoding="utf-8"))[
                "signing_address"
            ]
            res = attest.check_attestation(_model_attestation(receipt))
            self.assertEqual(res["level"], "quote_binds_signer", receipt)
            self.assertTrue(all(res["checks"].values()), receipt)
            self.assertEqual(res["signer"].lower(), signer.lower())

    def test_tampering_is_detected(self) -> None:
        item = _model_attestation("0001")
        wrong_signer = copy.deepcopy(item)
        wrong_signer["signing_address"] = "0x" + "11" * 20
        res = attest.check_attestation(wrong_signer)
        self.assertFalse(res["checks"]["report_data_binds_signer"])
        self.assertEqual(res["level"], "failed")
        wrong_compose = copy.deepcopy(item)
        wrong_compose["info"]["tcb_info"]["app_compose"] += " "
        self.assertFalse(attest.check_attestation(wrong_compose)["checks"]["compose_matches_mr_config"])
        wrong_nonce = attest.check_attestation(item, request_nonce="00" * 32)
        self.assertFalse(wrong_nonce["checks"]["report_data_embeds_nonce"])

    def test_cli_attest_offline(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["attest", str(RUN / "0001")])
        self.assertEqual(code, 0)
        self.assertIn("level   quote_binds_signer", out.getvalue())


if __name__ == "__main__":
    unittest.main()
