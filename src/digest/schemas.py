"""The shapes that pass between the agents. Each task has to return one of these, so a handoff is data, not a paragraph to re-read."""

from pydantic import BaseModel, Field


class Pick(BaseModel):
    id: str = Field(description="The article id, like i3. Must be one of the ids from list_items.")
    why: str = Field(description="One sentence on why a measurement or analytics lead should care. Use only facts from the article.")


class Research(BaseModel):
    picks: list[Pick] = Field(description="The articles worth including, most important first.")
    skipped: list[str] = Field(default_factory=list, description="Ids you read and left out, each with a few words on why.")


class Verdict(BaseModel):
    approved: bool = Field(description="True only if the draft is accurate to the research notes and passed check_draft.")
    issues: list[str] = Field(default_factory=list, description="What must change, one specific item per entry. Empty when approved.")
