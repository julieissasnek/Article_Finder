# Ports Contract

The reserved ports for this module are defined in `ports.json`.
Update `ports.json` to change ports and keep scripts aligned.
## AF Contracts

The AF repo now treats contracts as executable governance, not mere prose.

Primary current contracts:

- `AF_PIPELINE_AUTHORITY_2026-05-10.md`
- `AF_PDF_ATTACHMENT_INTEGRITY_AUTHORITY_2026-05-10.md`
- `AF_AE_HANDOFF_AUTHORITY_2026-05-10.md`
- `AF_AE_RESULT_INGESTION_AUTHORITY_2026-05-10.md`
- `AF_TRIAGE_AND_SCORING_AUTHORITY_2026-05-10.md`
- `AF_SCHEMA_AND_MIGRATION_AUTHORITY_2026-05-10.md`
- `AF_SHARED_INTAKE_CLASSIFICATION_AUTHORITY_2026-05-10.md`
- `AF_SHARED_INTAKE_CLASSIFICATION_SUCCESS_CONDITIONS_2026-05-10.json`
- `AF_AE_CORPUS_DEDUPE_AUTHORITY_2026-05-10.md`
- `AF_AE_CORPUS_DEDUPE_SUCCESS_CONDITIONS_2026-05-10.json`
- `AF_SYSTEM_HEALTH_AUTHORITY_2026-05-10.md`
- `AF_SYSTEM_HEALTH_SUCCESS_CONDITIONS_2026-05-10.json`
- `AF_QUARANTINE_AND_RECOVERY_AUTHORITY_2026-05-10.md`
- `AF_WEEKLY_SYSTEM_HEALTH_AUTHORITY_2026-05-10.md`
- `AF_WEEKLY_SYSTEM_HEALTH_SUCCESS_CONDITIONS_2026-05-10.json`

Operational executables:

- `eater_interface/handoff_contract.py`
- `scripts/repair_af_schema_governance.py`
- `scripts/verify_af_schema_governance.py`
- `scripts/verify_af_integrity.py`
- `scripts/verify_af_semantic_integrity.py`
- `scripts/run_atlas_shared_backlog_classifier.py`
- `scripts/verify_af_shared_intake_classification.py`
- `scripts/run_af_ae_corpus_dedupe.py`
- `scripts/verify_af_ae_corpus_dedupe.py`
- `scripts/repair_af_semantic_state.py`
- `scripts/repair_af_integrity.py`
- `scripts/run_system_health.py`
- `scripts/run_weekly_system_health.py`
- `scripts/build_quarantine_manifest.py`
- `scripts/verify_af_quarantine.py`
- `cli/main.py doctor --deep`
