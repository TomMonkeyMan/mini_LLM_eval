"""Artifact-driven report rendering."""

from __future__ import annotations

from html import escape
from pathlib import Path

from mini_llm_eval.core.exceptions import ReportError
from mini_llm_eval.core.types import CaseResultArtifact, RunMeta
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import CompareResult


class Reporter:
    """Render run and compare artifacts into Markdown or HTML reports."""

    def __init__(self, file_storage: FileStorage) -> None:
        self.file_storage = file_storage

    def load_run_artifacts(self, target: str | Path) -> tuple[RunMeta, list[CaseResultArtifact]]:
        run_dir = Path(target)
        meta_path = run_dir / "meta.json"
        cases_path = run_dir / "case_results.jsonl"
        if not meta_path.exists():
            raise ReportError(f"Run meta artifact not found: {meta_path}")
        if not cases_path.exists():
            raise ReportError(f"Run case-results artifact not found: {cases_path}")
        return self.file_storage.read_json(str(meta_path)), self.file_storage.read_json_lines(str(cases_path))

    def load_run_artifacts_from_run_id(
        self,
        run_id: str,
    ) -> tuple[RunMeta, list[CaseResultArtifact]]:
        return self.load_run_artifacts(Path(self.file_storage.output_dir) / run_id)

    def render_run_report(
        self,
        meta: RunMeta,
        case_results: list[CaseResultArtifact],
        *,
        format: str = "markdown",
    ) -> str:
        if format == "markdown":
            return _render_run_markdown(meta, case_results)
        if format == "html":
            return _render_run_html(meta, case_results)
        raise ReportError(f"Unsupported report format: {format}")

    def render_compare_report(self, result: CompareResult, *, format: str = "markdown") -> str:
        if format == "markdown":
            return _render_compare_markdown(result)
        if format == "html":
            return _render_compare_html(result)
        raise ReportError(f"Unsupported report format: {format}")


