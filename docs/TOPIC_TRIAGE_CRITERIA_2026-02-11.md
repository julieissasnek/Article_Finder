# Topic Triage Criteria for AF Database

**Date**: 2026-02-11
**Status**: REVISION NEEDED — criteria too narrow
**Database**: Article_Finder_v3_2_3/data/article_finder.db

---

## Purpose

Filter 15,036 papers to identify those relevant to CNfA (Cognitive Neuroarchitecture for Affect) research. The goal is to build an epistemic web of evidence about environment → human outcome relationships.

---

## Initial Approach (v1 - TOO NARROW)

### What Was Done

Six keyword-based passes on paper titles:
1. **Exclude Phase 1**: Biomedical/clinical terms (cancer, tumor, surgery, patients, drug, etc.)
2. **Exclude Phase 2**: Animal studies (mice, rats, fish, cattle, etc.)
3. **Exclude Phase 3**: Pure materials/chemistry (synthesis, nanoparticle, polymer, catalyst)
4. **Include Phase 1**: Direct CNfA terms (biophilic, daylight+performance, thermal comfort+cognitive, etc.)
5. **Include Phase 2**: Built environment + human outcomes (office+productivity, classroom+learning, etc.)
6. **Include Phase 3**: More environment terms (soundscape, indoor air quality, etc.)

### Results (v1)

| Status | Count | % |
|--------|-------|---|
| ON-TOPIC | 1,200 | 8.0% |
| OFF-TOPIC | 4,435 | 29.5% |
| UNCLASSIFIED | 9,362 | 62.3% |

### Problem Identified

**Criteria were too narrow.** Excluded papers about:
- Attention mechanisms (without "office" or "classroom")
- Mood and affect research (without "environment")
- Stress physiology (without "built environment")
- Cognitive load theory
- Restoration theory mechanisms
- Executive function studies

These papers are **foundational** to the CNfA epistemic web—they explain the *mechanisms* by which environmental factors affect human outcomes. Without them, we have correlations but no explanatory power.

---

## Revised Approach (v2 - MORE INCLUSIVE)

### Core Principle

Include papers that inform **any of these**:
1. **Environment → Outcome** (direct CNfA evidence)
2. **Outcome mechanisms** (how attention, mood, stress, cognition work)
3. **Theoretical frameworks** (ART, SRT, prospect-refuge, biophilia hypothesis)
4. **Moderators/mediators** (what affects the E→O relationship)

### Outcome Categories to INCLUDE

Papers about these psychological/physiological outcomes should be INCLUDED even if they don't mention built environment:

| Category | Key Terms | Rationale |
|----------|-----------|-----------|
| **Attention** | attention, focus, concentration, vigilance, distractibility, selective attention, sustained attention | Core CNfA outcome |
| **Cognitive** | working memory, executive function, cognitive load, mental fatigue, cognitive performance, decision making | Core CNfA outcome |
| **Affect** | mood, emotion, affect, stress, anxiety, relaxation, calm, wellbeing, well-being | Core CNfA outcome |
| **Restoration** | restoration, recovery, fatigue recovery, mental restoration, stress recovery | Theoretical framework |
| **Perception** | visual perception, auditory perception, spatial perception, aesthetic, preference | Mediating process |
| **Physiological** | cortisol, heart rate variability, skin conductance, EEG, autonomic | Outcome markers |
| **Social** | social behavior, collaboration, communication, crowding, privacy | CNfA outcome |

### Environment Categories to INCLUDE

Papers about these environmental factors should be INCLUDED:

| Category | Key Terms |
|----------|-----------|
| **Visual** | lighting, daylight, color, view, window, glare, illuminance |
| **Acoustic** | noise, sound, soundscape, acoustic, auditory, speech intelligibility |
| **Thermal** | temperature, thermal, humidity, air movement, HVAC |
| **Air** | air quality, ventilation, CO2, VOC, odor, olfactory |
| **Spatial** | layout, density, enclosure, ceiling height, openness, wayfinding |
| **Biophilic** | nature, plant, green, biophilic, natural materials, water feature |
| **Settings** | office, classroom, hospital, school, workplace, home, urban |

