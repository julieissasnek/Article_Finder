# AF AE Corpus Dedupe Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs AF's deduplication of candidate papers against the
canonical AE corpus before PDF-acquisition effort is spent on them.

## Canonical External Surface

The canonical AE match surface is built from:

- `data/pipeline_registry_unified.db` `papers`
- `data/article_eater_lifecycle.db` `paper_metadata`
- `data/article_eater_lifecycle.db` `paper_supersessions`
- `data/papers/PDF-*/metadata.json` canonicality flags

AF must not infer corpus overlap from one of these surfaces in isolation when
the combined surface is available.

## Canonical Persistence Surface In AF

In `papers`:

- `ae_corpus_match_status`
- `ae_corpus_match_basis`
- `ae_corpus_match_paper_id`
- `ae_corpus_match_confidence`
- `ae_corpus_match_candidates_json`
- `ae_corpus_deduped_at`

## Canonical Operational Rules

1. Dedupe is not complete because an overlap was seen in memory. It is complete
   only when the AF `papers` row carries the persistence fields above.
2. The canonical statuses are:
   - `matched`
   - `unmatched`
   - `ambiguous`
3. The canonical match bases are:
   - `exact_doi`
   - `exact_title_year`
   - `exact_title`
   - `none`
4. `matched` rows must record a canonical AE `paper_id`.
5. `unmatched` rows must not record a canonical AE `paper_id`.
6. `ambiguous` rows must preserve all candidate AE `paper_id` values in
   `ae_corpus_match_candidates_json`.
7. The last mile is not complete unless the dedupe timestamp is written:
   `ae_corpus_deduped_at`.
8. The purpose of this surface is to reduce wasted retrieval effort, not to
   redefine AF triage semantics. Dedupe overlap may later affect export policy,
   but the overlap fact must be materialized first.
9. New or updated papers written through AF's canonical persistence path must
   receive dedupe materialization in the same write cycle. The batch runner is
   a reconciliation and backfill surface, not the primary ingestion path.

## Canonical Executables

- `core/database.py`
- `scripts/run_af_ae_corpus_dedupe.py`
- `scripts/verify_af_ae_corpus_dedupe.py`
- `core/schema_registry.py`

## Last Mile Requirement

The dedupe is not complete because AE overlap could be computed. It is complete
only when the overlap state has been written into AF `papers`, verified, and
made part of AF system-health checks.
