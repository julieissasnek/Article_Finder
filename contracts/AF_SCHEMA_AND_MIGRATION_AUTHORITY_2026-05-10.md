# AF Schema And Migration Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs AF schema change discipline during the present
transitional period.

## Present Reality

AF currently uses a hybrid scheme:

- monolithic schema definition in `core/database.py`
- `schema_version` rows for named revisions
- `_ensure_columns(...)` for additive backward-compatible column repair

This is weaker than a full migration stack, but it is the live reality and
must be governed honestly.

## Canonical Rule

Any schema-affecting change must update all three of:

1. the canonical schema emitted by `get_schema_sql()` in `core/database.py`
2. the `schema_version` ledger when the change is more than a trivial additive
   compatibility shim
3. tests or health checks that would reveal drift in the affected surface

## Transitional Restriction

`_ensure_columns(...)` may be used only for additive backward-compatible
repairs. It is not a substitute for deliberate schema-version discipline.

## Canonical Executables

- `core/database.py`
- `scripts/validate_codebase.py`
- `scripts/run_system_health.py`

## Last Mile Requirement

Schema change is not complete merely because the DB opens. The health and test
surfaces that rely on the changed fields must still pass.
