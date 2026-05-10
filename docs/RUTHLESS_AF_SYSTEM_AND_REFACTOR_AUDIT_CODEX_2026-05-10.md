# Ruthless AF System And Refactor Audit By Codex (2026-05-10)

## Verdict

`HOLD_ON_MAJOR_REFACTOR_UNTIL_NAMED_REPAIRS_LAND`

AF is not unsound. It is in fact more coherent than many research-adjacent tools. Its tests pass, its local health checks pass, and the recent integrity and quarantine repairs are real. But it is not yet in a state where a major structural refactor should begin without first tightening several live seams.

The central judgment is this:

- AF is a real pipeline,
- but it is governed more by good local craft than by a fully aligned state model,
- and several of its most dangerous defects are second-order defects:
  - green health checks that miss semantic drift,
  - contracts that describe a narrower vocabulary than the live system actually uses,
  - and dual implementation surfaces that a refactor could easily break.

## What Was Checked

I did not merely read the repo.

I ran:

- `python3 scripts/run_system_health.py`
- `python3 -m pytest -q tests`

Results:

- AF health: `PASS`
- tests: `43 passed, 1 skipped`

I also queried the live DB:

- `data/article_finder.db`

Important live counts:

- `papers`: `16257`
- `expansion_queue`: `136`
- `claims`: `0`
- `rules`: `0`
- `paper_facet_scores`: `0`
- `paper_embeddings`: `0`
- `extracted_tables`: `0`

And I traced the main production code:

- [cli/main.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/cli/main.py)
- [core/database.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/core/database.py)
- [eater_interface/pipeline.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/pipeline.py)
- [search/bibliographer.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/search/bibliographer.py)
- [ingest/pdf_cataloger.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/ingest/pdf_cataloger.py)

## Findings

### 1. The live triage vocabulary is materially broader than the contracts and health checks admit.

This is the single most important governance finding.

The contract and schema comments tend to speak as though `triage_decision` is a closed vocabulary such as:

- `send_to_eater`
- `review`
- `reject`

But the live DB says otherwise.

Current `triage_decision` distribution:

- `pending`: `15131`
- `NULL`: `675`
- `review`: `377`
- `send_to_eater`: `73`
- `needs_review`: `1`

And the dominant state pairing is:

- `status='candidate'`
- `triage_decision='pending'`
- count: `14947`

This is not random corruption. It is an actual code path. In [search/bibliographer.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/search/bibliographer.py), deferred imports explicitly write:

- `status = 'pending_scorer'`
- `triage_decision = 'pending'`

So the right conclusion is not “the DB is dirty.” It is:

- the live state machine is wider than the contract surface says,
- and the health monitor does not check this vocabulary drift.

This matters greatly for refactor, because refactors break systems most readily where the real state machine is larger than the stated one.

### 2. AF’s health monitor is honest but too shallow.

The local health monitor passes:

- [run_system_health.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/scripts/run_system_health.py)

It runs:

- `doctor --deep`
- `validate_codebase.py`
- `verify_af_quarantine.py`

And `doctor --deep` itself depends on:

- path integrity
- import sanity
- initialization sanity
- PDF attachment integrity

But it does not detect the semantic state problems above.

It also misses another live inconsistency:

- `10` rows have `ae_status IS NOT NULL` while `ae_output_path IS NULL`

One of those even claims:

- `ae_status = 'SUCCESS'`
- with no `ae_output_path`

So the health monitor currently checks whether path references are broken, but not whether the state narrative is logically credible.

That is a serious second-order defect. The monitor is green, yet a refactor could still inherit a semantically muddled state model.

### 3. The AE handoff stack is forked.

This is the strongest direct refactor hazard.

The repo contains both old and v2 AE bundle/parser surfaces:

- [eater_interface/job_bundle.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/job_bundle.py)
- [eater_interface/job_bundle_v2.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/job_bundle_v2.py)
- [eater_interface/output_parser.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/output_parser.py)
- [eater_interface/output_parser_v2.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/output_parser_v2.py)

But the live production path is mixed.

The main pipeline still imports the old pair:

