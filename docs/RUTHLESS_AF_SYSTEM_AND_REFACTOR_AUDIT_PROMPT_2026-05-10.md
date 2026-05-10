# Ruthless AF System And Refactor Audit Prompt (2026-05-10)

*Easily copyable path: `/Users/davidusa/REPOS/Article_Finder_v3_2_3/docs/RUTHLESS_AF_SYSTEM_AND_REFACTOR_AUDIT_PROMPT_2026-05-10.md`*

This prompt is for a deep audit of **Article Finder v3.2.3** as a living system, not merely as a codebase. The audit must examine:

- the end-to-end AF pipeline,
- the contract surface,
- the live database state,
- the AE handoff and return path,
- the health-monitoring surface,
- and the refactor hazards that would matter before, during, and after a serious restructuring.

The audit must not be polite. It must not stop at the first defect. It must not confuse “tests pass” with “the system is well-governed.” It must pursue every claim to its operational ground.

## 1. Scope

The AF audit covers six surfaces.

### Surface A — The canonical AF pipeline

The audit must determine whether AF is truly a coherent feeder pipeline rather than a collection of partially-related tools.

Questions:

- What is the actual dependency graph among:
  - `ingest/`
  - `triage/`
  - `search/`
  - `eater_interface/`
  - `knowledge/`
  - `ui/`
  - `cli/`
- What is the canonical entrypoint for ordinary operation?
- Are there multiple competing entrypoints that produce materially different state?
- Which stages are local and paper-level, and which are corpus-level?
- Which stages are synchronous, and which are queue-like?
- Which stages are effectively dead, stubbed, or only documentary?

### Surface B — The contract surface

Audit every AF contract now present:

- `contracts/AF_PIPELINE_AUTHORITY_2026-05-10.md`
- `contracts/AF_PDF_ATTACHMENT_INTEGRITY_AUTHORITY_2026-05-10.md`
- `contracts/AF_AE_HANDOFF_AUTHORITY_2026-05-10.md`
- `contracts/AF_SYSTEM_HEALTH_AUTHORITY_2026-05-10.md`
- `contracts/AF_QUARANTINE_AND_RECOVERY_AUTHORITY_2026-05-10.md`
- `contracts/AF_WEEKLY_SYSTEM_HEALTH_AUTHORITY_2026-05-10.md`
- `contracts/AF_SYSTEM_HEALTH_SUCCESS_CONDITIONS_2026-05-10.json`
- `contracts/AF_WEEKLY_SYSTEM_HEALTH_SUCCESS_CONDITIONS_2026-05-10.json`

For each contract, determine:

- what real writes it governs,
- what scripts actually perform those writes,
- what verifier checks the invariant,
- what failure modes are specified,
- what last-mile behaviour is missing,
- and whether the contract overstates reality.

### Surface C — The live DB

The live AF DB is:

- `data/article_finder.db`

The audit must:

- enumerate all tables,
- identify which are active, empty, orphaned, or merely provisioned,
- identify which code writes each table,
- identify which code reads each table,
- and identify where the DB schema is enforcing invariants versus merely hoping for them.

### Surface D — The AE handoff and return path

AF’s purpose is not merely to collect papers. It is to decide, hand off, and truthfully remember what happened.

The audit must verify:

- whether the AF → AE path is singular or forked,
- whether the job bundle writer is singular or forked,
- whether the AE output parser is singular or forked,
- whether `ae_job_path`, `ae_output_path`, `ae_status`, `ae_n_claims`, `ae_n_rules`, and `ae_confidence` are written honestly,
- whether empty or stale AE state is detectable,
- whether the UI and knowledge surfaces depend on tables that are in fact empty.

### Surface E — Health monitoring

AF now has:

- `cli/main.py doctor --deep`
- `scripts/run_system_health.py`
- `scripts/verify_af_integrity.py`
- `scripts/verify_af_quarantine.py`
- `scripts/run_weekly_system_health.py`

The audit must determine whether these genuinely measure system health, or only a narrow subset of path integrity.

### Surface F — Refactor hazard

The audit must explicitly search for every error class that is likely to appear when a real refactor begins.

This includes:

- hidden coupling,
- vocabulary drift,
- state-machine ambiguity,
- old and new implementations coexisting,
- under-constrained schema surfaces,
- green health checks that miss semantic errors,
- path truth without state truth,
- and empty-but-live tables whose callers assume fullness.

## 2. Methods

Documentary reading is insufficient. Every serious finding must be grounded by at least one of:

### Method A — Code trace

Read the actual source path. If a contract says “the system writes X,” find the write. If a verifier claims “hard integrity,” read the exact query or file check.

### Method B — Database query

Query the live DB for:

