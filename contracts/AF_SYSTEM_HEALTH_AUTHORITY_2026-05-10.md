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
- `scripts/verify_af_integrity.py`
- `scripts/verify_af_quarantine.py`

## Required Deep Checks

- configuration and ports
- import sanity
- database initialization
- PDF cataloger sanity
- claim verifier sanity
- PDF attachment integrity
- AE handoff path integrity
- quarantine manifest integrity

## Required Outputs

The deep verifier must emit machine-readable JSON and fail nonzero when any
hard integrity condition is violated.
