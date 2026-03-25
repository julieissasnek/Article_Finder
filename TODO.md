
## AI Claim Verification (Priority: High)

**File:** `triage/claim_verifier.py`

**Current state:** Basic keyword-based verification that checks:
- Title-abstract consistency
- Claims relevance to paper topic
- Rule structure validity

**TODO:** Implement `AIClaimVerifier` class that uses LLM for:

1. **Semantic title-abstract matching**
   - Prompt: "Does this abstract match the paper title '{title}'?"
   - Catches cases where keywords differ but topic is same (or vice versa)

2. **Claim validity checking**
   - Prompt: "Is this claim supported by the abstract? Claim: {claim}"
   - Detects hallucinated or unsupported claims

3. **Rule logic verification**
   - Prompt: "Is this causal rule logically valid? {lhs} → {rhs} ({polarity})"
   - Catches nonsensical cause-effect relationships

4. **Cross-paper consistency**
   - Check if similar claims from different papers contradict each other

**Implementation notes:**
- Use Claude API (Haiku for cost efficiency)
- Batch requests to minimize API calls
- Cache results to avoid re-verification
- Run asynchronously after AE processing

## Corpus Expansion (Priority: Medium)

- [ ] Collate 30-50 high-quality CNfA questions to run in Elicit and other RAG tools to deepen the PDF collection.
