from __future__ import annotations

from typing import Any

from paperctl._support.sorting import posix_path_sort_key


PRIMARY_BLOCKERS = {
    "needs_human_review": ("needs_human_review", 0),
    "blocked": ("unresolved_preanalysis_blocker", 1),
    "analysis_candidate": ("missing_semantic_analysis", 2),
}
EVIDENCE_BLOCKERS = {
    "conflicting": ("unresolved_evidence_conflict", 3),
    "missing": ("unresolved_evidence_blocker", 4),
    "unsupported": ("unresolved_evidence_blocker", 5),
}


def derive_publication_blockers(
    manifest: dict[str, Any],
    evidence_packets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    experiments = manifest["experiments"]
    if not experiments:
        return [
            {
                "severity": "blocker",
                "code": "no_experiments_discovered",
                "question_path": None,
                "experiment_path": None,
            }
        ]

    packet_by_experiment = {packet["experiment_path"]: packet for packet in evidence_packets}
    blockers: list[dict[str, Any]] = []
    for entry in experiments:
        experiment_path = entry["experiment_path"]
        packet = packet_by_experiment[experiment_path]
        emitted_codes: set[str] = set()

        primary = PRIMARY_BLOCKERS[packet["preanalysis_disposition"]][0]
        blockers.append(_blocker(primary, entry, packet))
        emitted_codes.add(primary)

        evidence_status = packet["evidence_status"]
        if evidence_status in EVIDENCE_BLOCKERS:
            evidence_code = EVIDENCE_BLOCKERS[evidence_status][0]
            if evidence_code not in emitted_codes:
                blockers.append(_blocker(evidence_code, entry, packet))

    return sorted(blockers, key=_blocker_sort_key)


def _blocker(
    code: str,
    manifest_entry: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    return {
        "severity": "blocker",
        "code": code,
        "question_path": manifest_entry["question_path"],
        "experiment_path": manifest_entry["experiment_path"],
        "preanalysis_disposition": packet["preanalysis_disposition"],
        "evidence_status": packet["evidence_status"],
    }


def _blocker_sort_key(blocker: dict[str, Any]) -> tuple[Any, ...]:
    question_path = blocker.get("question_path") or ""
    experiment_path = blocker.get("experiment_path") or ""
    return (
        *posix_path_sort_key(question_path),
        *posix_path_sort_key(experiment_path),
        _blocker_priority(blocker["code"]),
        blocker["code"],
    )


def _blocker_priority(code: str) -> int:
    priorities = {
        "needs_human_review": 0,
        "unresolved_preanalysis_blocker": 1,
        "missing_semantic_analysis": 2,
        "unresolved_evidence_conflict": 3,
        "unresolved_evidence_blocker": 4,
        "no_experiments_discovered": 5,
    }
    return priorities[code]
