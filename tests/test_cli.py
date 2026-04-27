"""Tests for the CLI surface."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from mini_llm_eval.cli.main import app
from mini_llm_eval.db.database import Database
from mini_llm_eval.models.schemas import RunConfig, RunStatus

runner = CliRunner()


def _write_basic_config(tmp_path) -> tuple:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "timeout_ms: 5000",
                "max_retries: 3",
                "concurrency: 2",
                f'output_dir: "{tmp_path / "outputs"}"',
                'evaluators_package: "mini_llm_eval.evaluators"',
                "defaults:",
                "  evaluators:",
                "    - contains",
            ]
        ),
        encoding="utf-8",
    )
    mapping_path = tmp_path / "mock_mapping.json"
    mapping_path.write_text(json.dumps({"Question A": "expected-a"}), encoding="utf-8")
    providers_path = tmp_path / "providers.yaml"
    providers_path.write_text(
        "\n".join(
            [
                "mock-default:",
                "  type: mock",
                f'  mapping_file: "{mapping_path}"',
            ]
        ),
        encoding="utf-8",
    )
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "case-a",
                "query": "Question A",
                "expected_answer": "expected-a",
                "eval_type": "contains",
                "tags": ["knowledge"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "cli.db"
    return config_path, providers_path, dataset_path, db_path


def test_cli_run_and_status_commands(tmp_path) -> None:
    config_path, providers_path, dataset_path, db_path = _write_basic_config(tmp_path)

    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            str(dataset_path),
            "--provider",
            "mock-default",
            "--run-id",
            "run-cli",
            "--config",
            str(config_path),
            "--providers",
            str(providers_path),
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "run-cli" in result.stdout
    assert "succeeded" in result.stdout

    status_result = runner.invoke(
        app,
        [
            "status",
            "run-cli",
            "--config",
            str(config_path),
            "--db-path",
            str(db_path),
        ],
    )
    assert status_result.exit_code == 0, status_result.stdout
    assert "Pass Rate" in status_result.stdout


def test_cli_resume_command_returns_existing_succeeded_run(tmp_path) -> None:
    config_path, providers_path, dataset_path, db_path = _write_basic_config(tmp_path)

    run_result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            str(dataset_path),
            "--provider",
            "mock-default",
            "--run-id",
            "run-cli",
            "--config",
            str(config_path),
            "--providers",
            str(providers_path),
            "--db-path",
            str(db_path),
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout

    resume_result = runner.invoke(
        app,
        [
            "resume",
            "run-cli",
            "--config",
            str(config_path),
            "--providers",
            str(providers_path),
            "--db-path",
            str(db_path),
        ],
    )
    assert resume_result.exit_code == 0, resume_result.stdout
    assert "run-cli" in resume_result.stdout


def test_cli_list_command_shows_recent_runs(tmp_path) -> None:
    config_path, providers_path, dataset_path, db_path = _write_basic_config(tmp_path)

    for run_id in ("run-a", "run-b"):
        run_result = runner.invoke(
            app,
            [
                "run",
                "--dataset",
                str(dataset_path),
                "--provider",
                "mock-default",
                "--run-id",
                run_id,
                "--config",
                str(config_path),
                "--providers",
                str(providers_path),
                "--db-path",
                str(db_path),
            ],
        )
        assert run_result.exit_code == 0, run_result.stdout

    list_result = runner.invoke(
        app,
        [
            "list",
            "--limit",
            "5",
            "--config",
            str(config_path),
            "--db-path",
            str(db_path),
        ],
    )

    assert list_result.exit_code == 0, list_result.stdout
    assert "Recent Runs" in list_result.stdout
    assert "run-a" in list_result.stdout
    assert "run-b" in list_result.stdout


def test_cli_show_command_can_filter_failed_cases(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "timeout_ms: 5000",
                "max_retries: 3",
                "concurrency: 2",
                f'output_dir: "{tmp_path / "outputs"}"',
                'evaluators_package: "mini_llm_eval.evaluators"',
            ]
        ),
        encoding="utf-8",
    )
    mapping_path = tmp_path / "mock_mapping.json"
    mapping_path.write_text(json.dumps({"Question A": "wrong-answer"}), encoding="utf-8")
    providers_path = tmp_path / "providers.yaml"
    providers_path.write_text(
        "\n".join(
            [
                "mock-default:",
                "  type: mock",
                f'  mapping_file: "{mapping_path}"',
            ]
        ),
        encoding="utf-8",
    )
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "case-a",
                "query": "Question A",
                "expected_answer": "expected-a",
                "eval_type": "contains",
                "tags": ["knowledge"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "cli.db"

    run_result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            str(dataset_path),
            "--provider",
            "mock-default",
            "--run-id",
            "run-failed-case",
            "--config",
            str(config_path),
            "--providers",
            str(providers_path),
            "--db-path",
            str(db_path),
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout

    show_result = runner.invoke(
        app,
        [
            "show",
            "run-failed-case",
            "--cases",
            "--failed-only",
            "--config",
            str(config_path),
            "--db-path",
            str(db_path),
        ],
    )

    assert show_result.exit_code == 0, show_result.stdout
    assert "Case Results" in show_result.stdout
    assert "case-a" in show_result.stdout


def test_cli_cancel_command_cancels_pending_run(tmp_path) -> None:
    config_path, providers_path, _, db_path = _write_basic_config(tmp_path)
    db = Database(str(db_path))

    import asyncio

    async def prepare_pending_run() -> None:
        await db.init()
        await db.create_run(
            RunConfig(
                run_id="run-pending",
                dataset_path="data/eval_cases.jsonl",
                provider_name="mock-default",
            )
        )

    asyncio.run(prepare_pending_run())

    cancel_result = runner.invoke(
        app,
        [
            "cancel",
            "run-pending",
            "--config",
            str(config_path),
            "--providers",
            str(providers_path),
            "--db-path",
            str(db_path),
        ],
    )

    assert cancel_result.exit_code == 0, cancel_result.stdout
    assert "cancelled" in cancel_result.stdout


def test_cli_cancel_command_rejects_running_run(tmp_path) -> None:
    config_path, providers_path, _, db_path = _write_basic_config(tmp_path)
    db = Database(str(db_path))

    import asyncio

    async def prepare_running_run() -> None:
        await db.init()
        await db.create_run(
            RunConfig(
                run_id="run-running",
                dataset_path="data/eval_cases.jsonl",
                provider_name="mock-default",
            )
        )
        await db.update_run_status("run-running", RunStatus.RUNNING.value, event="run_started")

    asyncio.run(prepare_running_run())

    cancel_result = runner.invoke(
        app,
        [
            "cancel",
            "run-running",
            "--config",
            str(config_path),
            "--providers",
            str(providers_path),
            "--db-path",
            str(db_path),
        ],
    )

    assert cancel_result.exit_code == 1, cancel_result.stdout
    assert "active cancellation is not supported" in cancel_result.stdout
