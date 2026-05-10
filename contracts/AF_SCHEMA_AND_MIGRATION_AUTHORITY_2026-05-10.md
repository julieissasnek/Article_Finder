# AF Schema And Migration Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs AF schema change discipline during the present
transitional period.

## Present Reality

AF currently uses a transitional but explicit scheme:

- monolithic base schema definition in `core/database.py`
- named additive migrations in `core/schema_registry.py`
- `schema_version` rows as the applied ledger

This is still weaker than a large dedicated migration framework, but it is no
longer an informal `_ensure_columns(...)` habit.

## Canonical Rule

Any schema-affecting change must update all three of:

1. the canonical base schema emitted by `get_schema_sql()` in `core/database.py`
2. the migration registry in `core/schema_registry.py`
3. the `schema_version` ledger
4. tests or health checks that would reveal drift in the affected surface

## Transitional Restriction

Schema change may not be smuggled in through ad hoc `ALTER TABLE` calls in
feature code. Additive repairs belong in the migration registry, and the
health monitor must be able to see that they were applied.

## Canonical Executables

- `core/database.py`
- `core/schema_registry.py`
- `scripts/repair_af_schema_governance.py`
- `scripts/verify_af_schema_governance.py`
- `scripts/validate_codebase.py`
- `scripts/run_system_health.py`

## Last Mile Requirement

Schema change is not complete merely because the DB opens. The health and test
surfaces that rely on the changed fields must still pass.
