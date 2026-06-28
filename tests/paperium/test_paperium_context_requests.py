import json

import pytest

from paperium.context_requests import (
    ContextRequest,
    ContextRequestError,
    apply_context_decision,
    context_request_state_from_request,
    read_context_request,
    write_context_decision,
    write_context_request,
)


def test_context_request_round_trip(tmp_path):
    path = tmp_path / ".paperium/context-requests/req1.json"
    request = ContextRequest(
        id="req1",
        worker_id="w1",
        requested_paths=["questions/q001/src"],
        reason="Need shared parser",
    )
    write_context_request(path, request)
    assert "questions/q001/src" in path.read_text()
    loaded = read_context_request(path)
    assert loaded.worker_id == "w1"
    state_entry = context_request_state_from_request(
        loaded, decision_path=".paperium/context-requests/req1.decision.json"
    )
    assert state_entry["status"] == "pending"
    assert state_entry["decision_path"] == ".paperium/context-requests/req1.decision.json"
    decision_path = tmp_path / ".paperium/context-requests/req1.decision.json"
    write_context_decision(decision_path, request_id="req1", approved=True)
    assert '"approved": true' in decision_path.read_text()
    denied_path = tmp_path / ".paperium/context-requests/req1.denied.json"
    write_context_decision(denied_path, request_id="req1", approved=False)
    assert '"approved": false' in denied_path.read_text()


def test_apply_approved_context_decision_adds_expansion():
    worker = {"approved_expansions": []}
    updated = apply_context_decision(
        worker, requested_paths=["questions/q001/src"], approved=True
    )
    assert updated["approved_expansions"] == ["questions/q001/src"]


def test_apply_denied_context_decision_records_denial_without_expansion():
    worker = {"approved_expansions": [], "denied_expansions": []}
    updated = apply_context_decision(
        worker, requested_paths=["questions/q001/src"], approved=False
    )
    assert updated["approved_expansions"] == []
    assert updated["denied_expansions"] == ["questions/q001/src"]


def test_context_request_rejects_unsafe_requested_paths(tmp_path):
    for requested_paths in [
        ["/etc/passwd"],
        ["../outside"],
        ["..\\outside"],
        ["C:\\tmp\\secret"],
        ["questions\\q001\\src"],
        [""],
        "questions/q001/src",
    ]:
        path = tmp_path / ".paperium/context-requests/unsafe.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "id": "unsafe",
                    "worker_id": "w1",
                    "requested_paths": requested_paths,
                    "reason": "bad path",
                }
            )
        )
        with pytest.raises(ContextRequestError):
            read_context_request(path)
