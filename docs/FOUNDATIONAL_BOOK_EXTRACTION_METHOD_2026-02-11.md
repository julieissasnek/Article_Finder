# Method: Extracting Rule-Ready Content from Foundational Books

**Date**: 2026-02-11
**Status**: DRAFT - Developed from Mehrabian & Russell case study
**Purpose**: Systematic extraction of secondary material for books without PDFs

---

## Problem

Many foundational CNfA books lack PDFs (copyright, out of print). We need comprehensive secondary material sufficient for rule extraction.

Current approach was too shallow:
- 50-150 word summaries
- No theoretical propositions
- No measurement details
- No testable claims

---

## Target Output Structure

For each foundational book, collect:

### 1. Core Abstract (200-400 words)
- Main thesis/argument
- Key constructs introduced
- Framework/model name
- Primary contribution to field
- Stored in: `papers.abstract`

### 2. Extended Notes (2000-10000 chars)
Structured sections for rule extraction:

```
## [AUTHOR YEAR] - EXTENDED SECONDARY MATERIAL

### CORE THEORETICAL FRAMEWORK
- Central model/theory name
- Key relationships proposed
- Causal mechanisms

### KEY CONSTRUCTS
- Definition of each major construct
- How measured/operationalized
- Relationships to other constructs

### THEORETICAL PROPOSITIONS
- P1: [If X then Y]
- P2: [A relates to B via C]
- Numbered, extractable claims

### MEASUREMENT INSTRUMENTS
- Scale names and items
- Validation evidence
- How to apply

### DESIGN IMPLICATIONS
- What environments should have
- What to avoid
- Specific recommendations

### EMPIRICAL FINDINGS (if applicable)
- Key study results cited
- Effect sizes if available
- Boundary conditions

### RELATED PUBLICATIONS
- Follow-on papers by same authors
- Key applications by others

### SOURCE METADATA
- Sources consulted
- Retrieval date
- Confidence level
```

Stored in: `papers.extended_notes`

---

## Search Strategy

For each book, conduct searches in this order:

### Pass 1: Overview Sources
- Wikipedia article on the theory/book
- Google Books preview
- Publisher description (MIT Press, etc.)
- APA PsycInfo record

### Pass 2: Academic Reviews
- "[Author] [Year] book review" in Google Scholar
- ResearchGate/Academia.edu summaries
- Semantic Scholar overview

### Pass 3: Theory Explanations
- "[Theory name] explained"
- "[Theory name] framework propositions"
- "[Author] [construct name] definition"

### Pass 4: Measurement Details
- "[Scale name] items"
- "[Author] measurement instrument"
- "[Theory] operationalization"

### Pass 5: Applications
- "[Theory] applied to [domain]"
- "[Theory] architecture/design"
- "[Theory] empirical test"

---

## Quality Criteria

### Minimum for Rule Extraction
- [ ] At least 3 named constructs defined
- [ ] At least 2 causal/correlational propositions
- [ ] Clear IV → DV relationships identifiable
- [ ] Sufficient for generating CNfA rules

### Ideal Coverage
- [ ] Complete theoretical model described
- [ ] Measurement approach documented
- [ ] Design implications explicit
- [ ] Boundary conditions noted
- [ ] Multiple corroborating sources

---

## Priority Books for This Treatment

### Tier 1 - Foundational Theories (do first)
| Book | Year | Theory/Contribution |
|------|------|---------------------|
| Mehrabian & Russell | 1974 | PAD model, S-O-R framework | ✓ DONE |
| Kaplan & Kaplan | 1989 | Attention Restoration Theory |
| Ulrich | 1983 | Stress Recovery Theory |
| Altman | 1975 | Privacy regulation, territoriality |
| Berlyne | 1971 | Arousal theory, collative variables |

### Tier 2 - Domain Foundations
| Book | Year | Domain |
|------|------|--------|
| Heschong | 1979 | Thermal comfort/delight |
| Gehl | 1987/2010 | Public space, social life |
| Pallasmaa | 2005 | Multisensory architecture |
| Alexander | 1977 | Pattern language |
| Rapoport | 1990 | Environmental meaning |

### Tier 3 - Specialized Domains
| Book | Year | Domain |
|------|------|--------|
| Passini | 1984/1992 | Wayfinding |
| Kellert | 2005 | Biophilic design |
| Beranek | 2004 | Architectural acoustics |
| Birren | 1983 | Color psychology |
| Hall | 1966 | Proxemics |

---

## Implementation

### Per-Book Workflow
1. Create todo item for book
2. Run 5 search passes
3. Fetch key sources (WebFetch where possible)
4. Compile structured extended_notes
5. Write core abstract
6. Update database
7. Mark complete

### Estimated Time
- 15-30 minutes per book for thorough treatment
- ~15 Tier 1 books = 4-8 hours
- Can parallelize searches

### Storage
- `papers.abstract`: Core summary
- `papers.extended_notes`: Detailed extraction
- Future: Could add `papers.rule_candidates` for pre-extracted propositions

---

## Post-Processing for Rules

Extended notes structured to enable:
1. Regex extraction of "P1:", "P2:" propositions
2. Construct identification from ### sections
3. IV/DV parsing from theoretical framework
4. Confidence assignment from source metadata

---

## Revision History

| Date | Change |
|------|--------|
| 2026-02-11 | Initial method developed from M&R case study |
