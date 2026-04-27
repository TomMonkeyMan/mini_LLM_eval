"""CLI entrypoint."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mini_llm_eval.core.config import (
    Config,
    load_config,
    load_providers,
    reset_runtime_config,
    set_runtime_config,
)
from mini_llm_eval.core.exceptions import EvalRunnerException
from mini_llm_eval.core.exceptions import ReportError
from mini_llm_eval.core.logging import get_logger, setup_logging
from mini_llm_eval.core.types import CaseResultRecord, RunRecord
from mini_llm_eval.db.database import Database
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import CompareResult, RunConfig
from mini_llm_eval.services.comparator import Comparator
from mini_llm_eval.services.reporter import Reporter
from mini_llm_eval.services.run_service import RunService

app = typer.Typer(help="Mini LLM evaluation runner CLI")
console = Console()
logger = get_logger(__name__)


def _build_runtime(
    config_path: str | None,
    providers_path: str | None,
    db_path: str | None,
) -> tuple[Config, Database, RunService]:
    config = load_config(config_path)
    setup_logging(config.log_level)
    providers = load_providers(providers_path)
    set_runtime_config(config=config, providers=providers)

    resolved_db_path = db_path or str(Path(config.output_dir) / "eval.db")
    db = Database(resolved_db_path)
    storage = FileStorage(output_dir=config.output_dir)
    service = RunService(db=db, file_storage=storage, providers=providers, config=config)
    return config, db, service


async def _run_and_load_record(service: RunService, db: Database, run_config: RunConfig) -> RunRecord:
    await service.start_run(run_config)
    run_record = await db.get_run(run_config.run_id)
    if run_record is None:
        raise EvalRunnerException(f"Run completed but could not be loaded: {run_config.run_id}")
    return run_record


async def _resume_and_load_record(service: RunService, db: Database, run_id: str) -> RunRecord:
    resumed_run_id = await service.resume_run(run_id)
    run_record = await db.get_run(resumed_run_id)
    if run_record is None:
        raise EvalRunnerException(f"Run resumed but could not be loaded: {resumed_run_id}")
    return run_record


async def _load_status_record(db: Database, run_id: str) -> RunRecord:
    run_record = await db.get_run(run_id)
    if run_record is None:
        raise EvalRunnerException(f"Run not found: {run_id}")
    return run_record


async def _load_run_cases(db: Database, run_id: str) -> tuple[RunRecord, list[CaseResultRecord]]:
    run_record = await db.get_run(run_id)
    if run_record is None:
        raise EvalRunnerException(f"Run not found: {run_id}")
    return run_record, await db.get_case_results(run_id)


async def _load_recent_runs(db: Database, limit: int) -> list[RunRecord]:
    return await db.list_runs(limit=limit)


async def _cancel_and_load_record(service: RunService, db: Database, run_id: str) -> RunRecord:
    cancelled_run_id = await service.cancel_run(run_id)
    run_record = await db.get_run(cancelled_run_id)
    if run_record is None:
        raise EvalRunnerException(f"Run cancelled but could not be loaded: {cancelled_run_id}")
    return run_record


def _build_storage(config_path: str | None) -> tuple[Config, FileStorage]:
    config = load_config(config_path)
    setup_logging(config.log_level)
    return config, FileStorage(output_dir=config.output_dir)


def _resolve_compare_input(value: str, output_dir: str) -> tuple[str, str]:
    input_path = Path(value).expanduser()
    if "/" in value or value.startswith(".") or value.startswith("~"):
        return str(input_path), str(input_path)
    return value, str(Path(output_dir) / value)


def _write_report_output(report: str, output_path: str | None) -> None:
    if output_path is None:
        typer.echo(report)
        return
    target = Path(output_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Failed to write report output {target}: {exc}") from exc


def _print_run_summary(run_record: RunRecord) -> None:
    summary = json.loads(run_record["summary_json"]) if run_record.get("summary_json") else None

    table = Table(title=f"Run {run_record['run_id']}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Status", run_record["status"])
    table.add_row("Dataset", run_record["dataset_path"])
    table.add_row("Provider", run_record["provider_name"])
    table.add_row("Created", str(run_record["created_at"]))
    table.add_row("Started", str(run_record["started_at"]))
    table.add_row("Finished", str(run_record["finished_at"]))
    if summary:
        table.add_row("Pass Rate", f"{summary['pass_rate']:.2%}")
        table.add_row("Passed", str(summary["passed_cases"]))
        table.add_row("Failed", str(summary["failed_cases"]))
        table.add_row("Errors", str(summary["error_cases"]))
        table.add_row("Avg Latency", f"{summary['avg_latency_ms']:.2f} ms")
        table.add_row("P95 Latency", f"{summary['p95_latency_ms']:.2f} ms")
    console.print(table)


def _print_run_list(run_records: list[RunRecord]) -> None:
    table = Table(title="Recent Runs")
    table.add_column("Run ID")
    table.add_column("Status")
    table.add_column("Provider")
    table.add_column("Created")
    table.add_column("Pass Rate")

    for run_record in run_records:
        summary = json.loads(run_record["summary_json"]) if run_record["summary_json"] else None
        pass_rate = f"{summary['pass_rate']:.2%}" if summary and "pass_rate" in summary else "-"
        table.add_row(
            run_record["run_id"],
            run_record["status"],
            run_record["provider_name"],
            str(run_record["created_at"]),
            pass_rate,
        )

    console.print(table)


def _case_failed(case_row: CaseResultRecord) -> bool:
    payload = json.loads(case_row["payload_json"])
    if case_row["status"] != "completed":
        return True
    eval_results = payload.get("eval_results", {})
    if not eval_results:
        return False
    return any((not item.get("passed", False)) or item.get("error") for item in eval_results.values())


def _print_case_results(case_rows: list[CaseResultRecord], failed_only: bool = False) -> None:
    selected_rows = [row for row in case_rows if _case_failed(row)] if failed_only else case_rows
    table = Table(title="Case Results")
    table.add_column("Case ID")
    table.add_column("Status")
    table.add_column("Latency")
    table.add_column("Error")
    table.add_column("Evaluators")

    for row in selected_rows:
        payload = json.loads(row["payload_json"])
        eval_results = payload.get("eval_results", {})
        failed_evaluators = [
            name
            for name, item in eval_results.items()
            if (not item.get("passed", False)) or item.get("error")
        ]
        table.add_row(
            row["case_id"],
            row["status"],
            f"{row['latency_ms']:.2f} ms",
            row["error"] or "-",
            ", ".join(failed_evaluators) if failed_evaluators else "-",
        )

    console.print(table)


def _print_compare_result(result: CompareResult) -> None:
    summary_table = Table(title=f"Compare {result.base_run_id} -> {result.candidate_run_id}")
    summary_table.add_column("Metric")
    summary_table.add_column("Base")
    summary_table.add_column("Candidate")
    summary_table.add_column("Delta")
    summary_table.add_row("Pass Rate", f"{result.summary.base_pass_rate:.2%}", f"{result.summary.candidate_pass_rate:.2%}", f"{result.summary.pass_rate_delta:+.2%}")
    summary_table.add_row("Passed", str(result.summary.base_passed_cases), str(result.summary.candidate_passed_cases), f"{result.summary.passed_delta:+d}")
    summary_table.add_row("Failed", str(result.summary.base_failed_cases), str(result.summary.candidate_failed_cases), f"{result.summary.failed_delta:+d}")
    summary_table.add_row("Errors", str(result.summary.base_error_cases), str(result.summary.candidate_error_cases), f"{result.summary.error_delta:+d}")
    summary_table.add_row("Avg Latency", f"{result.summary.base_avg_latency_ms:.2f} ms", f"{result.summary.candidate_avg_latency_ms:.2f} ms", f"{result.summary.avg_latency_delta_ms:+.2f} ms")
    summary_table.add_row("P95 Latency", f"{result.summary.base_p95_latency_ms:.2f} ms", f"{result.summary.candidate_p95_latency_ms:.2f} ms", f"{result.summary.p95_latency_delta_ms:+.2f} ms")
    console.print(summary_table)

    if result.tag_results:
        tag_table = Table(title="Tag Changes")
        tag_table.add_column("Tag")
        tag_table.add_column("Base")
        tag_table.add_column("Candidate")
        tag_table.add_column("Delta")
        for tag_result in result.tag_results.values():
            tag_table.add_row(
                tag_result.tag,
                f"{tag_result.base_pass_rate:.2%}",
                f"{tag_result.candidate_pass_rate:.2%}",
                f"{tag_result.pass_rate_delta:+.2%}",
            )
        console.print(tag_table)

    case_table = Table(title="Case Changes")
    case_table.add_column("Category")
    case_table.add_column("Case IDs")
    case_table.add_row("Newly Failed", ", ".join(result.summary.newly_failed_case_ids) or "-")
    case_table.add_row("Fixed", ", ".join(result.summary.fixed_case_ids) or "-")
    case_table.add_row("Newly Errored", ", ".join(result.summary.newly_errored_case_ids) or "-")
    case_table.add_row("Base Only", ", ".join(result.summary.base_only_case_ids) or "-")
    case_table.add_row("Candidate Only", ", ".join(result.summary.candidate_only_case_ids) or "-")
    console.print(case_table)


@app.command()
def run(
    dataset: str = typer.Option(..., help="Dataset path"),
    provider: str = typer.Option(..., help="Provider name"),
    concurrency: int | None = typer.Option(None, help="Override concurrency"),
    timeout: int | None = typer.Option(None, help="Override timeout in milliseconds"),
    run_id: str | None = typer.Option(None, help="Optional run id"),
    config: str | None = typer.Option(None, help="Path to config.yaml"),
    providers: str | None = typer.Option(None, help="Path to providers.yaml"),
    db_path: str | None = typer.Option(None, help="Path to SQLite database"),
) -> None:
    """Create and execute a run."""

    try:
        cfg, db, service = _build_runtime(config, providers, db_path)
        resolved_run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        logger.info(
            "CLI run command started",
            extra={
                "event": "cli_run_started",
                "run_id": resolved_run_id,
                "dataset_path": dataset,
                "provider_name": provider,
            },
        )
        run_config = RunConfig(
            run_id=resolved_run_id,
            dataset_path=dataset,
            provider_name=provider,
            concurrency=concurrency or cfg.concurrency,
            timeout_ms=timeout or cfg.timeout_ms,
            max_retries=cfg.max_retries,
        )
        run_record = asyncio.run(_run_and_load_record(service, db, run_config))
        logger.info(
            "CLI run command completed",
            extra={
                "event": "cli_run_completed",
                "run_id": resolved_run_id,
                "status": run_record["status"],
            },
        )
        _print_run_summary(run_record)
    except EvalRunnerException as exc:
        logger.exception(
            "CLI run command failed",
            extra={"event": "cli_run_failed", "run_id": run_id, "provider_name": provider},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    finally:
        reset_runtime_config()


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Run id to resume"),
    config: str | None = typer.Option(None, help="Path to config.yaml"),
    providers: str | None = typer.Option(None, help="Path to providers.yaml"),
    db_path: str | None = typer.Option(None, help="Path to SQLite database"),
) -> None:
    """Resume a previously started run."""

    try:
        _, db, service = _build_runtime(config, providers, db_path)
        logger.info(
            "CLI resume command started",
            extra={"event": "cli_resume_started", "run_id": run_id},
        )
        run_record = asyncio.run(_resume_and_load_record(service, db, run_id))
        logger.info(
            "CLI resume command completed",
            extra={"event": "cli_resume_completed", "run_id": run_id, "status": run_record["status"]},
        )
        _print_run_summary(run_record)
    except EvalRunnerException as exc:
        logger.exception(
            "CLI resume command failed",
            extra={"event": "cli_resume_failed", "run_id": run_id},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    finally:
        reset_runtime_config()


@app.command()
def status(
    run_id: str = typer.Argument(..., help="Run id to inspect"),
    config: str | None = typer.Option(None, help="Path to config.yaml"),
    db_path: str | None = typer.Option(None, help="Path to SQLite database"),
) -> None:
    """Show run status and summary if available."""

    try:
        cfg = load_config(config)
        setup_logging(cfg.log_level)
        resolved_db_path = db_path or str(Path(cfg.output_dir) / "eval.db")
        db = Database(resolved_db_path)
        logger.info(
            "CLI status command started",
            extra={"event": "cli_status_started", "run_id": run_id},
        )
        run_record = asyncio.run(_load_status_record(db, run_id))
        logger.info(
            "CLI status command completed",
            extra={"event": "cli_status_completed", "run_id": run_id, "status": run_record["status"]},
        )
        _print_run_summary(run_record)
    except EvalRunnerException as exc:
        logger.exception(
            "CLI status command failed",
            extra={"event": "cli_status_failed", "run_id": run_id},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command()
def list(
    limit: int = typer.Option(10, min=1, help="Maximum number of runs to show"),
    config: str | None = typer.Option(None, help="Path to config.yaml"),
    db_path: str | None = typer.Option(None, help="Path to SQLite database"),
) -> None:
    """List recent runs."""

    try:
        cfg = load_config(config)
        setup_logging(cfg.log_level)
        resolved_db_path = db_path or str(Path(cfg.output_dir) / "eval.db")
        db = Database(resolved_db_path)
        logger.info(
            "CLI list command started",
            extra={"event": "cli_list_started", "limit": limit},
        )
        run_records = asyncio.run(_load_recent_runs(db, limit))
        logger.info(
            "CLI list command completed",
            extra={"event": "cli_list_completed", "limit": limit, "run_count": len(run_records)},
        )
        _print_run_list(run_records)
    except EvalRunnerException as exc:
        logger.exception(
            "CLI list command failed",
            extra={"event": "cli_list_failed", "limit": limit},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command()
def show(
    run_id: str = typer.Argument(..., help="Run id to inspect in detail"),
    cases: bool = typer.Option(False, "--cases", help="Show case-level results"),
    failed_only: bool = typer.Option(False, help="Show only failed/error cases"),
    config: str | None = typer.Option(None, help="Path to config.yaml"),
    db_path: str | None = typer.Option(None, help="Path to SQLite database"),
) -> None:
    """Show a run summary and optional case results."""

    try:
        cfg = load_config(config)
        setup_logging(cfg.log_level)
        resolved_db_path = db_path or str(Path(cfg.output_dir) / "eval.db")
        db = Database(resolved_db_path)
        logger.info(
            "CLI show command started",
            extra={"event": "cli_show_started", "run_id": run_id, "cases": cases, "failed_only": failed_only},
        )
        run_record, case_rows = asyncio.run(_load_run_cases(db, run_id))
        logger.info(
            "CLI show command completed",
            extra={
                "event": "cli_show_completed",
                "run_id": run_id,
                "status": run_record["status"],
                "case_count": len(case_rows),
            },
        )
        _print_run_summary(run_record)
        if cases or failed_only:
            _print_case_results(case_rows, failed_only=failed_only)
    except EvalRunnerException as exc:
        logger.exception(
            "CLI show command failed",
            extra={"event": "cli_show_failed", "run_id": run_id},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command()
def cancel(
    run_id: str = typer.Argument(..., help="Run id to cancel"),
    config: str | None = typer.Option(None, help="Path to config.yaml"),
    providers: str | None = typer.Option(None, help="Path to providers.yaml"),
    db_path: str | None = typer.Option(None, help="Path to SQLite database"),
) -> None:
    """Cancel a pending run."""

    try:
        _, db, service = _build_runtime(config, providers, db_path)
        logger.info(
            "CLI cancel command started",
            extra={"event": "cli_cancel_started", "run_id": run_id},
        )
        run_record = asyncio.run(_cancel_and_load_record(service, db, run_id))
        logger.info(
            "CLI cancel command completed",
            extra={"event": "cli_cancel_completed", "run_id": run_id, "status": run_record["status"]},
        )
        _print_run_summary(run_record)
    except EvalRunnerException as exc:
        logger.exception(
            "CLI cancel command failed",
            extra={"event": "cli_cancel_failed", "run_id": run_id},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    finally:
        reset_runtime_config()


@app.command()
def compare(
    base: str = typer.Argument(..., help="Base run id or run artifact directory"),
    candidate: str = typer.Argument(..., help="Candidate run id or run artifact directory"),
    output_dir: str = typer.Option("./outputs", help="Directory containing run artifact folders"),
) -> None:
    """Compare two runs from exported artifacts."""

    try:
        setup_logging("INFO")
        storage = FileStorage(output_dir=output_dir)
        base_label, base_path = _resolve_compare_input(base, output_dir)
        candidate_label, candidate_path = _resolve_compare_input(candidate, output_dir)
        logger.info(
            "CLI compare command started",
            extra={
                "event": "cli_compare_started",
                "base_input": base,
                "candidate_input": candidate,
                "base_path": base_path,
                "candidate_path": candidate_path,
            },
        )
        comparator = Comparator(storage)
        result = comparator.compare_run_dirs(base_path, candidate_path)
        logger.info(
            "CLI compare command completed",
            extra={
                "event": "cli_compare_completed",
                "base_run_id": base_label,
                "candidate_run_id": candidate_label,
            },
        )
        _print_compare_result(result)
    except EvalRunnerException as exc:
        logger.exception(
            "CLI compare command failed",
            extra={
                "event": "cli_compare_failed",
                "base_input": base,
                "candidate_input": candidate,
            },
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command("report-run")
def report_run(
    target: str = typer.Argument(..., help="Run id or run artifact directory"),
    output_dir: str = typer.Option("./outputs", help="Directory containing run artifact folders"),
    format: str = typer.Option("markdown", help="Report format: markdown or html"),
    output: str | None = typer.Option(None, help="Write report to a file instead of stdout"),
) -> None:
    """Render a single-run report from artifacts."""

    try:
        setup_logging("INFO")
        storage = FileStorage(output_dir=output_dir)
        reporter = Reporter(storage)
        target_label, target_path = _resolve_compare_input(target, output_dir)
        logger.info(
            "CLI report-run command started",
            extra={"event": "cli_report_run_started", "target": target, "target_path": target_path, "format": format},
        )
        meta, case_results = reporter.load_run_artifacts(target_path)
        report = reporter.render_run_report(meta, case_results, format=format)
        _write_report_output(report, output)
        logger.info(
            "CLI report-run command completed",
            extra={"event": "cli_report_run_completed", "run_id": target_label, "format": format, "output": output},
        )
    except EvalRunnerException as exc:
        logger.exception(
            "CLI report-run command failed",
            extra={"event": "cli_report_run_failed", "target": target, "format": format},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command("report-compare")
def report_compare(
    base: str = typer.Argument(..., help="Base run id or run artifact directory"),
    candidate: str = typer.Argument(..., help="Candidate run id or run artifact directory"),
    output_dir: str = typer.Option("./outputs", help="Directory containing run artifact folders"),
    format: str = typer.Option("markdown", help="Report format: markdown or html"),
    output: str | None = typer.Option(None, help="Write report to a file instead of stdout"),
) -> None:
    """Render a compare report from artifacts."""

    try:
        setup_logging("INFO")
        storage = FileStorage(output_dir=output_dir)
        base_label, base_path = _resolve_compare_input(base, output_dir)
        candidate_label, candidate_path = _resolve_compare_input(candidate, output_dir)
        logger.info(
            "CLI report-compare command started",
            extra={
                "event": "cli_report_compare_started",
                "base_input": base,
                "candidate_input": candidate,
                "base_path": base_path,
                "candidate_path": candidate_path,
                "format": format,
            },
        )
        comparator = Comparator(storage)
        reporter = Reporter(storage)
        result = comparator.compare_run_dirs(base_path, candidate_path)
        report = reporter.render_compare_report(result, format=format)
        _write_report_output(report, output)
        logger.info(
            "CLI report-compare command completed",
            extra={
                "event": "cli_report_compare_completed",
                "base_run_id": base_label,
                "candidate_run_id": candidate_label,
                "format": format,
                "output": output,
            },
        )
    except EvalRunnerException as exc:
        logger.exception(
            "CLI report-compare command failed",
            extra={"event": "cli_report_compare_failed", "base_input": base, "candidate_input": candidate, "format": format},
        )
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


def main() -> None:
    """Console script entrypoint."""

    app()
