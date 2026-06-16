"""Pydantic request/response models.

Most responses are still plain dicts (fine for this stage). Request bodies that
need validation live here so the routes stay thin and FastAPI documents them.
"""

from pydantic import BaseModel, field_validator


class SearchRequest(BaseModel):
    """Body for POST /api/search."""

    riot_id: str

    @field_validator("riot_id")
    @classmethod
    def _looks_like_riot_id(cls, value: str) -> str:
        value = value.strip()
        # A Riot id is "GameName#TAG"; reject anything obviously malformed before
        # we spend a queue slot / API call on it.
        if "#" not in value or value.startswith("#") or value.endswith("#"):
            raise ValueError("riot_id must look like 'GameName#TAG'")
        return value
