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

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src

python -m digest.main --demo       # offline demo on invented articles, no key needed
python -m digest.app               # the demo page, at http://localhost:7860
ANTHROPIC_API_KEY=... python -m digest.main     # the real thing: live feeds, Claude
```

A real run refuses to start without a key. I would rather it stop than publish a digest written by the offline stand-in.

**Schedule.** `.github/workflows/digest.yml` runs it every Monday at 12:00 UTC (7 or 8 a.m. in New York) and commits the digest and a run record. Add `ANTHROPIC_API_KEY` as a repository secret. You can also start it by hand from the Actions tab.

## Cost caps

A scheduled job needs limits that do not depend on anyone noticing.

| Cap | What it does |
|---|---|
| Monthly | Adds up the cost of this month's run records. Over `MONTHLY_CAP_USD` (default $5), the run does not start |
| Per run | Once a run has spent `MAX_RUN_USD` (default $0.50), every further model call is blocked |
| Per agent | Each agent gets a fixed number of steps, so a loop of tool calls cannot go on forever |
| Per input | At most 30 articles, each trimmed, so the prompt size is bounded before a model sees it |
| Model routing | Researcher and reviewer run on the small model. Only the writer uses the larger one |

I first tried to enforce the per-run cap by raising an error from CrewAI's step callback. CrewAI's event bus caught the error and the run kept spending. Blocking the model call itself is what works, and it is the version in the code.

Every run writes `runs/DATE.json` with the status, tokens, cost, issues, which feeds failed, and how many tool calls were made. When a run stops, the record says why.

## Try it

The demo page has a "Try a variation" box. It changes what the offline stand-in does, so you can watch the checks work:

- **Writer asks the researcher a question.** Delegation: you can see the `Ask question to coworker` call in the steps, and the answer ends up in the first bullet.
- **Writer forgets a citation.** The reviewer's tool flags it, the writer fixes it, and it publishes.
- **Writer obeys an injected link.** One of the sample articles contains hidden instructions to add a link. The link check catches it.
- **Reviewer rubber-stamps and the writer never fixes it.** The reviewer approves a bad draft. My code still refuses to publish it and saves it as a draft.

The last one is the point of the design. A model reviewing a model is a second opinion, not a guarantee.

## What this covers

Multi-agent roles, handoffs, delegation, scheduling and cost caps, plus structured outputs between agents, tool design (descriptions that say when to use the tool, and bad inputs that return a helpful message instead of crashing), and prompt-injection defence on untrusted text.


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