- [eater_interface/pipeline.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/pipeline.py)
  - imports `job_bundle`
  - imports `output_parser`

Meanwhile:

- [cli/main.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/cli/main.py) uses `job_bundle_v2` in one path
- [ingest/prepare_for_ae.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/ingest/prepare_for_ae.py) uses `job_bundle_v2`
- [search/discovery_orchestrator.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/search/discovery_orchestrator.py) uses `job_bundle_v2`

And there are no tests referencing:

- `output_parser_v2`
- `job_bundle_v2`

So AF is not yet on one clean AE handoff stack. It is on a transitional forked stack.

That is precisely the kind of thing that makes a large refactor dangerous, because one can “clean up” the wrong side and break the real callers.

### 4. The PDF integrity contract overclaims what the verifier actually checks.

The contract:

- [AF_PDF_ATTACHMENT_INTEGRITY_AUTHORITY_2026-05-10.md](/Users/davidusa/REPOS/Article_Finder_v3_2_3/contracts/AF_PDF_ATTACHMENT_INTEGRITY_AUTHORITY_2026-05-10.md)

states, among other things:

- `pdf_sha256` must correspond to the bytes of the file at `pdf_path`

But the verifier:

- [verify_af_integrity.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/scripts/verify_af_integrity.py)

does **not** recompute or compare those hashes. It checks:

- path existence
- duplicate `pdf_sha256` rows
- orphan PDFs
- missing job/output paths

It does not check byte-vs-hash truth.

So the contract is stronger than the actual enforcement.

This is an exact example of contract-vs-code drift.

### 5. The DB schema is much weaker than the implied state model.

AF’s DB is better than a pile of JSON files, but it is not strongly constrained.

Important schema facts:

- `papers` has `41` columns
- `papers` has `0` foreign keys
- `schema_version` has only `2` rows
- schema change discipline relies partly on:
  - monolithic `get_schema_sql()`
  - opportunistic `_ensure_columns(...)`

This is convenient, but it is weak migration governance.

The contrast with AE is instructive:

- AE has more explicit migration surfaces and more aggressive contract-driven stage bookkeeping
- AF still relies on a monolithic schema constructor with ad hoc additive repair

That means refactor risk is higher than the passing tests alone would suggest, because code moves can silently expose assumptions the schema does not defend.

### 6. The system contains large monoliths that are not yet cleanly seamed.

Largest modules:

- [cli/main.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/cli/main.py): `1749` lines
- [search/bibliographer.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/search/bibliographer.py): `1470`
- [core/database.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/core/database.py): `1009`
- [ingest/pdf_cataloger.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/ingest/pdf_cataloger.py): `981`
- [eater_interface/pipeline.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/pipeline.py): `671`

These are not automatically bad. But they are risky in different ways:

- `cli/main.py`
  - dispatcher monolith
  - many imports
  - many command families
- `core/database.py`
  - schema, CRUD, taxonomy, claims/rules, extraction tables, and stats all in one class
- `search/bibliographer.py`
  - search logic, import policy, deferred-scoring semantics, and DB writes intertwined
- `eater_interface/pipeline.py`
  - mixes orchestration with state assumptions and legacy/compatibility choices

This is enough to justify refactor. But it also means the refactor must start from seam-making, not from casual file-splitting.

### 7. The state model is conceptually muddled between `status` and `triage_decision`.

The code even admits this.

[core/database.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/core/database.py) defines:

- `get_papers_by_status(...)`

which explicitly checks **both**:

- `status`
- `triage_decision`

for “backwards compatibility.”

That is understandable as transition code. But it is not a clean model.

It means the system does not yet have a single authoritative progression field for:

- corpus lifecycle state
- versus triage judgment

This is survivable now. It is dangerous during refactor.

### 8. Much of the knowledge layer is provisioned but unexercised.

Current live counts:

- `claims`: `0`
- `rules`: `0`
- `paper_facet_scores`: `0`
- `paper_embeddings`: `0`
- `extracted_tables`: `0`

Yet the repo includes:

- UI for claims/rules/facet display
- knowledge-query code
- synthesis code
- claim graph code
- AE output parsers

