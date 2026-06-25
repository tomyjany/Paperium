# PRE-ANALYSIS EVIDENCE DRAFT

> This is a pre-analysis evidence draft. It contains deterministic evidence listings only, is not a publishable paper, and is never promoted to PAPER.md in Milestone 1.

## Known Publication Blockers

| Code | Experiment | Evidence Status | Preanalysis Disposition |
|---|---|---|---|
| missing_semantic_analysis | questions/q001-throughput/experiments/exp001-completed | available | analysis_candidate |
| missing_semantic_analysis | questions/q001-throughput/experiments/exp002-incomplete | available | analysis_candidate |
| needs_human_review | questions/q001-throughput/experiments/exp003-structured-conflict | conflicting | needs_human_review |
| unresolved_evidence_conflict | questions/q001-throughput/experiments/exp003-structured-conflict | conflicting | needs_human_review |
| missing_semantic_analysis | questions/q001-throughput/experiments/exp004-smoke-and-full | available | analysis_candidate |
| missing_semantic_analysis | questions/q001-throughput/experiments/exp005-unsupported-and-previews | available | analysis_candidate |
| missing_semantic_analysis | questions/q001-throughput/experiments/legacy-baseline | available | analysis_candidate |

## Question `questions/q001-throughput`

- README: `questions/q001-throughput/README.md`
- README SHA-256: `sha256:f37d12062c60fef159ac7452ff7c715cb4859e1b72374a3723a2e22d7b59c8df`
- Discovered experiments: `6`

### Experiment `questions/q001-throughput/experiments/exp001-completed`

- Evidence packet: `paper/work/evidence/questions/q001-throughput/experiments/exp001-completed.json`
- preanalysis_disposition: `analysis_candidate`
- execution_status: `completed`
- evidence_status: `available`
- reason_codes: `none`

#### Canonical Facts

| Fact ID | Value | Type | Unit | Source | Selector |
|---|---|---|---|---|---|
| throughput_pages_per_second | 42.5 | number | pages/s | questions/q001-throughput/experiments/exp001-completed/outputs/experiment_report.json | /canonical_facts/0/value |

#### Observed Values

None.

#### Previews

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp001-completed/README.md | lines 1-1 | \\# Exp001 Completed |  |

#### Diagnostics

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp001-completed/README.md | lines 1-3 | line_count=3 |  |

#### Conflicts

None.

#### Warnings

None.

#### Unsupported Artifacts

None.

### Experiment `questions/q001-throughput/experiments/exp002-incomplete`

- Evidence packet: `paper/work/evidence/questions/q001-throughput/experiments/exp002-incomplete.json`
- preanalysis_disposition: `analysis_candidate`
- execution_status: `unknown`
- evidence_status: `available`
- reason_codes: `none`

#### Canonical Facts

None.

#### Observed Values

| Value | Type | Unit | Source | Selector |
|---|---|---|---|---|
| incomplete | string | null | questions/q001-throughput/experiments/exp002-incomplete/outputs/status.json | /execution_status |
| 21.5 | number | null | questions/q001-throughput/experiments/exp002-incomplete/outputs/status.json | /observations/throughput_pages_per_second |
| input corpus was not available | string | null | questions/q001-throughput/experiments/exp002-incomplete/outputs/status.json | /reason |

#### Previews

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp002-incomplete/README.md | lines 1-1 | \\# Exp002 Incomplete |  |

#### Diagnostics

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp002-incomplete/README.md | lines 1-6 | line_count=6 |  |

#### Conflicts

None.

#### Warnings

None.

#### Unsupported Artifacts

None.

### Experiment `questions/q001-throughput/experiments/exp003-structured-conflict`

- Evidence packet: `paper/work/evidence/questions/q001-throughput/experiments/exp003-structured-conflict.json`
- preanalysis_disposition: `needs_human_review`
- execution_status: `completed`
- evidence_status: `conflicting`
- reason_codes: `canonical_conflict`

#### Canonical Facts

| Fact ID | Value | Type | Unit | Source | Selector |
|---|---|---|---|---|---|
| throughput_pages_per_second | 11.1 | number | pages/s | questions/q001-throughput/experiments/exp003-structured-conflict/outputs/run-a.json | /metrics/throughput_pages_per_second |
| throughput_pages_per_second | 12.2 | number | pages/s | questions/q001-throughput/experiments/exp003-structured-conflict/outputs/run-b.json | /metrics/throughput_pages_per_second |

#### Observed Values

None.

#### Previews

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp003-structured-conflict/README.md | lines 1-1 | \\# Exp003 Structured Conflict |  |

#### Diagnostics

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp003-structured-conflict/README.md | lines 1-4 | line_count=4 |  |

#### Conflicts

| Reason | Fact ID | Sources |
|---|---|---|
| canonical_conflict | throughput_pages_per_second | questions/q001-throughput/experiments/exp003-structured-conflict/outputs/run-a.json /metrics/throughput_pages_per_second; questions/q001-throughput/experiments/exp003-structured-conflict/outputs/run-b.json /metrics/throughput_pages_per_second |

#### Warnings

None.

#### Unsupported Artifacts

None.

### Experiment `questions/q001-throughput/experiments/exp004-smoke-and-full`

- Evidence packet: `paper/work/evidence/questions/q001-throughput/experiments/exp004-smoke-and-full.json`
- preanalysis_disposition: `analysis_candidate`
- execution_status: `unknown`
- evidence_status: `available`
- reason_codes: `none`

#### Canonical Facts

