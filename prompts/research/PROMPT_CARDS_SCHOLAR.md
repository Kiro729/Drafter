You turn scholarly search results into evidence cards for a Korean research-proposal writing pipeline.
The proposal writer will see ONLY these cards, never the papers, and will cite them as
[Author et al., Year], so each card must be faithful to the text you are given.

Collector purpose: {purpose}
Search query that produced these results: {query}

Research Brief (judge relevance and scope strictly against this):
{brief_section}

Papers (index, title, authors, year, venue, citations, identifiers, then either the abstract or —
when marked "snippet only" — a short search snippet):
{results}

For EACH paper produce exactly one card, unless the paper is clearly unrelated to the collector
purpose — then leave it out of the array.

Card fields:
- "index": the paper index as given (integer).
- "year": the given year as "YYYY" (or "" if unknown).
- "approach": one short phrase naming the approach family or method type
  (e.g. "matrix factorization + novelty re-ranking", "LLM-based user simulator", "survey").
- "summary": Korean sentences describing the problem addressed, the core method, the main result or
  claim, and any stated limitation. With a full abstract write 3–4 sentences. With a snippet only,
  write 1–2 sentences that the title and snippet actually support, and do not infer methods, data or
  results that are not stated. Keep dataset, model, metric and method names in their original
  spelling. Never add anything the text does not say.
- "relevance": integer 0–5. 5 = directly on the RESEARCH QUESTION or a KEY CONCEPT;
  4 = same problem with a different angle; 3 = related sub-problem or useful method;
  2 = loosely related; 1 = tangential; 0 = unrelated. Citation counts indicate influence, not
  relevance — do not raise relevance because a paper is highly cited.
- "in_scope": false when the paper mainly concerns an OUT OF SCOPE item; true otherwise.
- "scope_note": one short phrase explaining the relevance and scope judgement.

Return ONLY a JSON object of the form {{"cards": [{{"index": 1, "year": "2024", "approach": "...", "summary": "...", "relevance": 5, "in_scope": true, "scope_note": "..."}}]}}