This means the system has a nontrivial provisioned knowledge layer whose live data is mostly absent.

That is not inherently shameful. But it means:

- one must not confuse designed surfaces with exercised surfaces,
- and a refactor must not use “there is code for this” as evidence that the pipeline currently depends on it successfully.

### 9. `finder_run_id` appears operationally absent.

The schema and bundle surfaces name `finder_run_id` as provenance.

But the live DB query showed no non-null `finder_run_id` distribution worth reporting.

That suggests either:

- the field is presently unused,
- or the provenance discipline is not actually landing in stored rows.

This is a smaller finding, but it belongs in the same family: declared provenance surfaces that are not yet strongly live.

### 10. AF has more contracts than it did, but still not enough.

The new contracts are useful. But the following are still missing or underdeveloped:

- acquisition-source cascade authority
- triage/scoring authority
- AE result-ingestion authority
- facet classification authority
- inbox watcher authority
- schema/migration authority
- disaster recovery authority
- refactor transition authority

That does not mean AF is contractless. It means AF now has a first ring of contracts, not a complete constitution.

## Positive Findings

The audit is not merely hostile.

### A. AF is a real pipeline, not a bag of tricks.

The major modules do fit an intelligible progression:

- ingestion
- triage
- search / expansion
- AE handoff
- AE output ingestion
- knowledge surfaces
- UI / CLI
- health / quarantine

That coherence is real.

### B. The recent integrity and quarantine work is genuine.

The repaired AF integrity surface now passes:

- missing `pdf_path` targets: `0`
- duplicate `pdf_sha256` rows: `0`
- orphan PDFs in `data/pdfs/`: `0`
- missing AE output paths: `0`

And quarantine now has a real manifest and weekly health machinery.

### C. The repo is in much better operational shape than AE.

AF git state during audit:

- modified tracked files: `0`
- untracked files: `1`

So unlike AE, AF is not currently suffering from a vast mixed-worktree problem.

### D. The test suite is healthy.

- `43 passed, 1 skipped`

That matters. It does not settle the architecture, but it lowers the probability of immediate accidental breakage.

## Refactor Hazards

If one begins a major refactor now, these are the most likely failure classes.

1. Breaking the wrong AE handoff stack.
- Because both old and v2 surfaces exist.

2. Preserving the wrong vocabulary.
- Because `pending` and `needs_review` are real live values though under-contracted.

3. Trusting green health when semantic drift remains.
- Because the health monitor is path-deep, not yet state-deep.

4. Splitting `core/database.py` without first defining repository boundaries.
- Because it currently mixes schema, state transitions, facet scoring, claim/rule import, and stats.

5. Splitting `cli/main.py` without preserving command-family grouping.
- Because it is a dispatcher monolith but also the de facto operational surface.

6. Refactoring the knowledge layer as though it were hot.
- When much of it is provisioned but not live.

7. Tightening schema constraints without first reconciling live vocabulary.
- Because the current live DB would violate a more honest set of CHECK constraints.

## What Should Be Done Before A Major Refactor

In order:

1. Write and enforce a **triage/scoring authority contract** that names the real live vocabulary, including deferred-scoring paths.
2. Expand the health monitor so it checks:
  - `triage_decision` vocabulary
  - `status` vocabulary
  - `ae_status` without output bundle
  - `pdf_sha256` vs actual bytes
3. Choose one AE handoff stack as canonical:
  - either old or v2
  - and explicitly demote the other
4. Write an **AE result-ingestion authority contract**.
5. Add a **schema/migration authority contract** and move AF away from silent schema accretion.
6. Only then split:
  - `core/database.py`
  - `cli/main.py`

## Recommended Refactor Order

1. Contract and state-vocabulary tightening  
2. Health-monitor widening  
3. AE handoff-stack unification  
4. Database seam extraction  
5. CLI command-module extraction  
6. Search/bibliographer decomposition  
7. Knowledge-layer activation or honest demotion  

## Final Judgment

AF is good enough to continue operating. It is not yet good enough for an ambitious refactor without preparatory repair.

Its current risk is not chaos. It is **transitional ambiguity**.

That is a much better problem to have. But it is still a problem.
