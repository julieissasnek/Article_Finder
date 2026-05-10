# AF Quarantine And Recovery Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs PDFs detached from misleading or no-longer-truthful AF
attachment claims. Quarantine is an archival and review state, not a euphemism
for deletion.

## Canonical Surface

- runtime quarantine root: `data/quarantine/integrity_orphans/`
- manifest builder: `scripts/build_quarantine_manifest.py`
- verifier: `scripts/verify_af_quarantine.py`

## Rules

1. Detached PDFs must move into a timestamped quarantine batch.
2. Every quarantine batch must carry a `manifest.json`.
3. Quarantined PDFs must be reviewable for re-ingest, archival retention, or
   explicit disposal.
4. Weekly AF system health must verify that the latest batch, if any, has a
   manifest.

## Last Mile Requirement

The quarantine action is not complete merely because files moved. A manifest
and a retained batch directory must exist on disk.
