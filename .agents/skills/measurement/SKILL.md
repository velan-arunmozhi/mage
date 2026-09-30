---
name: measurement
description: >-
  Apply the MAGE Measurement Model to define reproducible quantities from agent
  run telemetry and compare them with declared baselines, budgets, or bounds.
  Use when designing experiment measures, analyzing baseline and MAGE runs,
  validating measurement records, or reporting correctness, durable throughput,
  reconstruction cost, defect escape, human attention, and resource use.
  Measurement produces evidence; enforcement decisions belong to a separate policy.
---

# Measurement

Use this skill to answer:

> How much correct, durable work does an agent produce, at what reconstruction
> and human-attention cost, and how does it compare with a baseline or declared bound?

Turn run observations into reproducible quantities. Define each quantity's unit,
scope, time window, filters, aggregation, and reference before interpreting its value.
Keep every reported result attributable to its source observations.

## Core rule

Raw telemetry becomes a measurement only when its meaning and comparison are defined.
Declare baselines, budgets, targets, and tolerances separately from observations.
Preserve missing values as `unknown` and retain the margin behind each conclusion.
Leave warning, adapting, degrading, and gating to a separate response policy.

```mermaid
flowchart LR
  accTitle: Measurement model from observations to interpreted results
  accDescr: Run observations are normalized into quantities, aggregated, and compared with a separately declared baseline or bound. The comparison produces evidence; a separate response policy determines any consequence.

  O[Run observations] --> N[Normalized quantities]
  N --> A[Aggregation]
  A --> C[Comparison]
  B[Declared baseline or bound] --> C
  C --> E[Result with margin]
  E -. interpreted by .-> R[Separate response policy]
```

## How to use this skill

1. **State the engineering question and scope.** Identify the task, run, condition,
   repository revision, and unit of analysis. For the initial MAGE experiment, use
   [MAGE Project Guidance](../../../agent-guidance-docs/PROJECT_GUIDANCE.md) for
   the study contract and unresolved controls.
2. **Choose the measurement chain.** Use the chains below. Prioritize correct and
   accepted completion, then durable throughput, reconstruction cost, and defect escape.
3. **Define the quantity before calculating it.** Record its semantics, provenance,
   missing-data policy, and separately declared reference using the definition below.
   For rates, state the denominator; for composites, use only approved weights.
4. **Validate the evidence and comparison.** Check the invariants and validation
   criteria below. If required evidence is unavailable or the definitions differ,
   report `unknown` or `not_comparable`.
5. **Calculate and report the result.** Preserve the observed value, reference,
   delta, margin, uncertainty where available, and evidence references. Report
   missingness and comparability limits alongside the conclusion.

## Measurement chains

Choose the chain that answers the engineering question. Keep the chains distinct;
do not collapse them into one score.

| Chain | Source observations | Derived quantity | Reference | Interpretation |
| --- | --- | --- | --- | --- |
| Correctness and acceptance | Task result, test results, benchmark verdict, reviewer acceptance | Completion or acceptance rate | Task acceptance criteria; baseline condition | Whether the treatment preserves or improves correct completion |
| Durable throughput | Landed changes, retained generated code, rework, churn, corrective patches | Retained work per run; rework rate | Baseline distribution or declared tolerance | Whether output survives review and later correction |
| Reconstruction cost | Files read, searches, repeated reads, navigation calls, input tokens, time to first implementation | Reconstruction actions or cost per accepted task | Baseline distribution | Whether explicit models reduce repeated recovery of repository facts |
| Defect escape | Regressions, reopened tasks, architecture violations, policy violations, late failures | Escaped defects or violations per accepted task | Zero where the acceptance contract requires none; otherwise a declared tolerance | Whether apparent efficiency hides lower quality |
| Human-attention burden | Interventions, clarifications, review time, manual corrections, rejected or redirected outputs | Human minutes or interventions per accepted task | Baseline distribution | Whether the treatment reduces work transferred to people |
| Efficiency | Wall-clock time, latency, total tokens, tool calls, attempts, iterations | Resource use per accepted task | Baseline distribution or resource budget | Whether an accepted result consumes fewer resources |
| Bootstrap cost and quality | Bootstrap time and tokens, human corrections, extraction errors, useful coverage, stale facts | Up-front cost; extraction precision and coverage | Declared bootstrap budget and quality thresholds | Whether the reusable models repay their construction cost |

Correct and accepted completion is the primary outcome.
Durable throughput, reconstruction cost, and defect escape follow in that order.
Token or time savings do not establish success when correctness declines.

## Define a measurement

Every measured quantity must declare enough context to reproduce and interpret it.
Use one record per quantity definition.

```yaml
id: reconstruction.files-read
model_class: measurement
question: How many distinct repository files did the agent inspect before its first implementation edit?
scope:
  experiment: mage-initial
  unit_of_analysis: run
  conditions: [baseline, mage]
claim_type: observed
source_authority: generated_model
source_refs:
  - run_event_log
generated_at: 2026-09-23T00:00:00Z
generator_version: commit-or-version
confidence: known
property: files_read can be compared between matched conditions
quality_attribute: reconstruction_cost

quantity:
  name: files_read
  unit: distinct_files
  value_type: integer
  direction: lower_is_better
  aggregation: count_distinct
  time_window:
    start: run_started
    end: first_implementation_edit
  filters:
    include: repository_file_reads
    exclude: harness_bootstrap_reads

reference:
  kind: matched_baseline
  value: unknown
  unit: distinct_files
  tolerance: unknown

missing_data:
  representation: unknown
  policy: exclude_from_calculation_and_report_missingness
```

The example records a definition, not a result.
The baseline value and tolerance stay `unknown` until the experiment supplies or declares them.

## Required fields

### Identity and provenance

