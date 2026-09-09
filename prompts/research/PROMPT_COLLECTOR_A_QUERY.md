Generate {n_queries} web search queries for collecting RESEARCH BACKGROUND evidence: the context and
motivation for this research, concrete limitations or unsolved problems of existing approaches, and
relevant prior-work families or technology trends.

Research Brief (hard scope — every query must stay inside IN SCOPE, must never target an OUT OF SCOPE
item, and should prefer the KEY CONCEPTS vocabulary):
{brief_section}

Supervisor instructions for this collector:
{collector_prompt}

Research Abstract:
{abstract}
{gap_section}
Queries already used in earlier rounds (do not repeat or lightly paraphrase them):
{used_queries}

[Query rules]
- Each query targets ONE distinct facet (context / limitation / trend). Do not paraphrase the same facet.
- Concise natural language, under 10 words, no AND/OR operators, no quotation marks.
- English retrieves more technical sources; use Korean only when the topic is Korea-specific.
- Prefer sources that state specifics (numbers, named methods, named limitations) over overviews.

Return only the queries, one per line. No numbering or explanation.
