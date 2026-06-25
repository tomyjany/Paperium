from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import ValidationError

from paperctl._support.blockers import derive_publication_blockers
from paperctl._support.hashing import canonical_json_hash, sha256_bytes, sha256_file
from paperctl._support.jsonio import dump_json_bytes, write_json_atomic
from paperctl._support.paths import is_repo_relative_posix, resolve_repo_relative_path
from paperctl._support.schema import validate_artifact
from paperctl.discovery import _build_manifest
from paperctl.inventory import InventoryError, _manifest_path, load_manifest
from paperctl.normalize import NormalizeError, _build_packet, _expected_inventory, _load_fresh_inventory
from paperctl.rendering import _build_render_state, _render_state_path, render_draft_bytes


AUDIT_SCHEMA_VERSION = 1
AUDIT_STAGE_VERSION = 1


class AuditError(ValueError):
    pass


@dataclass(frozen=True)
class AuditResult:
    report_path: str
    stage: str
    deterministic_status: str
    publication_status: str
    publishable: bool
    issue_count: int
    blocker_count: int
    issue_codes: list[str]
    blocker_codes: list[str]


def audit(repo: Path, config: dict[str, Any], stage: str | None = None) -> AuditResult:
    repo = repo.resolve()
    requested_stage = stage or config["audit"]["default_stage"]
    if requested_stage not in {"deterministic", "publication"}:
        raise AuditError(f"invalid audit stage: {requested_stage}")

    report_output = _resolve_audit_report_output(repo, config)
    manifest_for_output_protection = _load_manifest_for_output_protection(repo, config)
    if manifest_for_output_protection is not None:
        _reject_manifest_artifact_collisions(
            repo,
            config,
            manifest_for_output_protection,
            report_output,
        )
    context = _AuditContext(repo=repo, config=config)
    context.run()
    report = context.report(requested_stage)
    _write_report(config, report, report_output)
    return AuditResult(
        report_path=config["paper"]["audit_report"],
        stage=requested_stage,
        deterministic_status=report["deterministic_health"]["status"],
        publication_status=report["publication_gate"]["status"],
        publishable=report["publishable"],
        issue_count=len(report["deterministic_health"]["issues"]),
        blocker_count=len(report["publication_gate"]["blockers"]),
        issue_codes=[issue["code"] for issue in report["deterministic_health"]["issues"]],
        blocker_codes=[blocker["code"] for blocker in report["publication_gate"]["blockers"]],
    )