- `id`: Stable identifier for the quantity.
- `model_class`: Always `measurement` for records governed by this model.
- `question`: The engineering question the quantity helps answer.
- `scope`: Repository revision, task, run, condition, and unit of analysis.
- `claim_type`: `observed`, `declared`, or `derived`.
- `source_authority`: The authoritative source for the value or bound.
- `source_refs`: Event logs, test reports, review records, configuration, or human decisions used to produce the value.
- `generated_at` and `generator_version`: Provenance required to reproduce derived values.
- `confidence`: `known`, `inferred`, or `uncertain`.

### Quantity semantics

- `name`: Canonical quantity name.
- `unit`: Unit shared by the observation, derived value, and reference.
- `value_type`: Numeric representation and permitted range.
- `direction`: `higher_is_better`, `lower_is_better`, `target`, or `descriptive`.
- `aggregation`: Exact function used to combine observations.
- `time_window`: Start and end events, timestamps, or commit interval.
- `filters`: Included and excluded events.

### Reference semantics

- `kind`: `fixed_bound`, `budget`, `capacity_envelope`, `matched_baseline`, or `target_range`.
- `value`: The declared reference value or interval.
- `unit`: Must be compatible with the measured quantity.
- `tolerance`: Acceptable variation around the reference.
- `source_refs`: Decision, configuration, or baseline data that supplied the reference.

## Report a comparison

Use a result record that retains the values needed to inspect the conclusion.
The values below are illustrative, not experiment evidence.

```yaml
measurement_id: reconstruction.files-read
run_id: run-0001
condition: mage
observed_value: 41
reference_value: 58
unit: distinct_files
delta: -17
relative_delta: -0.2931
margin_to_bound: null
status: lower_than_reference
uncertainty: null
evidence_refs:
  - runs/run-0001/events.jsonl
```

`status` summarizes the comparison but never replaces the underlying values.
When no valid comparison exists, use `unknown` or `not_comparable`; do not manufacture a pass or fail.

## Invariants

Preserve these rules when defining, calculating, validating, or reporting measurements:

1. **Compatible comparisons.** Compare only quantities with compatible definitions, units, scopes, time windows, filters, and aggregation methods.
2. **Separate references.** Store baselines, budgets, targets, tolerances, and capacity envelopes separately from observations.
3. **Explicit unknowns.** Missing, stale, or invalid observations remain `unknown`; they never become zero, empty, false, or permitted.
4. **Preserved margin.** Retain the observed value, reference value, delta, and uncertainty where available. Do not reduce the record to pass or fail.
5. **Traceable derivation.** Every derived quantity names its source observations and derivation version.
6. **No mixed denominators.** Rate measures declare their denominator, such as `per_run`, `per_attempted_task`, or `per_accepted_task`.
7. **No hidden enforcement.** A comparison reports evidence. A separate policy decides whether to observe, warn, adapt, degrade, or gate.
8. **Primary-outcome priority.** Efficiency gains cannot offset a decline in correctness unless the study protocol explicitly defines that tradeoff.

## Derived relations

Use explicit formulas and define the denominator at each site.
The following relations are starting points, not approved success thresholds.

```text
acceptance_rate = accepted_tasks / attempted_tasks

retained_work_rate = retained_generated_changes / landed_generated_changes

rework_rate = corrective_changes / landed_changes

reconstruction_cost = weighted_sum(
  file_reads,
  searches,
  repeated_reads,
  navigation_calls,
  input_tokens,
  time_to_first_implementation
)

defect_escape_rate = escaped_defects / accepted_tasks

human_attention_per_task = human_attention_minutes / attempted_tasks

efficiency_per_accepted_task = total_resource_use / accepted_tasks
```

Do not use `reconstruction_cost` as a composite until the team approves its weights.
Until then, report its components separately.

## Validate before reporting

Reject or flag a measurement when:

- the quantity or reference has no unit;
- the observation and reference units are incompatible;
- the time window or unit of analysis is absent;
- an aggregation has no declared function;
- a rate has no denominator;
- a derived value has no source references or generator version;
- missing data has been encoded as zero;
- baseline and treatment runs use different definitions;
- the repository revision, task, harness, foundation model, tool access, limits, or retry policy differs across a matched comparison;
- a result contains only a status and discards the observed value or margin.

## Initial MAGE experiment

The repository revision, task set, agent harness, foundation model, tool access, resource limits, retry policy, and numeric success thresholds remain open decisions in the project guidance.
Define their required fields, but do not fill them with inferred values. Check the
current project guidance for declared decisions before running a comparison.

For the first fixture, select one measure from each of the four primary outcome groups:

1. accepted completion;
2. retained work or rework;
3. one direct reconstruction observation, such as distinct files read before the first implementation edit;
4. escaped defects or rule violations.

Add human-attention, efficiency, and bootstrap measures after the event schema can collect them consistently.

## Deliverable

For a measurement-design task, provide the quantity definitions, required evidence,
declared references, and unresolved fields. For an analysis task, provide comparison
records and a concise interpretation with missingness and comparability limits.
For a validation task, identify invalid records and the fields or evidence needed
to repair them. Match the deliverable to the user's request; defining a measure
does not authorize changing an enforcement policy.

## Sources

- [*Model-Based Agentic Software Engineering*](../../../agent-guidance-docs/mage-book-2.pdf), Chapter 2, Section 2.6, pages 76-79: quantities, relations, separately declared bounds, tolerance, margin, and the separation of measurement from enforcement. Consult it when interpreting the model's conceptual basis.
- [MAGE Project Guidance](../../../agent-guidance-docs/PROJECT_GUIDANCE.md): shared metadata, experimental measures, priority order, unresolved controls, and explicit missing values. Consult it when applying this skill to the initial experiment.
