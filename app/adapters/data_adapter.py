"""DataAdapter interface (AGENTS.md §5.1).

Agents only ever talk to this interface. Two implementations share the same
logical table and view names:
  - ZetarisAdapter (live, REST)        -> app/adapters/zetaris_adapter.py
  - DuckDBAdapter  (SAMPLE_MODE twin)  -> app/adapters/duckdb_adapter.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

Row = dict[str, Any]
Params = Mapping[str, Any] | Sequence[Any] | None


class AdapterError(RuntimeError):
    """Raised when a query fails. `recoverable` tells the orchestrator whether
    falling back to DuckDB (logged as adapter_fallback) makes sense."""

    def __init__(self, message: str, *, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class DataAdapter(ABC):
    """One read-only SQL entry point over the fragmented sources."""

    #: "zetaris" or "duckdb"; recorded in RunResult.adapter and trace events.
    name: str

    @abstractmethod
    def query(self, sql: str, params: Params = None, limit: int = 1000) -> list[Row]:
        """Run one SQL statement and return rows as dicts keyed by column name.

        Contract every implementation must honour:
          - one statement per call, plain ANSI SQL with qualified names
            (`<source>.<table>` or `recallguard.product_exposure_v`)
          - values are cast to Python types (int/float/str/None), never left
            as the strings Zetaris REST returns
          - at most `limit` rows
          - bounded by a timeout; failures raise AdapterError
        """
        raise NotImplementedError
