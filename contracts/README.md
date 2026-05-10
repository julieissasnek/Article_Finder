# Ports Contract

The reserved ports for this module are defined in `ports.json`.
Update `ports.json` to change ports and keep scripts aligned.
## AF Contracts

The AF repo now treats contracts as executable governance, not mere prose.

Primary current contracts:

- `AF_PIPELINE_AUTHORITY_2026-05-10.md`
- `AF_PDF_ATTACHMENT_INTEGRITY_AUTHORITY_2026-05-10.md`
- `AF_AE_HANDOFF_AUTHORITY_2026-05-10.md`
- `AF_SYSTEM_HEALTH_AUTHORITY_2026-05-10.md`
- `AF_SYSTEM_HEALTH_SUCCESS_CONDITIONS_2026-05-10.json`

Operational executables:

- `scripts/verify_af_integrity.py`
- `scripts/repair_af_integrity.py`
- `scripts/run_system_health.py`
- `cli/main.py doctor --deep`
