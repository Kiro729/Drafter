You are auditing the evidence collected so far for the RESEARCH BACKGROUND channel of a
research-proposal pipeline. Decide what is covered, what is thin, and what is still missing, and
propose the next searches.

Research Abstract:
{abstract}

Research Brief:
{brief_section}

Evidence cards selected so far (id, title, year, relevance, summary):
{cards_digest}

Round {count} of {max_count}.

Criteria for this channel:
1. "background_context" — the domain's current state and recent changes that motivate this research.
2. "existing_limitations" — concrete limitations or unsolved problems of existing approaches, stated
   specifically (not "further research is needed").
3. "prior_work_trends" — relevant prior-work families or technology trends, evidenced by at least two
   distinct sources.

For each criterion report "status": "covered" (specific and well-sourced), "partial" (mentioned but thin
or single-source) or "missing", list the supporting card ids, and write a one-sentence note.
Then list "missing_topics": concrete topics not yet evidenced, phrased so a query writer can act on them,
and "followup_queries": 2–4 web search queries (under 10 words, English preferred, no operators), each
aimed at one missing or partial item. Do not repeat facets already covered.
Set "sufficient": true only when no criterion is "missing" and at most one is "partial".

Return ONLY a JSON object of the form
{{"coverage": [{{"criterion": "background_context", "status": "covered", "cards": ["A-01"], "note": "..."}}],
  "missing_topics": ["..."], "followup_queries": ["..."], "sufficient": false}}
