# Scheduled digest agent

Every Monday I want a short, trustworthy digest of what happened in marketing measurement: incrementality, MMM, clean rooms, retail media. Reading a dozen feeds myself is the kind of job I'd happily hand off, but I would not hand it to one model with no checks. So I built it as a small team, the way a newsroom works.

A **researcher** reads the week's articles and picks the ones that matter. A **writer** turns the picks into a two-minute digest. A **reviewer** checks the draft before it goes anywhere. It runs on a schedule with nobody watching, so the part I spent the most time on is what stops it from doing something dumb: cost caps, and a final check in plain code that does not depend on any model's say-so.

It is built with CrewAI. The articles in the demo are invented, so there is no real company data in this repo.

## How a run works

```
feeds  ->  collect  ->  researcher  ->  writer  ->  reviewer  ->  my checks  ->  digest
           (code)       picks 5         drafts      approves or    (code)         published,
                                                    sends back                    or a saved draft
```

- **Collect (plain Python).** Fetch the feeds, drop duplicates and old items, cap the number. Fetching has a right answer, so no model is involved.
- **Researcher.** Two tools: `list_items` and `read_item`. It returns structured picks, each with an id and one sentence on why it matters.
- **Writer.** Writes from the picks only and cites each bullet by article id, like `[i3]`, never by web address. If a note is missing a detail, it can ask the researcher one question (CrewAI's built-in delegation).
- **Reviewer.** Runs a `check_draft` tool, compares each bullet to the notes, and returns a verdict as data: approved or not, plus the specific issues.
- **My checks.** Code re-checks the draft however the reviewer voted. If it fails, the writer gets one revision. If it still fails, nothing is published and the draft is saved for me to read.

Links only get into the digest one way: the id is looked up in the list of articles that were really collected. A model cannot invent a link, and it cannot pass one along from inside an article.



## Files

| File | What it does |
|---|---|
| `src/digest/run.py` | One run, start to finish: caps, collect, crew, my checks, one revision, files |
| `src/digest/crew.py` | The three agents and the tasks, in the standard CrewAI layout |
| `src/digest/config/` | `agents.yaml` and `tasks.yaml`: roles, goals and task wording |
| `src/digest/sources.py` | Fetch and parse feeds, drop duplicates and old items |
| `src/digest/tools.py` | The researcher's two tools and the reviewer's check tool |
| `src/digest/verify.py` | The checks that are code, and how `[i3]` becomes a link |
| `src/digest/budget.py` | The cost caps |
| `src/digest/llms.py`, `scripted.py` | Which model each role uses, and the offline stand-in |
| `src/digest/main.py`, `app.py` | The command line and the demo page |
| `config/sources.yaml` | The feeds |
| `samples/articles.json` | The invented demo articles, including a duplicate, an old one and an injection attempt |
| `.github/workflows/` | The weekly schedule and the tests |
| `tests/` | Offline tests |
