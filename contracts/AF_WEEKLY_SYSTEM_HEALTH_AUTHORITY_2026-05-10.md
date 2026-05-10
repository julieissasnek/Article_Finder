# AF Weekly System Health Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs the deeper weekly AF health pass. It exists because the
repo needs more than one-off manual repair; it needs a recurring integrity and
archive check.

## Canonical Entrypoints

- `scripts/run_weekly_system_health.py`
- `scripts/run_system_health.py`
- `scripts/archive_system_health_report.py`
- `ops/launchd/com.articlefinder.weekly_system_health.plist`

## Required Checks

- deep doctor
- validate codebase
- schema governance verifier
- semantic integrity verifier
- shared intake-classification verifier
- AE corpus dedupe verifier
- AF integrity verifier
- quarantine verifier

## Required Archival Behavior

- each weekly run must archive a timestamped JSON payload under
  `data/health_reports/`
- the latest payload must also be materialized as `data/health_reports/latest.json`
