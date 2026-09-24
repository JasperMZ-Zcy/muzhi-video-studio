#!/usr/bin/env python3
"""Stdlib regression tests for generation_ledger.py.

Run with: python scripts/test_generation_ledger.py
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import generation_ledger as ledger


class GenerationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        self.write("inputs/source.wav", b"original source")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, contents: bytes) -> Path:
        target = self.project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        return target

    def reserve(self, *, kind: str = "image", key: str = "cover-v1", estimate: str = "2", budget: str | None = "10", unit: str = "credits", input_file: str = "inputs/source.wav", retry_quote: str | None = None, provider: str = "Example Provider", model: str = "Model-1") -> dict:
        return ledger.reserve(
            self.project,
            kind,
            key,
            [input_file],
            provider,
            model,
            estimate,
            budget,
            unit,
            "Create the approved scoped asset",
            retry_quote,
        )

    def attach(self, reservation: dict, job: str = "provider-job-1") -> dict:
        return ledger.attach(self.project, reservation["reservation"]["id"], job)

    def finish_success(self, reservation: dict, output: str = "output/result.bin", actual_cost: str | None = None) -> dict:
        self.write(output, b"result bytes")
        return ledger.finish(self.project, reservation["reservation"]["id"], "succeeded", output, actual_cost)

    def test_reserve_is_idempotent_without_double_reservation(self) -> None:
        first = self.reserve()
        second = self.reserve()
        self.assertEqual(first["action"], "reserved")
        self.assertEqual(second["action"], "reserved_existing")
        self.assertFalse(second["changed"])
        self.assertEqual(len(ledger.status(self.project)["entries"]), 1)

    def test_pending_attached_job_resumes_without_another_reservation(self) -> None:
        first = self.reserve()
        self.attach(first)
        resumed = self.reserve()
        self.assertEqual(resumed["action"], "resume")
        self.assertFalse(resumed["changed"])
        self.assertEqual(len(ledger.status(self.project)["entries"]), 1)

    def test_changed_success_output_rejects_reuse(self) -> None:
        first = self.reserve()
        self.attach(first)
        self.finish_success(first)
        self.write("output/result.bin", b"changed after success")
        with self.assertRaises(ledger.HashDriftError):
            self.reserve()
        repaired = self.reserve(retry_quote="The prior output drifted; retry this exact asset once.")
        self.assertEqual(repaired["action"], "retry_reserved")

    def test_budget_refusal_and_missing_positive_budget(self) -> None:
        with self.assertRaises(ledger.BudgetError):
            self.reserve(estimate="6", budget="5")
        with self.assertRaises(ledger.ValidationError):
            self.reserve(estimate="1", budget=None)
        self.assertFalse((self.project / "artifacts" / "generation-ledger.json").exists())

    def test_unknown_cost_is_charged_at_estimate_not_zero(self) -> None:
        first = self.reserve(estimate="3", budget="5")
        self.attach(first)
        ledger.finish(self.project, first["reservation"]["id"], "unknown")
        saved = ledger.status(self.project)
        self.assertEqual(saved["costs"]["estimated_for_unknown"], "3")
        with self.assertRaises(ledger.BudgetError):
            self.reserve(key="cover-v2", estimate="3", budget="5")

    def test_failed_attempt_requires_explicit_retry_quote(self) -> None:
        first = self.reserve()
        self.attach(first)
        ledger.finish(self.project, first["reservation"]["id"], "failed")
        with self.assertRaises(ledger.ValidationError):
            self.reserve()
        retried = self.reserve(retry_quote="Retry this exact failed job once; extra cost is approved.")
        self.assertEqual(retried["action"], "retry_reserved")
        self.assertEqual(len(ledger.status(self.project)["entries"]), 2)

    def test_asr_completed_input_reuses_across_different_keys(self) -> None:
        first = self.reserve(kind="asr", key="formal-asr-v1", estimate="1")
        self.attach(first)
        self.finish_success(first, "output/transcript.json")
        reused = self.reserve(kind="asr", key="formal-asr-v2", estimate="1", provider="Different provider", model="new-asr-model")
        self.assertEqual(reused["action"], "reuse")
        self.assertEqual(len(ledger.status(self.project)["entries"]), 1)

    def test_input_hash_drift_creates_a_new_asr_reservation(self) -> None:
        first = self.reserve(kind="asr", key="formal-asr-v1", estimate="1")
        self.attach(first)
        self.finish_success(first, "output/transcript.json")
        self.write("inputs/source.wav", b"changed source")
        fresh = self.reserve(kind="asr", key="formal-asr-v2", estimate="1", budget="3")
        self.assertEqual(fresh["action"], "reserved")
        self.assertEqual(len(ledger.status(self.project)["entries"]), 2)

    def test_projects_are_isolated(self) -> None:
        first = self.reserve()
        self.attach(first)
        self.finish_success(first)
        other = Path(self.temporary.name) / "other-project"
        other.mkdir()
        (other / "inputs").mkdir()
        (other / "inputs" / "source.wav").write_bytes(b"original source")
        fresh = ledger.reserve(
            other,
            "image",
            "cover-v1",
            ["inputs/source.wav"],
            "Example Provider",
            "Model-1",
            "2",
            "10",
            "credits",
            "Create a separate project asset",
        )
        self.assertEqual(fresh["action"], "reserved")
        self.assertEqual(len(ledger.status(other)["entries"]), 1)
        self.assertEqual(len(ledger.status(self.project)["entries"]), 1)

    def test_hash_only_outputs_are_not_accepted_without_attach(self) -> None:
        first = self.reserve()
        self.write("output/result.bin", b"result bytes")
        with self.assertRaises(ledger.ValidationError):
            ledger.finish(self.project, first["reservation"]["id"], "succeeded", "output/result.bin")

    def test_zero_cost_none_unit_and_relative_path_protection(self) -> None:
        zero = self.reserve(estimate="0", budget="0", unit="none")
        self.assertEqual(zero["action"], "reserved")
        with self.assertRaises(ledger.ValidationError):
            self.reserve(key="paid", estimate="1", budget="10", unit="none")
        with self.assertRaises(ledger.ValidationError):
            ledger.plan(
                self.project,
                "image",
                "outside",
                ["../outside.bin"],
                "Provider",
                "Model",
                "0",
                "0",
                "none",
            )

    def test_default_outstanding_limit_is_two_without_blocking_resume(self) -> None:
        first = self.reserve(key="cover-v1", estimate="0", budget="0", unit="none")
        second = self.reserve(key="cover-v2", estimate="0", budget="0", unit="none")
        resumed = self.reserve(key="cover-v1", estimate="0", budget="0", unit="none")
        self.assertEqual(resumed["action"], "reserved_existing")
        with self.assertRaises(ledger.BudgetError):
            self.reserve(key="cover-v3", estimate="0", budget="0", unit="none")
        self.assertEqual(len(ledger.status(self.project)["entries"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
