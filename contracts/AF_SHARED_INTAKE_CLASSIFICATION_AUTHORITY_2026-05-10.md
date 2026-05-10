# AF Shared Intake Classification Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs AF's use of the shared Atlas pre-extraction classifier
for backlog triage, article typing, and first-pass topic routing.

## Shared Canonical Source

AF must not invent a separate local first-pass topic classifier when the shared
Atlas intake classifier is available. The canonical shared source is:

- `atlas_shared.classifier_system.AdaptiveClassifierSubsystem`
- `atlas_shared.topic_bank.load_topic_constitution_bank`
- `atlas_shared.article_types.HeuristicArticleTypeClassifier`

## Canonical Persistence Surface

In `papers`:

- `atlas_constitution_version`
- `atlas_constitution_source`
- `atlas_article_type`
- `atlas_article_type_confidence`
- `atlas_article_type_source`
- `atlas_evidence_stage`
- `atlas_overall_confidence`
- `atlas_intake_decision`
- `atlas_routing_target`
- `atlas_domain_relevance`
- `atlas_primary_topic`
- `atlas_primary_bundle_id`
- `atlas_topic_candidates`
- `atlas_matched_question_ids`
- `atlas_edge_case_kind`
- `atlas_novelty_signal`
- `atlas_topic_expansion_candidate`
- `atlas_new_topic_candidate`
- `atlas_proposed_topic_label`
- `atlas_adjacent_topics`
- `atlas_analysis_steps_run`
- `atlas_next_action`
- `atlas_needs_more_evidence`
- `atlas_classification_payload_json`
- `atlas_classified_at`

## Canonical Operational Rules

1. The shared classifier is a pre-extraction gate, not a substitute for full AE
   extraction.
2. `triage_decision='pending'` rows may be resolved through this classifier.
3. `atlas_classified_at` is not truthful unless the shared result has been
   written into the canonical persistence fields.
4. If `atlas_domain_relevance='on_domain'`, a primary topic must be recorded.
5. JSON-bearing fields must contain parseable JSON arrays or objects, not ad
   hoc string formatting.
6. The runner must write a classification report artifact, not merely update
   the DB silently.
7. The last mile is not complete unless the coarse AF triage/topic surface is
   materialized as well:
   - `triage_decision`
   - `topic_decision`
   - `topic_stage`
   - `topic_category`
   - `status`
8. For `atlas_domain_relevance='on_domain'`, `topic_category` must agree with
   `atlas_primary_topic`.

## Canonical Executables

- `scripts/run_atlas_shared_backlog_classifier.py`
- `scripts/verify_af_shared_intake_classification.py`
- `core/schema_registry.py`

## Last Mile Requirement

The classification is not complete because the shared classifier returned a
result in memory. It is complete only when the DB fields, the triage/topic
surface, and the audit report all agree.
