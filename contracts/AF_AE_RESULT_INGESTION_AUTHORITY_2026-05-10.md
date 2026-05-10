# AF AE Result Ingestion Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs the AF side of AE job and result state. Its purpose is
to prevent flattering but misleading AE progress claims.

## Canonical Fields

In `papers`:

- `ae_job_path`
- `ae_output_path`
- `ae_run_id`
- `ae_status`
- `ae_n_claims`
- `ae_n_rules`
- `ae_confidence`

## Canonical AE Status Vocabulary

- `pending`
- `SUCCESS`
- `PARTIAL_SUCCESS`
- `FAIL`

## State Rules

1. `ae_status='pending'` requires a non-empty `ae_job_path`.
2. `ae_status='pending'` does **not** require an output path yet.
3. `ae_status IN ('SUCCESS','PARTIAL_SUCCESS','FAIL')` requires:
   - a non-empty `ae_output_path`,
   - and a parseable `result.json` under that output bundle.
4. If an output bundle exists and its `result.json` disagrees with the row's
   `ae_status`, the row is stale and must be repaired.
5. If a row carries a terminal AE status but no truthful output bundle, the
   row is stale and must be downgraded honestly.

## Canonical Executables

- `eater_interface/output_parser.py`
- `scripts/verify_af_semantic_integrity.py`
- `scripts/repair_af_semantic_state.py`

## Last Mile Requirement

AF health is not green merely because paths exist. The AE result state must
also agree with the actual output bundle semantics.
