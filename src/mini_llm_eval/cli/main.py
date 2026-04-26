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
    load_config,
    load_providers,
    reset_runtime_config,
    set_runtime_config,
)
from mini_llm_eval.core.exceptions import EvalRunnerException
from mini_llm_eval.db.database import Database
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import RunConfig
from mini_llm_eval.services.run_service import RunService

app = typer.Typer(help="Mini LLM evaluation runner CLI")
console = Console()


def _build_runtime(
    config_path: str | None,
    providers_path: str | None,
    db_path: str | None,
):
    config = load_config(config_path)
    providers = load_providers(providers_path)
    set_runtime_config(config=config, providers=providers)

    resolved_db_path = db_path or str(Path(config.output_dir) / "eval.db")
    db = Database(resolved_db_path)
    storage = FileStorage(output_dir=config.output_dir)
    service = RunService(db=db, file_storage=storage, providers=providers, config=config)
    return config, db, service


def _print_run_summary(run_record: dict) -> None:
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
        run_config = RunConfig(
            run_id=resolved_run_id,
            dataset_path=dataset,
            provider_name=provider,
            concurrency=concurrency or cfg.concurrency,
            timeout_ms=timeout or cfg.timeout_ms,
            max_retries=cfg.max_retries,
        )
        asyncio.run(service.start_run(run_config))
        run_record = asyncio.run(db.get_run(resolved_run_id))
        if run_record is None:
            raise EvalRunnerException(f"Run completed but could not be loaded: {resolved_run_id}")
        _print_run_summary(run_record)
    except EvalRunnerException as exc:
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
        resumed_run_id = asyncio.run(service.resume_run(run_id))
        run_record = asyncio.run(db.get_run(resumed_run_id))
        if run_record is None:
            raise EvalRunnerException(f"Run resumed but could not be loaded: {resumed_run_id}")
        _print_run_summary(run_record)
    except EvalRunnerException as exc:
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
        resolved_db_path = db_path or str(Path(cfg.output_dir) / "eval.db")
        db = Database(resolved_db_path)
        run_record = asyncio.run(db.get_run(run_id))
        if run_record is None:
            raise EvalRunnerException(f"Run not found: {run_id}")
        _print_run_summary(run_record)
    except EvalRunnerException as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


def main() -> None:
    """Console script entrypoint."""

    app()
