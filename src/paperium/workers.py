from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

WORKER_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "needs_context",
}


@dataclass
class WorkerSpec:
    worker_id: str
    backend: str
    role: str
    readable_paths: list[str]
    writable_paths: list[str]
    prompt: str
    timeout_seconds: int
    experiment_path: str | None = None
    canonical_result_path: str | None = None
    approved_expansions: list[str] = field(default_factory=list)


@dataclass
class WorkerResult:
    worker_id: str
    status: str
    stdout_path: str
    stderr_path: str
    output_path: str
    result_json_path: str
    canonical_result_path: str | None
    started_at: str | None
    ended_at: str | None
    failure_reason: str | None


def worker_id_for(role: str, repo_relative_path: str) -> str:
    role_slug = _slug(role.replace("_", "-"))
    path_slug = _slug(repo_relative_path)
    digest = hashlib.sha256(f"{role}\0{repo_relative_path}".encode("utf-8")).hexdigest()[:8]
    return f"{role_slug}-{path_slug}-{digest}"


def build_worker_record(spec: WorkerSpec) -> dict[str, object]:
    worker_dir = f".paperium/workers/{spec.worker_id}"
    return {
        "id": spec.worker_id,
        "backend": spec.backend,
        "role": spec.role,
        "experiment_path": spec.experiment_path,
        "status": "pending",
        "started_at": None,
        "ended_at": None,
        "stdout_path": f"{worker_dir}/stdout.txt",
        "stderr_path": f"{worker_dir}/stderr.txt",
        "output_path": f"{worker_dir}/output.md",
        "result_json_path": f"{worker_dir}/result.json",
        "canonical_result_path": spec.canonical_result_path,
        "readable_paths": list(spec.readable_paths),
        "writable_paths": list(spec.writable_paths),
        "approved_expansions": list(spec.approved_expansions),
        "failure_reason": None,
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "item"