@dataclass
class _AuditContext:
    repo: Path
    config: dict[str, Any]

    def __post_init__(self) -> None:
        self.issues: list[dict[str, Any]] = []
        self.blockers: list[dict[str, Any]] = []
        self.manifest: dict[str, Any] | None = None
        self.evidence_packets: list[dict[str, Any]] = []
        self.inventory_hashes: list[str] = []
        self.evidence_hashes: list[str] = []
        self.stale_manifest_inputs: dict[str, dict[str, str]] = {}
        self.stale_source_inputs: dict[str, dict[str, str]] = {}
        self.render_state_hash: str | None = None
        self.draft_hash: str | None = None

    def run(self) -> None:
        if not self._questions_root_exists():
            return
        self.manifest = self._load_manifest()
        if self.manifest is None:
            return
        self._load_experiment_artifacts()
        if not self._has_complete_evidence():
            return
        self.blockers = _with_blocker_messages(
            derive_publication_blockers(self.manifest, self.evidence_packets)
        )
        self._validate_render_outputs()

    def report(self, stage: str) -> dict[str, Any]:
        deterministic_status = "failed" if self.issues else "passed"
        publication_status = "blocked" if self.blockers else "passed"
        publishable = deterministic_status == "passed" and publication_status == "passed"
        fingerprint = self._fingerprint(
            stage=stage,
            deterministic_status=deterministic_status,
            publication_status=publication_status,
        )
        report = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "artifact_type": "paper_audit",
            "stage": stage,
            "deterministic_health": {
                "status": deterministic_status,
                "issues": self.issues,
            },
            "publication_gate": {
                "status": publication_status,
                "blockers": self.blockers,
            },
            "publishable": publishable,
            "fingerprint": fingerprint,
        }
        try:
            validate_artifact("paper-audit.schema.json", report)
        except ValidationError as exc:
            raise AuditError(f"invalid generated audit report: {exc.message}") from exc
        return report

    def _questions_root_exists(self) -> bool:
        root = self.config["questions"]["root"]
        path = resolve_repo_relative_path(self.repo, root)
        if not path.exists():
            self._issue(
                "missing_questions_root",
                f"Configured questions root is missing: {root}",
                path=root,
            )
            return False
        if not path.is_dir():
            self._issue(
                "invalid_questions_root",
                f"Configured questions root is not a directory: {root}",
                path=root,
            )
            return False
        return True

    def _load_manifest(self) -> dict[str, Any] | None:
        manifest_path = _manifest_path(self.config)
        try:
            return load_manifest(self.repo, self.config)
        except InventoryError as exc:
            code = _manifest_issue_code(str(exc))
            self._issue(code, str(exc), path=manifest_path)
            if code == "stale_discovery_manifest":
                self._record_stale_manifest_input(manifest_path)
            return None

    def _load_experiment_artifacts(self) -> None:
        assert self.manifest is not None
        manifest_path = _manifest_path(self.config)
        for entry in self.manifest["experiments"]:
            inventory = self._load_inventory(entry, manifest_path)
            packet = self._load_evidence(entry, inventory, manifest_path)
            if packet is not None:
                self.evidence_packets.append(packet)

    def _load_inventory(
        self,
        entry: dict[str, Any],
        manifest_path: str,
    ) -> dict[str, Any] | None:
        inventory_path = entry["inventory_path"]
        try:
            inventory = _load_fresh_inventory(self.repo, self.config, entry, manifest_path)
        except NormalizeError as exc:
            code = _inventory_issue_code(str(exc))
            self._issue(
                code,
                str(exc),
                path=inventory_path,
                entry=entry,
            )
            if code == "stale_inventory":
                self._record_stale_source_input(entry, manifest_path)
            return None
        self.inventory_hashes.append(sha256_file(self.repo / inventory_path))
        return inventory

    def _load_evidence(
        self,
        entry: dict[str, Any],
        inventory: dict[str, Any] | None,
        manifest_path: str,
    ) -> dict[str, Any] | None:
        evidence_path = entry["evidence_path"]
        absolute_path = self.repo / evidence_path
        try:
            with absolute_path.open(encoding="utf-8") as handle:
                packet = json.load(handle)
        except FileNotFoundError:
            self._issue(
                "missing_evidence",
                f"missing evidence packet: {evidence_path}; run paperctl normalize first",
                path=evidence_path,
                entry=entry,
            )
            return None
        except json.JSONDecodeError as exc:
            self._issue(
                "invalid_evidence",
                f"could not parse evidence packet: {evidence_path}: {exc}",
                path=evidence_path,
                entry=entry,
            )
            return None
        except OSError as exc:
            self._issue(
                "invalid_evidence",
                f"could not read evidence packet: {evidence_path}: {exc}",
                path=evidence_path,
                entry=entry,
            )
            return None

        try:
            validate_artifact("evidence-packet.schema.json", packet)
        except ValidationError as exc:
            self._issue(
                "invalid_evidence",
                f"invalid evidence packet: {evidence_path}: {exc.message}",
                path=evidence_path,
                entry=entry,
            )
            return None
        if packet["experiment_path"] != entry["experiment_path"]:
            self._issue(
                "evidence_experiment_mismatch",
                f"evidence packet does not match manifest entry: {evidence_path}",
                path=evidence_path,
                entry=entry,
            )
            return None
        if inventory is None:
            return None
        try:
            expected = _build_packet(self.repo, self.config, entry, inventory, manifest_path)
        except NormalizeError as exc:
            self._issue(
                "stale_evidence",
                f"could not verify evidence packet: {evidence_path}: {exc}",
                path=evidence_path,
                entry=entry,
            )
            self._record_stale_source_input(entry, manifest_path)
            return None
        if dump_json_bytes(packet) != dump_json_bytes(expected):
            self._issue(
                "stale_evidence",
                f"stale evidence packet: {evidence_path}; run paperctl normalize --force first",
                path=evidence_path,
                entry=entry,
            )
            self._record_stale_source_input(entry, manifest_path)
            return None
        self.evidence_hashes.append(sha256_file(absolute_path))
        return packet

    def _has_complete_evidence(self) -> bool:
        assert self.manifest is not None
        return len(self.evidence_packets) == len(self.manifest["experiments"])

    def _validate_render_outputs(self) -> None:
        assert self.manifest is not None
        render_state_path = _render_state_path(self.config)
        draft_path = self.config["paper"]["draft_output"]
        render_state = self._load_render_state(render_state_path)
        draft_bytes = self._load_draft(draft_path)
        if render_state is None or draft_bytes is None:
            return

        expected_draft = render_draft_bytes(self.manifest, self.evidence_packets, self.blockers)
        expected_render_state = _build_render_state(
            self.repo,
            self.config,
            self.manifest,
            self.evidence_packets,
            expected_draft,
        )
        if dump_json_bytes(render_state) != dump_json_bytes(expected_render_state):
            self._issue(
                "stale_render_state",
                f"stale render state: {render_state_path}; run paperctl render --force first",
                path=render_state_path,
            )

        draft_hash = sha256_bytes(draft_bytes)
        if draft_hash != render_state["fingerprint"]["draft_sha256"]:
            self._issue(
                "draft_hash_mismatch",
                f"draft hash does not match render state: {draft_path}",
                path=draft_path,
            )
        if draft_bytes != expected_draft:
            self._issue(
                "draft_content_mismatch",
                f"draft content is not deterministic for current inputs: {draft_path}",
                path=draft_path,
            )

    def _load_render_state(self, render_state_path: str) -> dict[str, Any] | None:
        absolute_path = self.repo / render_state_path
        try:
            with absolute_path.open(encoding="utf-8") as handle:
                render_state = json.load(handle)
        except FileNotFoundError:
            self._issue(
                "missing_render_state",
                f"missing render state: {render_state_path}; run paperctl render first",
                path=render_state_path,
            )
            return None
        except json.JSONDecodeError as exc:
            self._issue(
                "invalid_render_state",
                f"could not parse render state: {render_state_path}: {exc}",
                path=render_state_path,
            )
            return None
        except OSError as exc:
            self._issue(
                "invalid_render_state",
                f"could not read render state: {render_state_path}: {exc}",
                path=render_state_path,
            )
            return None
        try:
            validate_artifact("render-state.schema.json", render_state)
        except ValidationError as exc:
            self._issue(
                "invalid_render_state",
                f"invalid render state: {render_state_path}: {exc.message}",
                path=render_state_path,
            )
            return None
        self.render_state_hash = sha256_file(absolute_path)
        return render_state

    def _load_draft(self, draft_path: str) -> bytes | None:
        absolute_path = self.repo / draft_path
        try:
            draft_bytes = absolute_path.read_bytes()
        except FileNotFoundError:
            self._issue(
                "missing_draft",
                f"missing draft output: {draft_path}; run paperctl render first",
                path=draft_path,
            )
            return None
        except OSError as exc:
            self._issue(
                "invalid_draft",
                f"could not read draft output: {draft_path}: {exc}",
                path=draft_path,
            )
            return None
        self.draft_hash = sha256_bytes(draft_bytes)
        return draft_bytes

    def _fingerprint(
        self,
        *,
        stage: str,
        deterministic_status: str,
        publication_status: str,
    ) -> dict[str, Any]:
        manifest_path = _manifest_path(self.config)
        render_state_path = _render_state_path(self.config)
        draft_path = self.config["paper"]["draft_output"]
        fingerprint = {
            "stage": {"name": "audit", "version": AUDIT_STAGE_VERSION},
            "schema_version": AUDIT_SCHEMA_VERSION,
            "requested_stage": stage,
            "config_sha256": canonical_json_hash(_relevant_config(self.config)),
            "manifest_path": manifest_path,
            "manifest_sha256": _hash_if_file(self.repo / manifest_path),
            "inventory_sha256": self.inventory_hashes,
            "evidence_packet_sha256": self.evidence_hashes,
            "render_state_path": render_state_path,
            "render_state_sha256": self.render_state_hash
            or _hash_if_file(self.repo / render_state_path),
            "draft_path": draft_path,
            "draft_sha256": self.draft_hash or _hash_if_file(self.repo / draft_path),
            "issue_payload_sha256": canonical_json_hash(self.issues),
            "blocker_payload_sha256": canonical_json_hash(self.blockers),
            "failed_prerequisite_sha256": self._failed_prerequisite_hashes(),
            "stale_manifest_input_sha256": self._stale_manifest_input_hashes(),
            "stale_source_input_sha256": self._stale_source_input_hashes(),
            "input_counts": {
                "experiment_count": len(self.manifest["experiments"]) if self.manifest else 0,
                "inventory_count": len(self.inventory_hashes),
                "evidence_packet_count": len(self.evidence_hashes),
                "issue_count": len(self.issues),
                "blocker_count": len(self.blockers),
            },
            "deterministic_status": deterministic_status,
            "publication_status": publication_status,
        }
        fingerprint["fingerprint_sha256"] = canonical_json_hash(fingerprint)
        return fingerprint

    def _record_stale_manifest_input(self, manifest_path: str) -> None:
        questions_root = resolve_repo_relative_path(self.repo, self.config["questions"]["root"])
        expected = _build_manifest(self.repo, self.config, questions_root)
        expected_fingerprint = expected["fingerprint"]
        self.stale_manifest_inputs[manifest_path] = {
            "manifest_path": manifest_path,
            "expected_manifest_sha256": sha256_bytes(dump_json_bytes(expected)),
            "expected_config_sha256": expected_fingerprint["config_sha256"],
            "expected_directory_entries_sha256": expected_fingerprint[
                "directory_entries_sha256"
            ],
        }

    def _record_stale_source_input(self, entry: dict[str, Any], manifest_path: str) -> None:
        experiment_path = entry["experiment_path"]
        try:
            expected = _expected_inventory(self.repo, self.config, entry, manifest_path)
        except NormalizeError:
            return
        inventory_fingerprint = expected["fingerprint"]
        artifact_listing = inventory_fingerprint["extra_inputs"]["artifact_listing"]
        self.stale_source_inputs[experiment_path] = {
            "experiment_path": experiment_path,
            "inventory_path": entry["inventory_path"],
            "source_files_sha256": inventory_fingerprint["source_files_sha256"],
            "artifact_listing_sha256": canonical_json_hash(artifact_listing),
            "inventory_fingerprint_sha256": inventory_fingerprint["fingerprint_sha256"],
        }

    def _failed_prerequisite_hashes(self) -> list[dict[str, str]]:
        hashes = {}
        for issue in self.issues:
            issue_path = issue["path"]
            path = self.repo / Path(*PurePosixPath(issue_path).parts)
            file_hash = _hash_if_file(path)
            if file_hash is not None:
                hashes[issue_path] = file_hash
        return [{"path": path, "sha256": hashes[path]} for path in sorted(hashes)]

    def _stale_manifest_input_hashes(self) -> list[dict[str, str]]:
        return [
            self.stale_manifest_inputs[manifest_path]
            for manifest_path in sorted(self.stale_manifest_inputs)
        ]

    def _stale_source_input_hashes(self) -> list[dict[str, str]]:
        return [
            self.stale_source_inputs[experiment_path]
            for experiment_path in sorted(self.stale_source_inputs)
        ]

    def _issue(
        self,
        code: str,
        message: str,
        *,
        path: str,
        entry: dict[str, Any] | None = None,
    ) -> None:
        issue = {
            "severity": "error",
            "code": code,
            "message": message,
            "path": path,
            "question_path": entry["question_path"] if entry else None,
            "experiment_path": entry["experiment_path"] if entry else None,
        }
        self.issues.append(issue)


