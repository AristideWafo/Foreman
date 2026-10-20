from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Project(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: Annotated[str, Field(max_length=120)]
    team_id: UUID
    team_name: str
    created_at: AwareDatetime
