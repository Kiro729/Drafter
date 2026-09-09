Generate {n_queries} scholarly search queries to retrieve academic papers directly related to the research
question: prior approaches to the same problem, their methods and results, and recent work.

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

[Search engine note]
{backend_note}

[Query Guidelines]
- English academic terminology only. No non-English keywords.
- Include key model / technique / task names so the engine can match them,
  e.g. "serendipity recommendation user modeling", "task oriented dialogue large language model".
- Under 10 words, no AND/OR operators, no quotation marks, no field prefixes.
- Each query targets a different approach family or sub-problem so the results are diverse.
- Prefer specific academic terms over generic words (avoid "study", "analysis", "approach" alone).

Return only the queries, one per line. No numbering or explanation.
