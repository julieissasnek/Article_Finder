# AF Triage And Scoring Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs AF triage state as it truly exists in the live system.
It distinguishes:

- corpus lifecycle state,
- triage judgment,
- and deferred scoring.

## Canonical Fields

In `papers`:

- `status`
- `triage_score`
- `triage_decision`
- `triage_reasons`
- `topic_score`
- `topic_decision`
- `topic_stage`

## Canonical Triage Decision Vocabulary

- `pending`
- `send_to_eater`
- `review`
- `reject`

Deprecated:

- `needs_review`
  - canonical replacement: `review`

## Meaning Of `pending`

`triage_decision='pending'` means:

- the paper has been discovered and materialized as an AF candidate,
- but it has not yet completed the governed scorer pass,
- and therefore it is not yet a handoff-admitted AE candidate.

It does **not** mean:

- the paper's PDF has been downloaded,
- or that the paper is queued for AE,
- or that the paper has been rejected.

## Status Relation

At present the only canonical statuses for `triage_decision='pending'` are:

- `candidate`
- `pending_scorer`

Any other pairing is semantic drift.

## Canonical Executables

- `triage/scorer.py`
- `search/bibliographer.py`
- `scripts/verify_af_semantic_integrity.py`
- `scripts/repair_af_semantic_state.py`

## Last Mile Requirement

The semantic verifier must fail if:

- a triage decision uses a non-canonical vocabulary value,
- a deprecated value survives after repair,
- or `pending` appears on a status outside the allowed pair.
