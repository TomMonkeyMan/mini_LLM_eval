"""Tests for runtime logging."""

from __future__ import annotations

import json
import logging

from mini_llm_eval.core.logging import get_logger, setup_logging
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import CaseResult, CaseStatus, ProviderStatus


def test_setup_logging_emits_json_logs(capsys) -> None:
    setup_logging("INFO")
    logger = get_logger("mini_llm_eval.tests.logging")

    logger.info(
        "test log entry",
        extra={"event": "test_event", "run_id": "run-123"},
    )

    output = capsys.readouterr().err.strip()
    payload = json.loads(output)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "mini_llm_eval.tests.logging"
    assert payload["message"] == "test log entry"
    assert payload["event"] == "test_event"
    assert payload["run_id"] == "run-123"


def test_file_storage_logs_fallback_warning(tmp_path, caplog) -> None:
    blocking_path = tmp_path / "not-a-directory"
    blocking_path.write_text("occupied", encoding="utf-8")
    fallback_dir = tmp_path / "fallback"
    storage = FileStorage(output_dir=str(blocking_path), fallback_dir=str(fallback_dir))
    result = CaseResult(
        run_id="run-1",
        case_id="case-1",
        query="hello",
        expected="world",
        actual_output="world",
        case_status=CaseStatus.COMPLETED,
        eval_results={},
        latency_ms=1.0,
        provider_status=ProviderStatus.SUCCESS,
    )

    with caplog.at_level(logging.WARNING):
        storage.append_case_result("run-1", result)

    assert any(record.event == "artifact_fallback" for record in caplog.records)
