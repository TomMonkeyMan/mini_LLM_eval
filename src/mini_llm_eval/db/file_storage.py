"""Artifact file storage helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mini_llm_eval.core.types import CaseResultArtifact, RunMeta
from mini_llm_eval.core.logging import get_logger
from mini_llm_eval.models.schemas import CaseResult

logger = get_logger(__name__)


class FileStorage:
    """Write portable run artifacts to the local filesystem."""

    def __init__(self, output_dir: str = "./outputs", fallback_dir: str = "/tmp") -> None:
        self.output_dir = Path(output_dir)
        self.fallback_dir = Path(fallback_dir)

    def _run_dir(self, run_id: str) -> Path:
        return self.output_dir / run_id

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def append_case_result(self, run_id: str, result: CaseResult) -> str:
        """Append a case result to the run JSONL artifact."""

        payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        target_path = self._run_dir(run_id) / "case_results.jsonl"

        try:
            self._ensure_dir(target_path.parent)
            with target_path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
            return str(target_path)
        except OSError:
            fallback_path = self._fallback_path(run_id, "case_results", suffix=".jsonl")
            with fallback_path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
            logger.warning(
                "Primary artifact write failed; using fallback path",
                extra={
                    "event": "artifact_fallback",
                    "artifact_type": "case_results",
                    "run_id": run_id,
                    "fallback_path": str(fallback_path),
                },
            )
            return str(fallback_path)

    def save_meta(self, run_id: str, meta: RunMeta) -> str:
        """Write run metadata snapshot to meta.json."""

        target_path = self._run_dir(run_id) / "meta.json"
        payload = json.dumps(meta, ensure_ascii=False, indent=2)

        try:
            self._ensure_dir(target_path.parent)
            self._atomic_write(target_path, payload)
            return str(target_path)
        except OSError:
            fallback_path = self._fallback_path(run_id, "meta", suffix=".json")
            self._atomic_write(fallback_path, payload)
            logger.warning(
                "Primary artifact write failed; using fallback path",
                extra={
                    "event": "artifact_fallback",
                    "artifact_type": "meta",
                    "run_id": run_id,
                    "fallback_path": str(fallback_path),
                },
            )
            return str(fallback_path)

    def read_json_lines(self, path: str) -> list[CaseResultArtifact]:
        """Read a JSONL artifact back into memory."""

        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as handle:
            return [CaseResultArtifact(**json.loads(line)) for line in handle if line.strip()]

    def read_json(self, path: str) -> RunMeta:
        """Read a JSON artifact back into memory."""

        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as handle:
            return RunMeta(**json.load(handle))

    def _fallback_path(self, run_id: str, stem: str, suffix: str) -> Path:
        run_dir = self.fallback_dir / run_id
        self._ensure_dir(run_dir)
        fd, temp_path = tempfile.mkstemp(prefix=f"{stem}_", suffix=suffix, dir=run_dir)
        Path(temp_path).unlink(missing_ok=True)
        return Path(temp_path)

    def _atomic_write(self, path: Path, content: str) -> None:
        self._ensure_dir(path.parent)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
