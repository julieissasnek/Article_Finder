# Repo Agent Contract

Article Finder is allowed to orchestrate PDF discovery, metadata acquisition,
Zotero lookup, and local persistence. It must not invent a separate first-pass
topic classifier when shared Atlas contracts already exist.

## Shared Classification Source

Before changing intake, triage, article type, relevance, or topic routing code,
inspect:

- `/Users/davidusa/REPOS/atlas_shared/AGENTS.md`
- `/Users/davidusa/REPOS/atlas_shared/contracts/PRE_EXTRACTION_INTAKE_CONTRACT_2026-04-17.md`
- `/Users/davidusa/REPOS/atlas_shared/contracts/PANEL_TOPIC_EVIDENCE_CONTRACT_2026-04-17.md`

Prefer imports from `atlas_shared`:

- `atlas_shared.intake.PreExtractionIntakeGate`
- `atlas_shared.topic_bank.load_topic_constitution_bank`
- `atlas_shared.relevance.QuestionArticleRelevanceFilter`
- `atlas_shared.bundle_router.QuestionBundleRouter`

## First PDF Gate

The first decision is pre-extraction. Use only arrival metadata, title,
abstract, tags, keywords, DOI/source metadata, and first-page text if available.
Do not use Article Eater V7 extraction outputs at this stage.

Reject only clear false positives. Preserve credible adjacent or novel cases as
`edge_case`, `manual_review`, `topic_expansion_candidate`, or
`new_topic_candidate`.

## Panel Evidence

The student-facing questions are topic constitutions. Their panel dossiers and
curated JSON in `atlas_shared` are evidence for Article Finder routing, not just
Google Scholar prompts.