def _render_run_markdown(meta: RunMeta, case_results: list[CaseResultArtifact]) -> str:
    summary = meta.get("summary")
    lines = [
        f"# Run Report: {meta['run_id']}",
        "",
        "## Overview",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Status | {meta['status']} |",
        f"| Dataset | {meta['dataset_path']} |",
        f"| Provider | {meta['provider_name']} |",
        f"| Created | {meta['created_at']} |",
        f"| Started | {meta['started_at'] or '-'} |",
        f"| Finished | {meta['finished_at'] or '-'} |",
        f"| Case Results | {meta['case_result_count']} |",
    ]

    if summary is not None:
        lines.extend(
            [
                "",
                "## Summary",
                "",
                "| Metric | Value |",
                "| --- | --- |",
                f"| Total Cases | {summary['total_cases']} |",
                f"| Passed | {summary['passed_cases']} |",
                f"| Failed | {summary['failed_cases']} |",
                f"| Errors | {summary['error_cases']} |",
                f"| Pass Rate | {summary['pass_rate']:.2%} |",
                f"| Avg Latency | {summary['avg_latency_ms']:.2f} ms |",
                f"| P95 Latency | {summary['p95_latency_ms']:.2f} ms |",
            ]
        )
        if summary["tag_pass_rates"]:
            lines.extend(
                [
                    "",
                    "## Tag Pass Rates",
                    "",
                    "| Tag | Passed | Total | Pass Rate |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for tag, stats in sorted(summary["tag_pass_rates"].items()):
                lines.append(
                    f"| {tag} | {stats['passed']} | {stats['total']} | {stats['pass_rate']:.2%} |"
                )

    lines.extend(
        [
            "",
            "## Failed Or Errored Cases",
            "",
            "| Case ID | Status | Provider Status | Error | Failed Evaluators |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    failed_rows = 0
    for row in case_results:
        failed_evaluators = [
            name
            for name, item in row["eval_results"].items()
            if (not item["passed"]) or item.get("error")
        ]
        has_failure = row["case_status"] != "completed" or bool(failed_evaluators)
        if not has_failure:
            continue
        failed_rows += 1
        error_message = (row["error_message"] or "-").replace("|", "\\|")
        lines.append(
            f"| {row['case_id']} | {row['case_status']} | {row['provider_status']} | "
            f"{error_message} | "
            f"{', '.join(failed_evaluators) or '-'} |"
        )
    if failed_rows == 0:
        lines.append("| - | - | - | - | - |")

    return "\n".join(lines) + "\n"


def _render_compare_markdown(result: CompareResult) -> str:
    summary = result.summary
    lines = [
        f"# Compare Report: {result.base_run_id} -> {result.candidate_run_id}",
        "",
        "## Summary",
        "",
        "| Metric | Base | Candidate | Delta |",
        "| --- | --- | --- | --- |",
        f"| Pass Rate | {summary.base_pass_rate:.2%} | {summary.candidate_pass_rate:.2%} | {summary.pass_rate_delta:+.2%} |",
        f"| Passed | {summary.base_passed_cases} | {summary.candidate_passed_cases} | {summary.passed_delta:+d} |",
        f"| Failed | {summary.base_failed_cases} | {summary.candidate_failed_cases} | {summary.failed_delta:+d} |",
        f"| Errors | {summary.base_error_cases} | {summary.candidate_error_cases} | {summary.error_delta:+d} |",
        f"| Avg Latency | {summary.base_avg_latency_ms:.2f} ms | {summary.candidate_avg_latency_ms:.2f} ms | {summary.avg_latency_delta_ms:+.2f} ms |",
        f"| P95 Latency | {summary.base_p95_latency_ms:.2f} ms | {summary.candidate_p95_latency_ms:.2f} ms | {summary.p95_latency_delta_ms:+.2f} ms |",
    ]

    if result.tag_results:
        lines.extend(
            [
                "",
                "## Tag Changes",
                "",
                "| Tag | Base | Candidate | Delta |",
                "| --- | --- | --- | --- |",
            ]
        )
        for tag_result in sorted(result.tag_results.values(), key=lambda item: item.tag):
            lines.append(
                f"| {tag_result.tag} | {tag_result.base_pass_rate:.2%} | "
                f"{tag_result.candidate_pass_rate:.2%} | {tag_result.pass_rate_delta:+.2%} |"
            )

    lines.extend(
        [
            "",
            "## Case Changes",
            "",
            f"- Newly Failed: {_render_case_list(summary.newly_failed_case_ids)}",
            f"- Fixed: {_render_case_list(summary.fixed_case_ids)}",
            f"- Newly Errored: {_render_case_list(summary.newly_errored_case_ids)}",
            f"- Base Only: {_render_case_list(summary.base_only_case_ids)}",
            f"- Candidate Only: {_render_case_list(summary.candidate_only_case_ids)}",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_run_html(meta: RunMeta, case_results: list[CaseResultArtifact]) -> str:
    summary = meta.get("summary")
    sections = [
        _html_page_open(f"Run Report: {meta['run_id']}"),
        f"<h1>Run Report: {escape(meta['run_id'])}</h1>",
        "<h2>Overview</h2>",
        _html_key_value_table(
            [
                ("Status", meta["status"]),
                ("Dataset", meta["dataset_path"]),
                ("Provider", meta["provider_name"]),
                ("Created", meta["created_at"]),
                ("Started", meta["started_at"] or "-"),
                ("Finished", meta["finished_at"] or "-"),
                ("Case Results", str(meta["case_result_count"])),
            ]
        ),
    ]

    if summary is not None:
        sections.extend(
            [
                "<h2>Summary</h2>",
                _html_key_value_table(
                    [
                        ("Total Cases", str(summary["total_cases"])),
                        ("Passed", str(summary["passed_cases"])),
                        ("Failed", str(summary["failed_cases"])),
                        ("Errors", str(summary["error_cases"])),
                        ("Pass Rate", f"{summary['pass_rate']:.2%}"),
                        ("Avg Latency", f"{summary['avg_latency_ms']:.2f} ms"),
                        ("P95 Latency", f"{summary['p95_latency_ms']:.2f} ms"),
                    ]
                ),
            ]
        )
        if summary["tag_pass_rates"]:
            tag_rows = [
                [
                    tag,
                    str(stats["passed"]),
                    str(stats["total"]),
                    f"{stats['pass_rate']:.2%}",
                ]
                for tag, stats in sorted(summary["tag_pass_rates"].items())
            ]
            sections.extend(
                [
                    "<h2>Tag Pass Rates</h2>",
                    _html_table(["Tag", "Passed", "Total", "Pass Rate"], tag_rows),
                ]
            )

    failed_rows: list[list[str]] = []
    for row in case_results:
        failed_evaluators = [
            name
            for name, item in row["eval_results"].items()
            if (not item["passed"]) or item.get("error")
        ]
        has_failure = row["case_status"] != "completed" or bool(failed_evaluators)
        if has_failure:
            failed_rows.append(
                [
                    row["case_id"],
                    row["case_status"],
                    row["provider_status"],
                    row["error_message"] or "-",
                    ", ".join(failed_evaluators) or "-",
                ]
            )
    if not failed_rows:
        failed_rows = [["-", "-", "-", "-", "-"]]
    sections.extend(
        [
            "<h2>Failed Or Errored Cases</h2>",
            _html_table(
                ["Case ID", "Status", "Provider Status", "Error", "Failed Evaluators"],
                failed_rows,
            ),
            _html_page_close(),
        ]
    )
    return "\n".join(sections)


def _render_compare_html(result: CompareResult) -> str:
    summary = result.summary
    sections = [
        _html_page_open(f"Compare Report: {result.base_run_id} -> {result.candidate_run_id}"),
        f"<h1>Compare Report: {escape(result.base_run_id)} -&gt; {escape(result.candidate_run_id)}</h1>",
        "<h2>Summary</h2>",
        _html_table(
            ["Metric", "Base", "Candidate", "Delta"],
            [
                ["Pass Rate", f"{summary.base_pass_rate:.2%}", f"{summary.candidate_pass_rate:.2%}", f"{summary.pass_rate_delta:+.2%}"],
                ["Passed", str(summary.base_passed_cases), str(summary.candidate_passed_cases), f"{summary.passed_delta:+d}"],
                ["Failed", str(summary.base_failed_cases), str(summary.candidate_failed_cases), f"{summary.failed_delta:+d}"],
                ["Errors", str(summary.base_error_cases), str(summary.candidate_error_cases), f"{summary.error_delta:+d}"],
                ["Avg Latency", f"{summary.base_avg_latency_ms:.2f} ms", f"{summary.candidate_avg_latency_ms:.2f} ms", f"{summary.avg_latency_delta_ms:+.2f} ms"],
                ["P95 Latency", f"{summary.base_p95_latency_ms:.2f} ms", f"{summary.candidate_p95_latency_ms:.2f} ms", f"{summary.p95_latency_delta_ms:+.2f} ms"],
            ],
        ),
    ]

    if result.tag_results:
        tag_rows = [
            [
                tag_result.tag,
                f"{tag_result.base_pass_rate:.2%}",
                f"{tag_result.candidate_pass_rate:.2%}",
                f"{tag_result.pass_rate_delta:+.2%}",
            ]
            for tag_result in sorted(result.tag_results.values(), key=lambda item: item.tag)
        ]
        sections.extend(
            [
                "<h2>Tag Changes</h2>",
                _html_table(["Tag", "Base", "Candidate", "Delta"], tag_rows),
            ]
        )

    sections.extend(
        [
            "<h2>Case Changes</h2>",
            _html_key_value_table(
                [
                    ("Newly Failed", _render_case_list(summary.newly_failed_case_ids)),
                    ("Fixed", _render_case_list(summary.fixed_case_ids)),
                    ("Newly Errored", _render_case_list(summary.newly_errored_case_ids)),
                    ("Base Only", _render_case_list(summary.base_only_case_ids)),
                    ("Candidate Only", _render_case_list(summary.candidate_only_case_ids)),
                ]
            ),
            _html_page_close(),
        ]
    )
    return "\n".join(sections)


def _render_case_list(case_ids: list[str]) -> str:
    return ", ".join(case_ids) if case_ids else "-"


def _html_page_open(title: str) -> str:
    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 32px; color: #1f2937; }",
            "    h1, h2 { color: #111827; }",
            "    table { border-collapse: collapse; width: 100%; margin: 16px 0 24px; }",
            "    th, td { border: 1px solid #d1d5db; padding: 8px 12px; text-align: left; vertical-align: top; }",
            "    th { background: #f3f4f6; }",
            "    code { background: #f3f4f6; padding: 1px 4px; border-radius: 4px; }",
            "  </style>",
            "</head>",
            "<body>",
        ]
    )


def _html_page_close() -> str:
    return "</body>\n</html>"


def _html_key_value_table(rows: list[tuple[str, str]]) -> str:
    body = "\n".join(
        f"  <tr><th>{escape(key)}</th><td>{escape(value)}</td></tr>"
        for key, value in rows
    )
    return "<table>\n" + body + "\n</table>"


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(item)}</th>" for item in headers)
    body = "\n".join(
        "  <tr>" + "".join(f"<td>{escape(item)}</td>" for item in row) + "</tr>"
        for row in rows
    )
    return f"<table>\n  <thead><tr>{head}</tr></thead>\n  <tbody>\n{body}\n  </tbody>\n</table>"