### EXCLUDE Only If

Paper is CLEARLY about:
- Non-human subjects (animal behavior, ecology) with no human relevance
- Pure materials/chemistry (synthesis, polymers) with no building application
- Clinical treatment (drug trials, surgery outcomes, disease treatment)
- Pure engineering (protocols, algorithms) with no human factors
- Historical/art criticism with no psychological insight

### Uncertain → KEEP

If uncertain whether a paper is relevant, **KEEP IT**. Better to have some noise than miss foundational work.

---

## Implementation (v2)

### SQL Update Strategy

```sql
-- RESTORE papers about psychological mechanisms
UPDATE papers SET
  off_topic_flag = 0,
  topic_decision = 'on_topic',
  topic_stage = 'psych_mechanism_include'
WHERE off_topic_flag = 1
AND (
  -- Attention/cognitive mechanisms
  title LIKE '%attention%'
  OR title LIKE '%working memory%'
  OR title LIKE '%executive function%'
  OR title LIKE '%cognitive load%'
  OR title LIKE '%mental fatigue%'
  OR title LIKE '%concentration%'

  -- Affect/stress mechanisms
  OR title LIKE '%mood%'
  OR title LIKE '%stress%' AND title NOT LIKE '%material stress%'
  OR title LIKE '%anxiety%'
  OR title LIKE '%wellbeing%'
  OR title LIKE '%well-being%'
  OR title LIKE '%relaxation%'

  -- Restoration theory
  OR title LIKE '%restoration%'
  OR title LIKE '%restorative%'
  OR title LIKE '%recovery%' AND title LIKE '%mental%'

  -- Perception (relevant to environment)
  OR title LIKE '%visual perception%'
  OR title LIKE '%auditory perception%'
  OR title LIKE '%aesthetic%'
);
```

---

## Columns Used

| Column | Purpose |
|--------|---------|
| `off_topic_flag` | 0 = relevant, 1 = exclude |
| `topic_decision` | 'on_topic', 'off_topic', 'possibly_off_topic', 'needs_abstract' |
| `topic_stage` | Which filter pass classified it |

---

## Next Steps

1. Run v2 inclusive criteria
2. Review sample of restored papers
3. Process ON-TOPIC papers for rule extraction
4. For UNCLASSIFIED, use abstract-level review

---

## Final Results (v2)

| Status | Count | % |
|--------|-------|---|
| **ON-TOPIC** | 4,804 | 31.9% |
| **OFF-TOPIC** | 3,587 | 23.9% |
| **UNCLASSIFIED** | 6,606 | 43.9% |

### Papers Restored/Added by Category

| Stage | Count | Terms |
|-------|-------|-------|
| psych_restore_attention | 339 | attention, working memory, executive function, cognitive load |
| psych_restore_affect | 288 | mood, emotion, stress, anxiety, wellbeing |
| psych_restore_restoration | 128 | restoration, recovery (mental/cognitive) |
| psych_restore_perception | 49 | visual/auditory perception, aesthetic |
| psych_restore_physio | 25 | cortisol, HRV, skin conductance |
| psych_include_mechanisms | 2,712 | (from unclassified) all psych terms |
| psych_include_approach_avoid | 6 | approach-avoidance, behavioral approach |
| psych_include_embodied | 57 | affordance, embodied cognition, place attachment |

---

## Revision History

| Date | Version | Change |
|------|---------|--------|
| 2026-02-11 | v1 | Initial keyword filtering (too narrow) |
| 2026-02-11 | v2 | Added psychological mechanism inclusion |
| 2026-02-11 | v2.1 | Added approach-avoidance, affordance, place attachment |
