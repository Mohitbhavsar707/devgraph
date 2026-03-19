"""
extraction.py — Uses a local Ollama model (100% free, runs on your laptop) to
extract typed entities and relationships from GitHub text.
"""

import json
import os
import re
import hashlib
from typing import List, Tuple

import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from devgraph.models import (
    Entity, Relationship, ExtractionResult, GitHubArtifact,
)

console = Console()

OLLAMA_BASE   = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"

SYSTEM_PROMPT = """You are a precise information-extraction engine for software engineering artifacts.
Extract entities and relationships from the provided GitHub issue or PR text.

ENTITY TYPES (use EXACTLY these strings):
  Engineer, Service, Module, Bug, PR, Deployment, Error

RELATIONSHIP TYPES (use EXACTLY these strings):
  AUTHORED, REVIEWED, FIXED, BROKE, DEPENDS_ON, MENTIONED_IN, DEPLOYED_BY, CAUSED_BY

RULES:
1. Return ONLY valid JSON matching the schema below — absolutely no prose, no markdown fences.
2. Every entity id must be: "<type_lowercase>:<name_slug>" e.g. "engineer:mohit", "service:auth"
3. Relationship confidence (0.0–1.0): 0.9+ = explicitly stated, 0.6–0.9 = strongly implied, <0.6 = inferred.
4. If nothing can be extracted, return: {"entities": [], "relationships": []}

OUTPUT SCHEMA:
{
  "entities": [
    {"id": "...", "name": "...", "type": "...", "aliases": [], "metadata": {}}
  ],
  "relationships": [
    {"source_id": "...", "target_id": "...", "type": "...", "confidence": 0.85,
     "source_artifact": "...", "metadata": {}}
  ]
}"""

USER_TEMPLATE = """Artifact URL: {url}
Author: {author}
Created: {created_at}
Type: {kind}
Title: {title}

Body:
{body}

Comments:
{comments}

Extract all entities and relationships. Return ONLY the JSON object, nothing else."""


def _get_model() -> str:
    return os.getenv("DEVGRAPH_MODEL", DEFAULT_MODEL)


def _check_ollama() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _list_local_models() -> list:
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        return [t["name"] for t in r.json().get("models", [])]
    except Exception:
        return []


def _ensure_model(model: str) -> None:
    """Check if model is available; if not, prompt user to pull it."""
    local = _list_local_models()
    # Match by base name (strip :tag for comparison)
    base = model.split(":")[0]
    available = any(m.split(":")[0] == base for m in local)
    if not available:
        console.print(f"[yellow]Model '{model}' not found. Run this in a new terminal:[/yellow]")
        console.print(f"[bold]  ollama pull {model}[/bold]")
        console.print(f"[yellow]Then re-run devgraph.[/yellow]")
        raise SystemExit(1)
    console.print(f"[green]Model '{model}' is ready.[/green]")


def _call_ollama(system: str, user: str, model: str) -> str:
    """
    Call Ollama. Tries /api/chat first (newer Ollama), falls back to
    /api/generate (older Ollama) if chat returns 404.
    """
    # Try /api/chat first
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=120)
        if resp.status_code == 404:
            raise ValueError("chat endpoint not available")
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except (ValueError, Exception) as e:
        if "404" not in str(e) and "chat endpoint" not in str(e):
            # Real error, not just missing endpoint
            raise

    # Fall back to /api/generate
    prompt = f"System: {system}\n\nUser: {user}\n\nAssistant:"
    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _parse_response(raw: str, artifact_url: str) -> ExtractionResult | None:
    """Strip markdown fences, find JSON, parse into ExtractionResult."""
    try:
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            raw = match.group(0)
        data = json.loads(raw)
        for rel in data.get("relationships", []):
            if not rel.get("source_artifact"):
                rel["source_artifact"] = artifact_url
        return ExtractionResult(**data)
    except Exception as e:
        console.print(f"[dim red]Parse failed for {artifact_url}: {e}[/dim red]")
        return None


def extract_from_artifacts(
    artifacts: List[GitHubArtifact],
    batch_size: int = 1,
) -> Tuple[List[Entity], List[Relationship]]:
    if not _check_ollama():
        console.print(
            "[bold red]Ollama is not running![/bold red]\n"
            "Start it with: [bold]ollama serve[/bold]\n"
            "Or open the Ollama app from your Applications folder."
        )
        raise SystemExit(1)

    model = _get_model()
    _ensure_model(model)
    console.print(f"[cyan]Using local model: [bold]{model}[/bold] (free, no API key needed)[/cyan]")

    all_entities:      dict[str, Entity]  = {}
    all_relationships: List[Relationship] = []
    seen_rel_keys:     set[str]           = set()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Extracting entities …", total=len(artifacts))

        for artifact in artifacts:
            user_prompt = USER_TEMPLATE.format(
                url        = artifact.url,
                author     = artifact.author,
                created_at = artifact.created_at,
                kind       = artifact.type,
                title      = artifact.title,
                body       = artifact.body[:1500],
                comments   = "\n".join(artifact.comments[:5])[:500],
            )

            try:
                raw    = _call_ollama(SYSTEM_PROMPT, user_prompt, model)
                result = _parse_response(raw, artifact.url)
            except Exception as e:
                console.print(f"[dim red]Extraction failed for {artifact.url}: {e}[/dim red]")
                result = None

            if result:
                for ent in result.entities:
                    if ent.id in all_entities:
                        existing = all_entities[ent.id]
                        existing.aliases = list(set(existing.aliases + ent.aliases + [ent.name]))
                        existing.metadata["mention_count"] = existing.metadata.get("mention_count", 1) + 1
                    else:
                        ent.metadata.setdefault("mention_count", 1)
                        all_entities[ent.id] = ent

                for rel in result.relationships:
                    key = hashlib.md5(f"{rel.source_id}|{rel.target_id}|{rel.type}|{rel.source_artifact}".encode()).hexdigest()
                    if key not in seen_rel_keys:
                        seen_rel_keys.add(key)
                        all_relationships.append(rel)

            progress.advance(task)

    entities = list(all_entities.values())
    console.print(f"[bold green]✓ Extracted {len(entities)} entities, {len(all_relationships)} relationships[/bold green]")
    return entities, all_relationships
