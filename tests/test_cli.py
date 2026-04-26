"""Tests for the CLI surface."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from mini_llm_eval.cli.main import app

runner = CliRunner()


def test_cli_run_and_status_commands(tmp_path) -> None:
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
    mapping_path.write_text(
        json.dumps({"Question A": "expected-a"}),
        encoding="utf-8",
    )
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
