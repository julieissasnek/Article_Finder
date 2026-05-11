# AF Pipeline Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract states the canonical AF pipeline as it presently exists.

## Canonical Stages

1. ingestion / acquisition
   - `ingest/`
   - includes immediate AE-corpus dedupe materialization through
     `core/database.py`
2. metadata enrichment and PDF attachment
   - `ingest/`
3. triage and topical relevance
   - `triage/`
4. corpus expansion and search
   - `search/`
5. AF → AE handoff
   - `eater_interface/`
6. AE output parsing and storage
   - `eater_interface/`
   - `knowledge/`
7. UI and operator control
   - `ui/`
   - `cli/`
8. quarantine and health governance
   - `scripts/build_quarantine_manifest.py`
   - `scripts/verify_af_quarantine.py`
   - `scripts/run_weekly_system_health.py`

## Architectural Rule

AF is not merely a bag of tools. It is a feeder pipeline. The modules may be
separate, but the overall state progression should remain coherent:

- candidate enters
- metadata and attachment become truthful
- triage decides
- AE handoff occurs when warranted
- returned outputs are materialized honestly

## Present Structural Weaknesses

- `cli/main.py` is too large and acts as a dispatcher monolith
- `core/database.py` is also too large and contains schema, state logic, and
  general operations in one place
- health checking existed but was shallower than the live system required
- quarantine handling existed operationally before it was constitutionally
  governed

These weaknesses do not negate the pipeline, but they do justify future
refactoring.