def _write_report(config: dict[str, Any], report: dict[str, Any], output_path: Path) -> None:
    report_path = config["paper"]["audit_report"]
    try:
        write_json_atomic(output_path, report)
    except OSError as exc:
        raise AuditError(f"could not write audit report: {report_path}: {exc}") from exc


def _resolve_audit_report_output(repo: Path, config: dict[str, Any]) -> Path:
    report_path = config["paper"]["audit_report"]
    report_relative = _normalized_repo_relative_path(report_path, label="paper.audit_report")
    if report_relative == "PAPER.md":
        raise AuditError("paper.audit_report must not target repository-root PAPER.md")

    protected_paths = [
        (
            config["paper"]["draft_output"],
            "paper.audit_report must not target protected paper.draft_output",
        ),
        (
            config["paper"]["final_output"],
            "paper.audit_report must not target protected paper.final_output",
        ),
        (
            _render_state_path(config),
            "paper.audit_report must not target render state output",
        ),
        (
            _manifest_path(config),
            "paper.audit_report must not target discovery manifest",
        ),
    ]
    output_path = _resolve_report_output_path(repo, report_path)
    _reject_protected_path_collisions(
        repo,
        output_path,
        report_relative,
        protected_paths,
    )
    if output_path.is_dir():
        raise AuditError(f"paper.audit_report output path is a directory: {report_path}")
    return output_path


