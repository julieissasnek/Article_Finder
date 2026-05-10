# AF System Health Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract defines the deeper AF health monitor. It is stricter than the
older `doctor` command, which mainly checked configuration and paths.

## Canonical Entrypoints

- `cli/main.py doctor`
- `cli/main.py doctor --deep`
- `scripts/validate_codebase.py`
- `scripts/verify_af_schema_governance.py`
- `scripts/verify_af_integrity.py`
- `scripts/verify_af_quarantine.py`
- `scripts/verify_af_semantic_integrity.py`
- `scripts/verify_af_shared_intake_classification.py`
- `scripts/verify_af_ae_corpus_dedupe.py`

## Required Deep Checks

- configuration and ports
- import sanity
- database initialization
- PDF cataloger sanity
- claim verifier sanity
- schema migration governance
- PDF attachment integrity
- AE handoff path integrity
- AF semantic-state integrity
- shared intake-classification persistence integrity
- AE corpus-overlap dedupe materialization integrity
- quarantine manifest integrity

## Required Outputs

The deep verifier must emit machine-readable JSON and fail nonzero when any
hard integrity condition is violated.
