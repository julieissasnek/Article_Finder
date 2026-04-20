# AF Question Filter with AG

AF can now use the shared question filter at intake without relying on a network API client.

## Principle

- AF performs the first-pass deterministic triage.
- The shared question filter checks question constitutions.
- AG may adjudicate only the borderline cases.

## Relevant Files

- [question_relevance.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/triage/question_relevance.py)
- [pipeline.py](/Users/davidusa/REPOS/Article_Finder_v3_2_3/eater_interface/pipeline.py)
- [question_constitutions_starter.json](/Users/davidusa/REPOS/atlas_shared/src/atlas_shared/data/question_constitutions_starter.json)

## Pipeline YAML Example

```yaml
question_filter_enabled: true
question_constitutions_path: /Users/davidusa/REPOS/atlas_shared/src/atlas_shared/data/question_constitutions_starter.json
question_constitution_ids:
  - SQ-ART-001
question_adjudication_policy: borderline_only
question_adjudicator_kind: ag
question_adjudicator_command:
  - /path/to/ag_wrapper
  - question-relevance
question_adjudicator_timeout: 180
```

## Meaning

- `question_filter_enabled`: turn the gate on
- `question_constitutions_path`: bank of machine-readable constitutions
- `question_constitution_ids`: optional subset to apply
- `question_adjudication_policy`: `never`, `borderline_only`, or `always`
- `question_adjudicator_kind`: `none`, `ag`, `codex`, or `claude`
- `question_adjudicator_command`: only needed for `ag`

## Conservative Behaviour

The question gate is intentionally not a full replacement for the taxonomy triage.

It acts as a second opinion and can:

- promote a reject to `review`
- promote a reject or review to `send_to_eater`

It also records novelty fields for edge cases, including:

- `edge_case_kind`
- `novelty_signal`
- `topic_expansion_candidate`
- `new_topic_candidate`
- `proposed_topic_label`

It should not silently erase the broader AF triage logic.