def _reject_protected_path_collisions(
    repo: Path,
    output_path: Path,
    report_relative: str,
    protected_paths: list[tuple[str, str]],
) -> None:
    resolved_output_path = output_path.resolve(strict=False)
    for protected_path, message in protected_paths:
        if report_relative == _normalized_repo_relative_path(
            protected_path,
            label="protected output",
        ):
            raise AuditError(message)
    for protected_path, message in protected_paths:
        protected_output = _resolve_repo_relative_target(repo, protected_path)
        if (
            protected_output == output_path
            or protected_output.resolve(strict=False) == resolved_output_path
        ):
            raise AuditError(message)


def _load_manifest_for_output_protection(
    repo: Path,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    manifest_path = _manifest_path(config)
    try:
        with (repo / manifest_path).open(encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    try:
        validate_artifact("manifest.schema.json", manifest)
    except ValidationError:
        return None
    return manifest


def _reject_manifest_artifact_collisions(
    repo: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    output_path: Path,
) -> None:
    report_relative = _normalized_repo_relative_path(
        config["paper"]["audit_report"],
        label="paper.audit_report",
    )
    protected_paths: list[tuple[str, str]] = []
    for entry in manifest["experiments"]:
        protected_paths.extend(
            [
                (
                    entry["inventory_path"],
                    "paper.audit_report must not target manifest-recorded inventory_path",
                ),
                (
                    entry["evidence_path"],
                    "paper.audit_report must not target manifest-recorded evidence_path",
                ),
            ]
        )
    _reject_protected_path_collisions(
        repo,
        output_path,
        report_relative,
        protected_paths,
    )


def _normalized_repo_relative_path(path: str, *, label: str) -> str:
    if not is_repo_relative_posix(path):
        raise AuditError(f"{label} path must be repo-relative POSIX: {path}")
    return PurePosixPath(*PurePosixPath(path).parts).as_posix()


def _resolve_report_output_path(repo: Path, path: str) -> Path:
    parts = PurePosixPath(path).parts
    current = repo
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            relative = current.relative_to(repo).as_posix()
            if index == len(parts) - 1:
                raise AuditError(f"paper.audit_report output path is a symlink: {path}")
            raise AuditError(f"paper.audit_report output path contains a symlink: {relative}")
        if not current.exists():
            break
    return repo / Path(*parts)


def _resolve_repo_relative_target(repo: Path, path: str) -> Path:
    parts = PurePosixPath(path).parts
    return repo / Path(*parts)


def _with_blocker_messages(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**blocker, "message": _blocker_message(blocker)} for blocker in blockers]


def _blocker_message(blocker: dict[str, Any]) -> str:
    code = blocker["code"]
    experiment_path = blocker.get("experiment_path")
    messages = {
        "missing_semantic_analysis": "Experiment is missing semantic analysis.",
        "unresolved_preanalysis_blocker": "Experiment has unresolved pre-analysis blockers.",
        "needs_human_review": "Experiment requires human review before publication.",
        "unresolved_evidence_conflict": "Experiment has unresolved evidence conflicts.",
        "unresolved_evidence_blocker": "Experiment has missing or unsupported evidence.",
        "no_experiments_discovered": "No experiments were discovered in the manifest.",
    }
    message = messages[code]
    if experiment_path is None:
        return message
    return f"{message} ({experiment_path})"


def _manifest_issue_code(message: str) -> str:
    if "missing discovery manifest" in message:
        return "missing_discovery_manifest"
    if "invalid discovery manifest" in message:
        return "invalid_discovery_manifest"
    if "stale discovery manifest" in message:
        return "stale_discovery_manifest"
    return "manifest_error"


def _inventory_issue_code(message: str) -> str:
    if "missing artifact inventory" in message:
        return "missing_inventory"
    if "invalid artifact inventory" in message:
        return "invalid_inventory"
    if "stale artifact inventory" in message:
        return "stale_inventory"
    if "does not match manifest entry" in message:
        return "inventory_experiment_mismatch"
    return "inventory_error"


def _hash_if_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return sha256_file(path)
    except OSError:
        return None


def _relevant_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "questions": config["questions"],
        "paper": {
            "work_directory": config["paper"]["work_directory"],
            "draft_output": config["paper"]["draft_output"],
            "audit_report": config["paper"]["audit_report"],
        },
        "audit": config["audit"],
    }
