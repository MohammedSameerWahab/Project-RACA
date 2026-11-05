from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Repository:
    """
    Represents one repository loaded into RACA.

    This is application-level repository identity.
    It is intentionally separate from the database records
    used by the retrieval layers.
    """

    name: str
    path: Path
    source_url: str

    @property
    def identifier(self) -> str:
        """
        Stable identifier used by the application to select
        the repository during retrieval.
        """
        return self.name