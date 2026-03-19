"""
ingestion.py — Fetches GitHub Issues and Pull Requests via the REST API.
Supports incremental ingestion: only pulls artifacts newer than the last checkpoint.
"""

import os
import time
from typing import List, Optional, Generator
from datetime import datetime, timezone

import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from devgraph.models import GitHubArtifact
from devgraph.checkpoint import get_last_cursor, set_cursor

console = Console()

GITHUB_API = "https://api.github.com"
PER_PAGE   = 100   # max allowed by GitHub


def _headers() -> dict:
    token = os.getenv("GITHUB_TOKEN", "")
    h = {"Accept": "application/vnd.github.v3+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, params: dict = None) -> dict | list:
    """Single GET with basic rate-limit handling."""
    resp = requests.get(url, headers=_headers(), params=params or {}, timeout=30)
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
        wait = max(reset_at - int(time.time()), 1)
        console.print(f"[yellow]Rate limit hit — waiting {wait}s…[/yellow]")
        time.sleep(wait)
        return _get(url, params)
    resp.raise_for_status()
    return resp.json()


def _fetch_comments(repo: str, number: int, kind: str) -> List[str]:
    """Fetch all comment bodies for an issue or PR."""
    path = "issues" if kind == "issue" else "pulls"
    url  = f"{GITHUB_API}/repos/{repo}/{path}/{number}/comments"
    try:
        items = _get(url, {"per_page": 100})
        return [c.get("body", "") for c in items if c.get("body")]
    except Exception:
        return []


def _iter_pages(url: str, params: dict) -> Generator[list, None, None]:
    """Yield pages of results until GitHub returns an empty page."""
    page = 1
    while True:
        params["page"] = page
        data = _get(url, params)
        if not data:
            break
        yield data
        if len(data) < PER_PAGE:
            break
        page += 1


def fetch_artifacts(
    repo: str,
    max_items: int = 500,
    full_refresh: bool = False,
) -> List[GitHubArtifact]:
    """
    Pull Issues + PRs from a GitHub repo.

    Args:
        repo:          "owner/repo" string, e.g. "torvalds/linux"
        max_items:     Hard cap on total artifacts returned.
        full_refresh:  Ignore checkpoint; re-fetch everything.

    Returns:
        List of GitHubArtifact objects ready for the extraction pipeline.
    """
    since  = None if full_refresh else get_last_cursor(repo)
    newest = None

    results: List[GitHubArtifact] = []

    params = {
        "state":    "all",
        "per_page": PER_PAGE,
        "sort":     "created",
        "direction": "desc",
    }
    if since:
        params["since"] = since
        console.print(f"[cyan]Incremental mode — fetching items since {since}[/cyan]")
    else:
        console.print(f"[cyan]Full refresh — fetching all items for {repo}[/cyan]")

    url = f"{GITHUB_API}/repos/{repo}/issues"   # returns both issues AND PRs

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Fetching {repo} …", total=None)

        for page_items in _iter_pages(url, params):
            for item in page_items:
                if len(results) >= max_items:
                    break

                kind     = "pr" if "pull_request" in item else "issue"
                number   = item["number"]
                created  = item.get("created_at", "")

                # track the newest timestamp to save as cursor
                if newest is None:
                    newest = created

                comments = _fetch_comments(repo, number, kind)

                artifact = GitHubArtifact(
                    url        = item.get("html_url", ""),
                    number     = number,
                    type       = kind,
                    title      = item.get("title", ""),
                    body       = item.get("body", "") or "",
                    author     = item.get("user", {}).get("login", "unknown"),
                    created_at = created,
                    labels     = [l["name"] for l in item.get("labels", [])],
                    comments   = comments,
                )
                results.append(artifact)
                progress.update(task, description=f"Fetched {len(results)} artifacts …")

            if len(results) >= max_items:
                break

    if newest and not full_refresh:
        set_cursor(repo, newest)
        console.print(f"[green]Checkpoint saved: {newest}[/green]")

    console.print(f"[bold green]✓ Fetched {len(results)} artifacts from {repo}[/bold green]")
    return results
