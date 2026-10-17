from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Project(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: Annotated[str, Field(max_length=120)]
    created_at: AwareDatetime