| Fact ID | Value | Type | Unit | Source | Selector |
|---|---|---|---|---|---|
| throughput_pages_per_second | 37.75 | number | pages/s | questions/q001-throughput/experiments/exp004-smoke-and-full/outputs/full.json | /throughput_pages_per_second |

#### Observed Values

| Value | Type | Unit | Source | Selector |
|---|---|---|---|---|
| full | string | null | questions/q001-throughput/experiments/exp004-smoke-and-full/outputs/full.json | /mode |
| smoke | string | null | questions/q001-throughput/experiments/exp004-smoke-and-full/outputs/smoke.json | /mode |
| 3.0 | number | null | questions/q001-throughput/experiments/exp004-smoke-and-full/outputs/smoke.json | /throughput_pages_per_second |

#### Previews

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp004-smoke-and-full/README.md | lines 1-1 | \\# Exp004 Smoke And Full |  |

#### Diagnostics

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp004-smoke-and-full/README.md | lines 1-4 | line_count=4 |  |

#### Conflicts

None.

#### Warnings

None.

#### Unsupported Artifacts

None.

### Experiment `questions/q001-throughput/experiments/exp005-unsupported-and-previews`

- Evidence packet: `paper/work/evidence/questions/q001-throughput/experiments/exp005-unsupported-and-previews.json`
- preanalysis_disposition: `analysis_candidate`
- execution_status: `unknown`
- evidence_status: `available`
- reason_codes: `none`

#### Canonical Facts

None.

#### Observed Values

None.

#### Previews

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/README.md | lines 1-1 | \\# Exp005 Unsupported And Previews |  |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/credentials.txt | lines 1-1 | API\\\_KEY=[REDACTED] |  |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/events.jsonl | lines 1-1 | {"row": 1, "value": 10} |  |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/events.jsonl | lines 2-2 | {"row": 2, "value": 20} |  |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/run.log | lines 1-1 | line 1: setup |  |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/run.log | lines 2-2 | line 2: warmup |  |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/run.log | lines 5-5 | line 5: complete |  |

#### Diagnostics

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/README.md | lines 1-4 | line_count=4 |  |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/credentials.txt | lines 1-1 | line_count=1 pattern_counts={'ERROR': 0, 'WARN': 0, 'WARNING': 0, 'FATAL': 0, 'TRACEBACK': 0} | {"byte_limit_truncated":false,"calculation_label":"log_line_summary","inspected_byte_count":31,"inspected_line_count":1,"inspected_line_end":1,"inspected_line_start":1,"omitted_byte_count":0,"pattern_counts":{"ERROR":0,"FATAL":0,"TRACEBACK":0,"WARN":0,"WARNING":0}} |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/events.jsonl | lines 1-5 | numeric field row: count=5 min=1.0 max=5.0 | {"byte_limit_truncated":false,"calculation_label":"jsonl_numeric_field_summary","field":"row","inspected_byte_count":120,"inspected_line_count":5,"inspected_line_end":5,"inspected_line_start":1,"non_finite_omitted_count":0,"numeric_value_count":5,"omitted_byte_count":0,"omitted_value_count":0,"summary":{"count":5,"max":5.0,"min":1.0}} |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/events.jsonl | lines 1-5 | numeric field value: count=5 min=10.0 max=50.0 | {"byte_limit_truncated":false,"calculation_label":"jsonl_numeric_field_summary","field":"value","inspected_byte_count":120,"inspected_line_count":5,"inspected_line_end":5,"inspected_line_start":1,"non_finite_omitted_count":0,"numeric_value_count":5,"omitted_byte_count":0,"omitted_value_count":0,"summary":{"count":5,"max":50.0,"min":10.0}} |
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/run.log | lines 1-5 | line_count=5 pattern_counts={'ERROR': 0, 'WARN': 0, 'WARNING': 0, 'FATAL': 0, 'TRACEBACK': 0} | {"byte_limit_truncated":false,"calculation_label":"log_line_summary","inspected_byte_count":84,"inspected_line_count":5,"inspected_line_end":5,"inspected_line_start":1,"omitted_byte_count":0,"pattern_counts":{"ERROR":0,"FATAL":0,"TRACEBACK":0,"WARN":0,"WARNING":0}} |

#### Conflicts

None.

#### Warnings

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/credentials.txt | none | redacted 1 secret-like value\(s\) | {"redaction_category":"secret_like","redaction_count":1,"warning_type":"redaction"} |

#### Unsupported Artifacts

| Artifact | Reason |
|---|---|
| questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/model.bin | unsupported_only |

### Experiment `questions/q001-throughput/experiments/legacy-baseline`

- Evidence packet: `paper/work/evidence/questions/q001-throughput/experiments/legacy-baseline.json`
- preanalysis_disposition: `analysis_candidate`
- execution_status: `unknown`
- evidence_status: `available`
- reason_codes: `none`

#### Canonical Facts

None.

#### Observed Values

| Value | Type | Unit | Source | Selector |
|---|---|---|---|---|
| completed | string | null | questions/q001-throughput/experiments/legacy-baseline/outputs/summary.json | /execution_status |
| 18.25 | number | null | questions/q001-throughput/experiments/legacy-baseline/outputs/summary.json | /throughput_pages_per_second |

#### Previews

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/legacy-baseline/README.md | lines 1-1 | \\# Legacy Baseline |  |

#### Diagnostics

| Source | Selector | Message | Detail |
|---|---|---|---|
| questions/q001-throughput/experiments/legacy-baseline/README.md | lines 1-3 | line_count=3 |  |

#### Conflicts

None.

#### Warnings

None.

#### Unsupported Artifacts

None.
