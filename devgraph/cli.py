"""
cli.py — The main command-line interface for DevGraph.
Run `devgraph --help` after installation to see all commands.
"""

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from dotenv import load_dotenv

# Load .env automatically
load_dotenv()

app     = typer.Typer(help="DevGraph — Knowledge Graph Builder for Engineering Artifacts")
console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────────

def _require_graph():
    """Load graph or exit with a helpful message."""
    from devgraph.graph import load_graph
    G = load_graph()
    if G is None:
        console.print(
            "[red]No graph found.[/red] Run [bold]devgraph ingest[/bold] first."
        )
        raise typer.Exit(1)
    return G


# ── Commands ──────────────────────────────────────────────────────────────────────

@app.command()
def ingest(
    repo: str = typer.Argument(
        ..., help='GitHub repo in "owner/repo" format, e.g. "torvalds/linux"'
    ),
    max_items: int = typer.Option(
        200, "--max", "-m", help="Maximum number of issues/PRs to fetch"
    ),
    full_refresh: bool = typer.Option(
        False, "--full", "-f", help="Ignore checkpoint and re-ingest everything"
    ),
    no_export: bool = typer.Option(
        False, "--no-export", help="Skip HTML export after building the graph"
    ),
):
    """
    Ingest a GitHub repo: fetch → extract → resolve → build graph → export HTML.
    """
    console.print(Panel(
        f"[bold cyan]DevGraph Ingest[/bold cyan]\n"
        f"Repo: [yellow]{repo}[/yellow]  |  Max items: {max_items}",
        expand=False,
    ))

    from devgraph.ingestion    import fetch_artifacts
    from devgraph.extraction   import extract_from_artifacts
    from devgraph.coreference  import resolve_coreferences
    from devgraph.graph        import build_graph, save_graph, load_graph, merge_graphs
    from devgraph.visualize    import export_html

    # 1. Fetch
    artifacts = fetch_artifacts(repo, max_items=max_items, full_refresh=full_refresh)
    if not artifacts:
        console.print("[yellow]No new artifacts to process.[/yellow]")
        raise typer.Exit(0)

    # 2. Extract
    entities, relationships = extract_from_artifacts(artifacts)
    if not entities:
        console.print("[yellow]No entities extracted. Check your ANTHROPIC_API_KEY.[/yellow]")
        raise typer.Exit(1)

    # 3. Coreference resolution
    entities, relationships = resolve_coreferences(entities, relationships)

    # 4. Build new graph
    new_graph = build_graph(entities, relationships)

    # 5. Merge with existing graph (for incremental updates)
    existing = load_graph()
    if existing and not full_refresh:
        console.print("[cyan]Merging with existing graph …[/cyan]")
        new_graph = merge_graphs(existing, new_graph)

    # 6. Save
    save_graph(new_graph)

    # 7. Export HTML
    if not no_export:
        export_html(new_graph, title=f"DevGraph — {repo}")
        console.print("\n[bold green]Done![/bold green] Open [cyan]devgraph.html[/cyan] in your browser.")


@app.command()
def query(
    question: Optional[str] = typer.Argument(
        None, help="Question to ask in plain English (omit for interactive mode)"
    ),
):
    """
    Ask a plain-English question about the knowledge graph.
    Omit the question to enter interactive mode.
    """
    G = _require_graph()

    from devgraph.query import answer_question

    if question:
        _run_query(G, question)
    else:
        # Interactive REPL
        console.print(Panel(
            "[bold cyan]DevGraph Query REPL[/bold cyan]\n"
            "Type your questions in plain English. Type [bold]exit[/bold] to quit.",
            expand=False,
        ))
        while True:
            try:
                q = typer.prompt("\n❓ Question")
            except (KeyboardInterrupt, EOFError):
                break
            if q.strip().lower() in ("exit", "quit", "q"):
                break
            _run_query(G, q)


def _run_query(G, question: str):
    from devgraph.query import answer_question
    console.print(f"\n[dim]Thinking …[/dim]")
    result = answer_question(G, question)

    console.print(Panel(
        result.answer,
        title="[bold green]Answer[/bold green]",
        expand=False,
    ))

    if result.entities:
        table = Table(title="Relevant Entities", show_header=True, header_style="bold magenta")
        table.add_column("ID",       style="dim",    width=28)
        table.add_column("Name",     style="cyan",   width=24)
        table.add_column("Type",     style="yellow", width=14)
        table.add_column("Mentions", style="green",  width=10)
        for ent in result.entities[:15]:
            table.add_row(
                str(ent.get("id", "")),
                str(ent.get("name", "")),
                str(ent.get("type", "")),
                str(ent.get("mention_count", "")),
            )
        console.print(table)

    if result.sources:
        console.print("\n[bold]Sources:[/bold]")
        for url in result.sources[:5]:
            console.print(f"  • [link={url}]{url}[/link]")


@app.command()
def export(
    output: str = typer.Option("devgraph.html", "--output", "-o", help="Output HTML file"),
):
    """Re-export the graph to an HTML visualisation without re-ingesting."""
    G = _require_graph()
    from devgraph.visualize import export_html
    export_html(G, output_path=output)


@app.command()
def stats():
    """Print a summary of the current graph."""
    import networkx as nx
    G = _require_graph()

    console.print(Panel("[bold cyan]Graph Statistics[/bold cyan]", expand=False))

    # Node type breakdown
    type_counts: dict = {}
    for _, data in G.nodes(data=True):
        t = data.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Entity Type", style="cyan")
    table.add_column("Count",       style="green")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        table.add_row(t, str(c))
    console.print(table)

    console.print(f"\nTotal nodes : [bold green]{G.number_of_nodes()}[/bold green]")
    console.print(f"Total edges : [bold green]{G.number_of_edges()}[/bold green]")

    # Top 5 most-connected nodes
    top = sorted(G.degree(), key=lambda x: x[1], reverse=True)[:5]
    console.print("\n[bold]Top 5 most-connected nodes:[/bold]")
    for nid, deg in top:
        name = G.nodes[nid].get("name", nid)
        ntype = G.nodes[nid].get("type", "?")
        console.print(f"  • [cyan]{name}[/cyan] ({ntype}) — degree {deg}")


@app.command()
def reset(
    repo: str = typer.Argument(..., help='Repo to clear checkpoint for ("owner/repo")'),
):
    """Clear the ingestion checkpoint so the next run re-fetches everything."""
    from devgraph.checkpoint import clear_cursor
    clear_cursor(repo)
    console.print(f"[green]Checkpoint cleared for {repo}.[/green]")


if __name__ == "__main__":
    app()
