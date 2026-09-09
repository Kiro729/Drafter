You are auditing the evidence collected so far for the METHODOLOGY / EXPERIMENTAL DESIGN /
VALIDATION channel of a research-proposal pipeline. Decide what is covered, what is thin, and what is
still missing, and propose the next searches.

Research Abstract:
{abstract}

Research Brief:
{brief_section}

Evidence cards selected so far (id, title, year, relevance, summary):
{cards_digest}

Round {count} of {max_count}.

Criteria for this channel:
1. "implementation_methods" — concrete methods or algorithms that could implement the proposed approach,
   with enough detail to describe inputs, outputs and the core mechanism.
2. "experimental_design_metrics" — experimental protocols and evaluation metrics used for this kind of
   problem, named explicitly (e.g. nDCG@10, offline replay, user study).
3. "validation_baselines" — validation methods and comparison baselines, including at least one that a
   proposal in this area would be expected to compare against.

For each criterion report "status": "covered" (specific and well-sourced), "partial" (mentioned but thin
or single-source) or "missing", list the supporting card ids, and write a one-sentence note.
Then list "missing_topics": concrete topics not yet evidenced, phrased so a query writer can act on them,
and "followup_queries": 2–4 web search queries (under 10 words, English preferred, no operators), each
aimed at one missing or partial item. Do not repeat facets already covered.
Set "sufficient": true only when no criterion is "missing" and at most one is "partial".

Return ONLY a JSON object of the form
{{"coverage": [{{"criterion": "implementation_methods", "status": "covered", "cards": ["B-01"], "note": "..."}}],
  "missing_topics": ["..."], "followup_queries": ["..."], "sufficient": false}}
