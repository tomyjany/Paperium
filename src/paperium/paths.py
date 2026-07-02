from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PaperiumPaths:
    repo: Path

    @property
    def root_dir(self) -> Path:
        return self.repo / ".paperium"

    @property
    def state_path(self) -> Path:
        return self.root_dir / "state.json"

    @property
    def ranking_md_path(self) -> Path:
        return self.root_dir / "ranking.md"

    @property
    def ranking_json_path(self) -> Path:
        return self.root_dir / "ranking.json"

    @property
    def dispositions_path(self) -> Path:
        return self.root_dir / "dispositions.md"

    @property
    def question_focus_path(self) -> Path:
        return self.root_dir / "question-focus.md"

    @property
    def question_focus_json_path(self) -> Path:
        return self.root_dir / "question-focus.json"

    def experiment_analysis_path(self, experiment: Path) -> Path:
        return experiment / ".paperium" / "analysis.md"

    def experiment_fact_check_path(self, experiment: Path) -> Path:
        return experiment / ".paperium" / "fact-check.json"

    def worker_dir(self, worker_id: str) -> Path:
        return self.root_dir / "workers" / worker_id

    def context_request_path(self, request_id: str) -> Path:
        return self.root_dir / "context-requests" / f"{request_id}.json"

    def context_decision_path(self, request_id: str) -> Path:
        return self.root_dir / "context-requests" / f"{request_id}.decision.json"

    def section_path(self, section_id: str) -> Path:
        return self.root_dir / "sections" / f"{section_id}.md"

    def section_review_path(self, section_id: str) -> Path:
        return self.root_dir / "sections" / f"{section_id}.review.json"
