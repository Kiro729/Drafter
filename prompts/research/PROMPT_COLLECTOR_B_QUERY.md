Generate {n_queries} web search queries for collecting METHODOLOGY, EXPERIMENTAL DESIGN and
VALIDATION evidence: concrete implementation methods or algorithms, experimental protocols and
evaluation metrics, and validation approaches or comparison baselines used by similar work.

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
- Each query targets ONE distinct facet (method / metric or protocol / baseline or validation).
- Concise natural language, under 10 words, no AND/OR operators, no quotation marks.
- English retrieves more technical documentation, implementation guides and benchmark pages.
- Name the dataset, metric, model family or task explicitly when the brief names it.

Return only the queries, one per line. No numbering or explanation.
