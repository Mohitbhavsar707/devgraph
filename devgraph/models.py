"""
models.py — Pydantic schemas for every entity and relationship DevGraph understands.
All LLM extraction output is validated against these schemas before touching the graph.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


# ── Entity types ────────────────────────────────────────────────────────────────

class EntityType(str, Enum):
    ENGINEER    = "Engineer"
    SERVICE     = "Service"
    MODULE      = "Module"
    BUG         = "Bug"
    PR          = "PR"
    DEPLOYMENT  = "Deployment"
    ERROR       = "Error"


# ── Relationship types ───────────────────────────────────────────────────────────

class RelationshipType(str, Enum):
    AUTHORED     = "AUTHORED"
    REVIEWED     = "REVIEWED"
    FIXED        = "FIXED"
    BROKE        = "BROKE"
    DEPENDS_ON   = "DEPENDS_ON"
    MENTIONED_IN = "MENTIONED_IN"
    DEPLOYED_BY  = "DEPLOYED_BY"
    CAUSED_BY    = "CAUSED_BY"


# ── Core data models ─────────────────────────────────────────────────────────────

class Entity(BaseModel):
    id:       str                       # slug, e.g. "engineer:mohit"
    name:     str                       # canonical display name
    type:     EntityType
    aliases:  List[str]   = []          # alternate names seen in text
    metadata: Dict[str, Any] = {}       # timestamps, URLs, mention_count, etc.


class Relationship(BaseModel):
    source_id:        str
    target_id:        str
    type:             RelationshipType
    confidence:       float = Field(ge=0.0, le=1.0)   # 0–1 from LLM
    source_artifact:  str                              # PR/issue URL where found
    metadata:         Dict[str, Any] = {}


# ── LLM extraction envelope ──────────────────────────────────────────────────────

class ExtractionResult(BaseModel):
    """Exactly what the LLM must return for each text chunk."""
    entities:      List[Entity]
    relationships: List[Relationship]


# ── GitHub raw artifact ──────────────────────────────────────────────────────────

class GitHubArtifact(BaseModel):
    url:        str
    number:     int
    type:       str          # "issue" | "pr"
    title:      str
    body:       str
    author:     str
    created_at: str
    labels:     List[str] = []
    comments:   List[str] = []


# ── Query result ─────────────────────────────────────────────────────────────────

class QueryResult(BaseModel):
    answer:   str
    entities: List[Dict[str, Any]] = []
    edges:    List[Dict[str, Any]] = []
    sources:  List[str]            = []   # PR/issue URLs that support the answer
