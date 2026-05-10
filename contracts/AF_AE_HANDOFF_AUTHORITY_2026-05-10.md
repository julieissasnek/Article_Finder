# AF → AE Handoff Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs the AF surfaces that prepare or remember handoff to
Article Eater.

## Canonical Fields

In `papers`:

- `triage_decision`
- `ae_job_path`
- `ae_output_path`
- `ae_run_id`
- `ae_profile`
- `ae_status`
- `ae_n_claims`
- `ae_n_rules`
- `ae_confidence`

## Rules

1. `triage_decision='send_to_eater'` is the canonical AF admission to AE
   queueing.
2. If `ae_job_path` is non-empty, it must resolve to a job bundle directory.
3. `ae_status='pending'` is truthful only when a job path exists. It does not
   by itself imply an output bundle exists yet.
4. If `ae_output_path` is non-empty, it must resolve to an AE output bundle.
5. If an output bundle exists and carries a parseable `result.json`, the row's
   `ae_status` must agree with that result.
6. If an output path is lost or superseded, the stale path must be rewritten
   to a valid current path or cleared honestly.
7. AF must not keep a misleading AE output reference on a row that no longer
   has a truthful PDF attachment.

## Canonical Executables

- `eater_interface/handoff_contract.py`
- `scripts/verify_af_integrity.py`
- `scripts/repair_af_integrity.py`
- `cli/main.py doctor --deep`
- `scripts/verify_af_semantic_integrity.py`
- `scripts/repair_af_semantic_state.py`
