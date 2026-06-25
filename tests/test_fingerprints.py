from __future__ import annotations

import pytest

from paperctl._support.jsonio import write_json_atomic


def _valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "artifact_type": "manifest",
        "experiments": [
            {
                "question_ref": "q001",
                "question_path": "questions/q001-throughput",
                "question_readme_path": None,
                "question_readme_sha256": None,
                "experiment_ref": "exp001",
                "experiment_path": "questions/q001-throughput/experiments/exp001",
                "inventory_path": "paper/work/inventories/questions/q001-throughput/experiments/exp001.json",
                "evidence_path": "paper/work/evidence/questions/q001-throughput/experiments/exp001.json",
            }
        ],
    }


def test_stage_fingerprint_records_versions_config_sources_and_prerequisites(tmp_path):
    from paperctl._support.fingerprints import (
        PrerequisiteArtifact,
        SourceFile,
        build_stage_fingerprint,
    )
    from paperctl._support.hashing import canonical_json_hash, sha256_file

    source = tmp_path / "source.txt"
    source.write_text("source\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    write_json_atomic(manifest, _valid_manifest())

    fingerprint = build_stage_fingerprint(
        stage_name="inventory",
        stage_version=1,
        schema_version=1,
        relevant_config={"paper": {"work_directory": "paper/work"}},
        source_files=[SourceFile(path="questions/q001/experiments/exp001/source.txt", file=source)],
        prerequisite_artifacts=[
            PrerequisiteArtifact(
                path="paper/work/manifest.json",
                file=manifest,
                schema_name="manifest.schema.json",
            )
        ],
        extra_inputs={"listing_sha256": "sha256:" + "a" * 64},
    )

    assert fingerprint["stage"] == {"name": "inventory", "version": 1}
    assert fingerprint["schema_version"] == 1
    assert fingerprint["config_sha256"] == canonical_json_hash(
        {"paper": {"work_directory": "paper/work"}}
    )
    assert fingerprint["source_files"] == [
        {
            "path": "questions/q001/experiments/exp001/source.txt",
            "sha256": sha256_file(source),
        }
    ]
    assert fingerprint["prerequisite_artifacts"] == [
        {
            "path": "paper/work/manifest.json",
            "schema_name": "manifest.schema.json",
            "sha256": sha256_file(manifest),
        }
    ]
    assert fingerprint["extra_inputs_sha256"] == canonical_json_hash(
        {"listing_sha256": "sha256:" + "a" * 64}
    )
    assert fingerprint["fingerprint_sha256"].startswith("sha256:")


def test_fingerprint_freshness_validates_prerequisite_schema_before_comparing(tmp_path):
    from paperctl._support.fingerprints import (
        FingerprintError,
        PrerequisiteArtifact,
        fingerprint_is_fresh,
    )

    invalid_manifest = tmp_path / "manifest.json"
    write_json_atomic(invalid_manifest, {"schema_version": 1, "artifact_type": "manifest"})
    current = {"fingerprint_sha256": "sha256:" + "a" * 64}

    with pytest.raises(FingerprintError, match="invalid prerequisite artifact"):
        fingerprint_is_fresh(
            existing=current,
            expected=current,
            prerequisite_artifacts=[
                PrerequisiteArtifact(
                    path="paper/work/manifest.json",
                    file=invalid_manifest,
                    schema_name="manifest.schema.json",
                )
            ],
        )


def test_fingerprint_freshness_compares_canonical_fingerprint_hash(tmp_path):
    from paperctl._support.fingerprints import (
        PrerequisiteArtifact,
        fingerprint_is_fresh,
    )

    manifest = tmp_path / "manifest.json"
    write_json_atomic(manifest, _valid_manifest())
    prerequisite = [
        PrerequisiteArtifact(
            path="paper/work/manifest.json",
            file=manifest,
            schema_name="manifest.schema.json",
        )
    ]

    assert fingerprint_is_fresh(
        existing={"fingerprint_sha256": "sha256:" + "a" * 64},
        expected={"fingerprint_sha256": "sha256:" + "a" * 64},
        prerequisite_artifacts=prerequisite,
    )
    assert not fingerprint_is_fresh(
        existing={"fingerprint_sha256": "sha256:" + "b" * 64},
        expected={"fingerprint_sha256": "sha256:" + "a" * 64},
        prerequisite_artifacts=prerequisite,
    )
