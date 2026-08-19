from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import unittest

from synthran.privacy import (
    Finding,
    PrivacyError,
    TextRedactor,
    redact_file,
    report_findings,
    scan_text,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAFE_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "safe.txt"


class PrivacyScannerTests(unittest.TestCase):
    def test_detects_provider_token_without_returning_value(self) -> None:
        value = "ghp_" + ("x" * 36)
        findings = scan_text(value, path="fixture.txt", identifiers=())
        self.assertEqual(["provider-token"], [item.rule for item in findings])
        self.assertFalse(hasattr(findings[0], "value"))

    def test_detects_machine_specific_paths(self) -> None:
        windows_path = "C:" + "\\" + "Users" + "\\" + "local-person" + "\\project"
        posix_path = "/" + "home" + "/" + "local-person" + "/project"
        findings = scan_text(
            f"{windows_path}\n{posix_path}",
            path="fixture.txt",
            identifiers=(),
        )
        self.assertEqual(
            {"windows-absolute-path", "posix-user-home"},
            {item.rule for item in findings},
        )

    def test_detects_explicit_local_username(self) -> None:
        findings = scan_text(
            "owner is local-person",
            path="fixture.txt",
            identifiers=("local-person",),
        )
        self.assertEqual(["local-username"], [item.rule for item in findings])

    def test_allows_ci_secret_expression_placeholder(self) -> None:
        expression = "${" + "{ github.token }}"
        key = "GITHUB_" + "TOKEN"
        findings = scan_text(
            f"{key}: {expression}",
            path="workflow.yml",
            identifiers=(),
        )
        self.assertEqual([], findings)

    def test_json_numeric_measurements_are_not_mistaken_for_imsi(self) -> None:
        timestamp = int("1234567" + "89012345")
        counter = int("6636640" + "20000000")
        text = json.dumps(
            {"timestamp_ns": timestamp, "counter": counter},
            indent=2,
        ) + "\n"
        findings = scan_text(
            text,
            path="results/campaign-analysis.json",
            identifiers=(),
        )
        self.assertEqual([], findings)

    def test_json_string_imsi_is_still_blocked(self) -> None:
        imsi = "0010100" + "00000100"
        text = json.dumps({"imsi": imsi}, indent=2) + "\n"
        findings = scan_text(text, path="fixture.json", identifiers=())
        self.assertEqual(["imsi"], [item.rule for item in findings])

    def test_plain_text_imsi_is_still_blocked(self) -> None:
        imsi = "0010100" + "00000100"
        findings = scan_text(
            f"subscriber {imsi}",
            path="fixture.txt",
            identifiers=(),
        )
        self.assertEqual(["imsi"], [item.rule for item in findings])

    def test_report_omits_detected_content(self) -> None:
        output = StringIO()
        status = report_findings(
            [Finding("provider-token", "fixture.txt", 4)],
            output,
        )
        self.assertEqual(1, status)
        expected = "provider-" + "token" + ": fixture.txt:4"
        self.assertIn(expected, output.getvalue())
        self.assertIn("intentionally omitted", output.getvalue())


class TextRedactorTests(unittest.TestCase):
    def test_redacts_paths_usernames_and_private_addresses_stably(self) -> None:
        home = "C:" + "\\" + "Users" + "\\" + "local-person"
        text = (
            f"{home} local-person "
            "10.20.30.40 10.20.30.41 10.20.30.40 "
            "192.0.2.10 fd00::1"
        )
        redacted = TextRedactor(identifiers=("local-person",)).redact(text)
        self.assertNotIn("local-person", redacted)
        self.assertIn("<USER_HOME>", redacted)
        self.assertEqual(2, redacted.count("<PRIVATE_IPV4_1>"))
        self.assertIn("<PRIVATE_IPV4_2>", redacted)
        self.assertIn("192.0.2.10", redacted)
        self.assertIn("<PRIVATE_IPV6_1>", redacted)

    def test_redact_file_refuses_in_place_rewrite(self) -> None:
        with self.assertRaisesRegex(PrivacyError, "must differ"):
            redact_file(SAFE_FIXTURE, SAFE_FIXTURE, dry_run=False, output=StringIO())

    def test_redact_file_dry_run_does_not_write(self) -> None:
        destination = REPOSITORY_ROOT / "tests" / "fixtures" / "dry-run-output.txt"
        self.assertFalse(destination.exists())
        redact_file(SAFE_FIXTURE, destination, dry_run=True, output=StringIO())
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
