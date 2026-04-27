"""Artifact-based run comparison service."""

from __future__ import annotations

from pathlib import Path

from mini_llm_eval.core.exceptions import ComparisonError
from mini_llm_eval.core.types import CaseResultArtifact, RunMeta, RunSummaryPayload, TagPassRatePayload
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import CompareResult, CompareSummary, RunStatus, TagCompareResult


class Comparator:
    """Compare two completed or archived runs from artifact files."""

    def __init__(self, file_storage: FileStorage) -> None:
        self.file_storage = file_storage

    def compare_runs(self, base_run_id: str, candidate_run_id: str) -> CompareResult:
        """Compare two runs using their exported artifact files."""

        base_meta, base_cases = self._load_run_artifacts(base_run_id)
        candidate_meta, candidate_cases = self._load_run_artifacts(candidate_run_id)
        return self.compare_artifacts(base_meta, base_cases, candidate_meta, candidate_cases)

    def compare_artifacts(
        self,
        base_meta: RunMeta,
        base_cases: list[CaseResultArtifact],
        candidate_meta: RunMeta,
        candidate_cases: list[CaseResultArtifact],
    ) -> CompareResult:
        """Compare two runs from already-loaded artifact payloads."""

        base_summary = base_meta.get("summary")
        candidate_summary = candidate_meta.get("summary")
        if base_summary is None:
            raise ComparisonError(f"Base run {base_meta['run_id']} has no summary")
        if candidate_summary is None:
            raise ComparisonError(f"Candidate run {candidate_meta['run_id']} has no summary")

        base_case_map = {row["case_id"]: row for row in base_cases}
        candidate_case_map = {row["case_id"]: row for row in candidate_cases}
        shared_case_ids = sorted(set(base_case_map) & set(candidate_case_map))

        newly_failed_case_ids: list[str] = []
        fixed_case_ids: list[str] = []
        newly_errored_case_ids: list[str] = []

        for case_id in shared_case_ids:
            base_case = base_case_map[case_id]
            candidate_case = candidate_case_map[case_id]
            base_passed = _is_passed_case(base_case)
            candidate_passed = _is_passed_case(candidate_case)
            base_errored = _is_error_case(base_case)
            candidate_errored = _is_error_case(candidate_case)

            if base_passed and not candidate_passed:
                newly_failed_case_ids.append(case_id)
            if not base_passed and candidate_passed:
                fixed_case_ids.append(case_id)
            if not base_errored and candidate_errored:
                newly_errored_case_ids.append(case_id)

        tag_results = self._build_tag_results(base_summary, candidate_summary)
        summary = CompareSummary(
            base_pass_rate=base_summary["pass_rate"],
            candidate_pass_rate=candidate_summary["pass_rate"],
            pass_rate_delta=candidate_summary["pass_rate"] - base_summary["pass_rate"],
            base_passed_cases=base_summary["passed_cases"],
            candidate_passed_cases=candidate_summary["passed_cases"],
            passed_delta=candidate_summary["passed_cases"] - base_summary["passed_cases"],
            base_failed_cases=base_summary["failed_cases"],
            candidate_failed_cases=candidate_summary["failed_cases"],
            failed_delta=candidate_summary["failed_cases"] - base_summary["failed_cases"],
            base_error_cases=base_summary["error_cases"],
            candidate_error_cases=candidate_summary["error_cases"],
            error_delta=candidate_summary["error_cases"] - base_summary["error_cases"],
            base_avg_latency_ms=base_summary["avg_latency_ms"],
            candidate_avg_latency_ms=candidate_summary["avg_latency_ms"],
            avg_latency_delta_ms=candidate_summary["avg_latency_ms"] - base_summary["avg_latency_ms"],
            base_p95_latency_ms=base_summary["p95_latency_ms"],
            candidate_p95_latency_ms=candidate_summary["p95_latency_ms"],
            p95_latency_delta_ms=candidate_summary["p95_latency_ms"] - base_summary["p95_latency_ms"],
            shared_case_count=len(shared_case_ids),
            base_only_case_ids=sorted(set(base_case_map) - set(candidate_case_map)),
            candidate_only_case_ids=sorted(set(candidate_case_map) - set(base_case_map)),
            newly_failed_case_ids=newly_failed_case_ids,
            fixed_case_ids=fixed_case_ids,
            newly_errored_case_ids=newly_errored_case_ids,
        )

        return CompareResult(
            base_run_id=base_meta["run_id"],
            candidate_run_id=candidate_meta["run_id"],
            base_status=RunStatus(base_meta["status"]),
            candidate_status=RunStatus(candidate_meta["status"]),
            summary=summary,
            tag_results=tag_results,
        )

    def _load_run_artifacts(self, run_id: str) -> tuple[RunMeta, list[CaseResultArtifact]]:
        run_dir = Path(self.file_storage.output_dir) / run_id
        meta_path = run_dir / "meta.json"
        cases_path = run_dir / "case_results.jsonl"

        if not meta_path.exists():
            raise ComparisonError(f"Run meta artifact not found: {meta_path}")
        if not cases_path.exists():
            raise ComparisonError(f"Run case-results artifact not found: {cases_path}")

        return self.file_storage.read_json(str(meta_path)), self.file_storage.read_json_lines(str(cases_path))

    @staticmethod
    def _build_tag_results(
        base_summary: RunSummaryPayload,
        candidate_summary: RunSummaryPayload,
    ) -> dict[str, TagCompareResult]:
        all_tags = sorted(set(base_summary["tag_pass_rates"]) | set(candidate_summary["tag_pass_rates"]))
        results: dict[str, TagCompareResult] = {}
        for tag in all_tags:
            base_tag = _get_tag_rate(base_summary["tag_pass_rates"], tag)
            candidate_tag = _get_tag_rate(candidate_summary["tag_pass_rates"], tag)
            results[tag] = TagCompareResult(
                tag=tag,
                base_total=base_tag["total"],
                candidate_total=candidate_tag["total"],
                base_pass_rate=base_tag["pass_rate"],
                candidate_pass_rate=candidate_tag["pass_rate"],
                pass_rate_delta=candidate_tag["pass_rate"] - base_tag["pass_rate"],
            )
        return results


def _get_tag_rate(tag_rates: dict[str, TagPassRatePayload], tag: str) -> TagPassRatePayload:
    return tag_rates.get(tag, {"total": 0, "passed": 0, "pass_rate": 0.0})


def _is_error_case(case_row: CaseResultArtifact) -> bool:
    return case_row["case_status"] == "error"


def _is_passed_case(case_row: CaseResultArtifact) -> bool:
    if case_row["case_status"] != "completed":
        return False
    eval_results = case_row["eval_results"]
    return bool(eval_results) and all(
        item["passed"] and not item.get("error")
        for item in eval_results.values()
    )
