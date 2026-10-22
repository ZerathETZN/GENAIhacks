"""Single entry point for every model call (AGENTS.md §5.3). Owner: B.

Order: Nightshift -> (transport failure only) NVIDIA direct
       -> (no credentials / SAMPLE_MODE) heuristic_fallback.
Engines and agents receive `generate` by injection; nothing else calls a model.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas import Provider


class GenerationResult(BaseModel):
    text: str
    provider: Provider
    served_by: str | None  # response.model as returned, never the requested model
    latency_ms: int


def generate(
    prompt: str,
    system_prompt: str | None = None,
    model: str | None = None,
    json_schema: type[BaseModel] | None = None,
) -> GenerationResult:
    """Generate text (or JSON validated against `json_schema`, one retry on
    validation error). max_tokens >= 800, client timeout 180 s."""
    # TODO(B): Nightshift client, NVIDIA fallback, heuristic_fallback.
    raise NotImplementedError("generate() is a Day-1 stub; B implements it")