- row counts,
- status distributions,
- vocabulary drift,
- orphan rows,
- missing output references,
- timestamp anomalies,
- and evidence of unused or empty tables.

### Method C — Execution trace

Run:

- `python3 scripts/run_system_health.py`
- `python3 -m pytest -q tests`
- any other canonical integrity scripts the auditor deems necessary

Do not merely read them. Execute them.

### Method D — Refactor-risk trace

Ask, for each large module:

- what it imports,
- what imports it,
- what state assumptions it makes,
- what would break if it were split,
- and whether its callers rely on undocumented side effects.

## 3. Panel

The six-to-eight-person live panel, after AI audit, should include these people or their nearest living equivalents:

1. **Leslie Lamport**
- formal specification
- state transitions
- invariants
- contract precision

2. **Pat Helland**
- idempotence
- transactional honesty
- recoverability
- partial-completion discipline

3. **Andy Pavlo**
- schema discipline
- migration discipline
- DB operational realism

4. **Joe Hellerstein**
- dataflow
- pipeline monotonicity
- cross-stage coupling

5. **Marti Hearst**
- information retrieval
- faceted search
- practical search-system architecture

6. **Christine Borgman**
- scholarly infrastructure
- bibliographic systems
- provenance and corpus curation

7. **Martin Fowler**
- refactoring
- seams
- strangler patterns
- monolith decomposition discipline

8. **Victoria Stodden**
- reproducibility
- auditability
- external reconstruction discipline

The panel is deliberately mixed: formalists, systems builders, search specialists, librarianship-minded scholars, and refactoring experts.

## 4. Questions the audit must answer

### Q-A1. Is AF structurally coherent?

Or does it merely contain coherent parts?

### Q-A2. Is there one AE handoff stack or two?

Specifically:

- `eater_interface/job_bundle.py` vs `eater_interface/job_bundle_v2.py`
- `eater_interface/output_parser.py` vs `eater_interface/output_parser_v2.py`

Which are actually production-used? Which are merely present? Which are tested? Which are health-checked?

### Q-A3. Is the DB state vocabulary governed?

Do the live values for:

- `status`
- `triage_decision`
- `topic_decision`
- `ae_status`

fit the contract and code vocabulary? Or are there live values the contracts do not name?

### Q-A4. Do the integrity verifiers check what the contracts claim?

For example:

- if the contract says `pdf_sha256` must correspond to the actual bytes at `pdf_path`, does the verifier really hash the file?
- if the contract says AE handoff must be truthful, does the verifier detect `ae_status` without a real output bundle?

### Q-A5. Are there empty tables that pretend to be a knowledge layer?

Specifically inspect:

- `claims`
- `rules`
- `paper_facet_scores`
- `paper_embeddings`
- `extracted_tables`

Are these:

- intentionally empty,
- provisioned but unexercised,
- or evidence of a broken import path?

### Q-A6. Is the health monitor semantically deep or merely path-deep?

Can it pass while the state machine is still semantically inconsistent?

### Q-A7. Is AF using explicit migrations or ad hoc schema accretion?

Does `schema_version` tell the truth about what actually changed? Or is the schema partly maintained by opportunistic `ALTER TABLE` logic?

### Q-A8. Are large modules merely large, or dangerously over-central?

Inspect at least:

- `cli/main.py`
- `core/database.py`
- `search/bibliographer.py`
- `ingest/pdf_cataloger.py`
- `eater_interface/pipeline.py`

Classify each by:

- dispatcher bloat,
- mixed responsibilities,
- hidden side effects,
- or justified concentration.

### Q-A9. Are there missing contracts?

The audit should explicitly ask whether AF lacks contracts for:

- acquisition-source cascade
- triage/scoring authority
- AE result-ingestion authority
- facet classification authority
- inbox watcher authority
- schema/migration authority
- disaster recovery / restore protocol
- refactor transition protocol

### Q-A10. What errors are most likely during refactor?

Not vague answers. Name the concrete failure classes:

- vocabulary breakage,
- dual-stack drift,
- broken CLI dispatch,
- stale import paths,
- hidden DB assumptions,
- orphaned verifiers,
- false-green health reports,
- UI breakage from empty tables,
- and migration half-application.

## 5. Required output

The audit output must include:

1. a verdict:
- `GO`
- `GO_WITH_REPAIRS`
- `HOLD`

2. findings ordered by severity

3. explicit distinction between:
- live failures
- latent refactor hazards
- overclaims in contracts
- under-governed surfaces

4. a recommended refactor order

5. a list of contracts to tighten, verifiers to widen, and empty/live surfaces to clarify

The audit must prefer clarity to comfort. If a surface is good, say so. If a surface is claimed but not real, say that too.
