"""Static roster and profile metadata for the multi-agent control deck."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .safe_paths import resolve_child


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    role: str
    avatar_filename: str
    sort_order: int

    @property
    def avatar_url(self) -> str:
        return f"/api/agents/{self.id}/avatar"


AGENT_ROSTER: tuple[AgentProfile, ...] = (
    AgentProfile("hermione", "Hermione", "Orchestrator / Administrator", "Hermione.png", 10),
    AgentProfile("hephaestus", "Hephaestus", "Coding / Software Engineering", "Hephaestus.jpeg", 20),
    AgentProfile("argus", "Argus", "Sysadmin / Monitoring", "Argus.jpeg", 30),
    AgentProfile("athena", "Athena", "Research / Analysis", "Athena.jpeg", 40),
    AgentProfile("aegis", "Aegis", "Security Review / Risk", "Aegis.jpeg", 50),
    AgentProfile("daedalus", "Daedalus", "Lab / Infrastructure Architecture", "Daedalus.jpeg", 60),
    AgentProfile("vox", "Vox", "Voice Interface", "Vox.jpeg", 70),
)

_BY_ID = {a.id: a for a in AGENT_ROSTER}
_BY_NAME = {a.name.lower(): a for a in AGENT_ROSTER}
ALIASES = {
    "hermes": "hermione",
    "hermione": "hermione",
    "hephaestus": "hephaestus",
    "coding": "hephaestus",
    "argus": "argus",
    "ops": "argus",
    "athena": "athena",
    "research": "athena",
    "aegis": "aegis",
    "security": "aegis",
    "daedalus": "daedalus",
    "lab": "daedalus",
    "vox": "vox",
    "voice": "vox",
}


def all_agents() -> Iterable[AgentProfile]:
    return AGENT_ROSTER


def get_agent(agent_id: str) -> AgentProfile | None:
    key = str(agent_id or "").strip().lower()
    if not key or any(sep in key for sep in ("/", "\\")) or ".." in key:
        return None
    return _BY_ID.get(key)


def normalize_agent(value: str | None) -> str | None:
    """Map free-form assignee names into roster ids when possible."""
    if not value:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    if key in ALIASES:
        return ALIASES[key]
    if key in _BY_NAME:
        return _BY_NAME[key].id
    # Tolerate labels like "Hermione <...>" or "agent:Daedalus".
    for profile in AGENT_ROSTER:
        if profile.id in key or profile.name.lower() in key:
            return profile.id
    return None


def avatar_path(profiles_dir: Path, agent_id: str) -> Path | None:
    profile = get_agent(agent_id)
    if profile is None:
        return None
    try:
        path = resolve_child(profiles_dir, profile.avatar_filename)
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def roster_payload() -> list[dict[str, object]]:
    return [
        {
            "id": a.id,
            "name": a.name,
            "role": a.role,
            "avatar_url": a.avatar_url,
            "sort_order": a.sort_order,
        }
        for a in AGENT_ROSTER
    ]
