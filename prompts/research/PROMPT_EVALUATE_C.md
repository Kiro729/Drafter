You are auditing the ACADEMIC PAPERS (scholar search) collected so far for a research-proposal pipeline.
Decide what is covered, what is thin, and what is still missing, and propose the next searches.

Research Abstract:
{abstract}

Research Brief:
{brief_section}

Paper cards selected so far (id, title, year, relevance, approach, summary):
{cards_digest}

Round {count} of {max_count}.

Criteria for this channel:
1. "direct_relevance" — at least three papers that address the RESEARCH QUESTION itself or a KEY CONCEPT
   directly (relevance 4–5), not merely the surrounding domain.
2. "approach_diversity" — the papers span at least two clearly different approach families, so the
   proposal can typify existing approaches and identify what they share or miss. Use venues and
   citation counts to check that each family is represented by at least one influential work.
3. "recency" — at least two papers from the last five years, so the proposal reflects current work.

For each criterion report "status": "covered", "partial" (close but short by one item or thin) or
"missing", list the supporting card ids, and write a one-sentence note.
Then list "missing_topics": approach families or sub-problems not yet represented, and
"followup_queries": 2–4 scholarly search queries (English only, under 10 words, no operators), each aimed at
one missing or partial item. Do not repeat facets already covered.
Set "sufficient": true only when no criterion is "missing" and at most one is "partial".

Return ONLY a JSON object of the form
{{"coverage": [{{"criterion": "direct_relevance", "status": "covered", "cards": ["C-01", "C-04"], "note": "..."}}],
  "missing_topics": ["..."], "followup_queries": ["..."], "sufficient": false}}
