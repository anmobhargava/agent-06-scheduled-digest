"""
The crew: three agents, three tasks, handed along in order.

  researcher  reads the collected articles with two tools and returns structured picks         (task: research_task)
  writer      turns the picks into a short digest, citing articles by id                       (task: write_task)
  reviewer    runs the mechanical checks, compares the draft with the notes, approves or not   (task: review_task)

Delegation: the writer may ask the researcher a question when a note is missing a detail it needs. That is CrewAI's built-in
"Ask question to coworker" tool, and its cost counts against the same per-run cap.

The handoff is the task `context`: each task receives the previous task's output. The researcher's output is a pydantic
object (Research) and the reviewer's is a Verdict, so the two decisions that code acts on are data, not prose.

If the reviewer sends the draft back, run.py builds a second, smaller crew (revision_crew below): the writer fixes the listed
issues, then the reviewer looks again. One revision only. A loop with no limit is a cost problem waiting to happen.

The layout (config/agents.yaml, config/tasks.yaml, this class) is the standard CrewAI project shape.
"""

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from .schemas import Research, Verdict
from .tools import make_check_tool, make_tools

MAX_ITER = {"researcher": 10, "writer": 4, "reviewer": 4}      # steps each agent may take, tool calls included


@CrewBase
class DigestCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self, items, llms: dict, budget, on_step=None):
        self.items, self.llms, self.budget = items, llms, budget
        self.picked: set[str] = set()                         # filled when the research task finishes; the reviewer's check reads it
        self.events: list[dict] = []                          # what each agent did, for the run record and the app
        self._on_step = on_step

    # ---- callbacks ------------------------------------------------------------------------------------
    def _step(self, step) -> None:
        """Runs after every agent step and records it. (The cost cap is not here: see budget.guard().)"""
        kind = type(step).__name__                          # AgentAction (a tool call) or ToolResult (what came back)
        if kind == "AgentAction":
            self.events.append({"kind": "tool_call", "tool": step.tool, "input": str(step.tool_input)[:120]})
        else:
            self.events.append({"kind": "tool_result", "tool": None, "input": ""})
        if self._on_step:
            self._on_step(self.events[-1])

    def _research_done(self, output) -> None:
        data = output.pydantic
        if data:
            self.picked.update(p.id for p in data.picks)

    # ---- agents ---------------------------------------------------------------------------------------
    @agent
    def researcher(self) -> Agent:
        return Agent(config=self.agents_config["researcher"], llm=self.llms["researcher"], tools=make_tools(self.items),
                     max_iter=MAX_ITER["researcher"], allow_delegation=False, verbose=False)

    @agent
    def writer(self) -> Agent:
        # Only the writer may delegate: it can ask the researcher one question when a note is missing a detail. CrewAI adds the
        # "Ask question to coworker" tool for this. The researcher and reviewer never delegate, so a question cannot bounce around.
        return Agent(config=self.agents_config["writer"], llm=self.llms["writer"], max_iter=MAX_ITER["writer"],
                     allow_delegation=True, verbose=False)

    @agent
    def reviewer(self) -> Agent:
        return Agent(config=self.agents_config["reviewer"], llm=self.llms["reviewer"], tools=[make_check_tool(self.items, self.picked)],
                     max_iter=MAX_ITER["reviewer"], allow_delegation=False, verbose=False)

    # ---- tasks ----------------------------------------------------------------------------------------
    @task
    def research_task(self) -> Task:
        return Task(config=self.tasks_config["research_task"], agent=self.researcher(), output_pydantic=Research,
                    callback=self._research_done)

    @task
    def write_task(self) -> Task:
        return Task(config=self.tasks_config["write_task"], agent=self.writer(), context=[self.research_task()])

    @task
    def review_task(self) -> Task:
        return Task(config=self.tasks_config["review_task"], agent=self.reviewer(), output_pydantic=Verdict,
                    context=[self.research_task(), self.write_task()])

    # ---- crews ----------------------------------------------------------------------------------------
    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, step_callback=self._step,
                    memory=False, verbose=False)

    def revision_crew(self, notes: str) -> Crew:
        """Writer fixes the issues, reviewer looks again. `notes` is the research as plain text, so the reviewer can still compare."""
        notes = notes.replace("{", "(").replace("}", ")")       # braces would be read as {placeholders}
        rcfg = dict(self.tasks_config["revise_task"])
        rcfg["description"] = rcfg["description"].strip() + "\nResearch notes (use only these):\n" + notes
        revise = Task(config=rcfg, agent=self.writer())
        cfg = dict(self.tasks_config["review_task"])
        cfg["description"] = cfg["description"].strip() + "\nResearch notes to compare against:\n" + notes
        review = Task(config=cfg, agent=self.reviewer(), output_pydantic=Verdict, context=[revise])
        return Crew(agents=[self.writer(), self.reviewer()], tasks=[revise, review], process=Process.sequential,
                    step_callback=self._step, memory=False, verbose=False)
