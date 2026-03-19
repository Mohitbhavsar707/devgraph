"""
visualize.py — Exports the knowledge graph as a self-contained, interactive
HTML file using pyvis. Low-confidence edges are visually dimmed.
"""

import os
from pathlib import Path
from typing import Optional

import networkx as nx
from rich.console import Console

console = Console()

# ── Colour palette by entity type ────────────────────────────────────────────────

TYPE_COLORS = {
    "Engineer":   "#4f8ef7",   # blue
    "Service":    "#f7a24f",   # orange
    "Module":     "#7bc67e",   # green
    "Bug":        "#e05c5c",   # red
    "PR":         "#b57bee",   # purple
    "Deployment": "#f7e24f",   # yellow
    "Error":      "#f74f7a",   # pink
    "Unknown":    "#aaaaaa",   # grey
}

TYPE_SHAPES = {
    "Engineer":   "dot",
    "Service":    "square",
    "Module":     "triangle",
    "Bug":        "star",
    "PR":         "ellipse",
    "Deployment": "diamond",
    "Error":      "triangleDown",
    "Unknown":    "dot",
}


def export_html(
    G: nx.DiGraph,
    output_path: str = "devgraph.html",
    title: str = "DevGraph — Knowledge Graph",
    height: str = "750px",
) -> str:
    """
    Render the graph as an interactive HTML file.

    Args:
        G:           The NetworkX DiGraph.
        output_path: Where to write the HTML file.
        title:       Page title shown in the browser.
        height:      Canvas height.

    Returns:
        Absolute path of the written file.
    """
    try:
        from pyvis.network import Network
    except ImportError:
        console.print("[red]pyvis not installed — run: pip install pyvis[/red]")
        return ""

    net = Network(
        height    = height,
        width     = "100%",
        directed  = True,
        notebook  = False,
        bgcolor   = "#1a1a2e",
        font_color= "#ffffff",
    )
    net.set_options("""
    {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.005,
          "springLength": 120
        },
        "solver": "forceAtlas2Based",
        "stabilization": { "iterations": 150 }
      },
      "edges": {
        "smooth": { "type": "dynamic" },
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.6 } }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100
      }
    }
    """)

    # Add nodes
    for node_id, data in G.nodes(data=True):
        entity_type   = data.get("type", "Unknown")
        color         = TYPE_COLORS.get(entity_type, "#aaaaaa")
        shape         = TYPE_SHAPES.get(entity_type, "dot")
        mention_count = data.get("mention_count", 1)
        size          = max(10, min(50, 10 + mention_count * 3))
        aliases       = ", ".join(data.get("aliases", []))
        tooltip       = (
            f"<b>{data.get('name', node_id)}</b><br>"
            f"Type: {entity_type}<br>"
            f"Mentions: {mention_count}<br>"
            f"Aliases: {aliases or 'none'}"
        )

        net.add_node(
            node_id,
            label  = data.get("name", node_id),
            title  = tooltip,
            color  = color,
            shape  = shape,
            size   = size,
            font   = {"size": 12, "color": "#ffffff"},
        )

    # Add edges
    for src, tgt, data in G.edges(data=True):
        confidence = data.get("confidence", 1.0)
        dimmed     = data.get("dimmed", False)
        rel_type   = data.get("type", "")
        source_url = data.get("source_url", "")

        edge_color = (
            {"color": "#555566", "opacity": 0.35}
            if dimmed
            else {"color": "#aaaacc", "opacity": 0.85}
        )
        tooltip = (
            f"<b>{rel_type}</b><br>"
            f"Confidence: {confidence:.2f}<br>"
            f"Source: <a href='{source_url}'>{source_url[:60]}</a>"
        )

        net.add_edge(
            src, tgt,
            title  = tooltip,
            label  = rel_type,
            color  = edge_color,
            width  = max(1, confidence * 3),
            font   = {"size": 9, "color": "#88889a"},
        )

    # Inject legend HTML
    legend_html = _build_legend()

    net.save_graph(output_path)

    # Post-process: inject legend into the HTML
    with open(output_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("</body>", legend_html + "\n</body>")
    html = html.replace("<title>network</title>", f"<title>{title}</title>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    abs_path = str(Path(output_path).resolve())
    console.print(f"[bold green]✓ Interactive graph → {abs_path}[/bold green]")
    console.print("[dim]Open in any browser — no server needed.[/dim]")
    return abs_path


def _build_legend() -> str:
    items = "".join(
        f'<div style="margin:4px 0;display:flex;align-items:center;gap:8px;">'
        f'<span style="display:inline-block;width:14px;height:14px;'
        f'background:{color};border-radius:3px;"></span>'
        f'<span>{entity_type}</span></div>'
        for entity_type, color in TYPE_COLORS.items()
        if entity_type != "Unknown"
    )
    return f"""
<div style="position:fixed;top:16px;left:16px;background:rgba(20,20,40,0.88);
     color:#ddd;padding:14px 18px;border-radius:10px;font-family:sans-serif;
     font-size:13px;z-index:9999;border:1px solid #333;">
  <b style="font-size:15px;">DevGraph</b>
  <div style="margin:10px 0 6px;font-size:11px;opacity:0.7;text-transform:uppercase;
       letter-spacing:0.06em;">Entity types</div>
  {items}
  <div style="margin-top:10px;font-size:11px;opacity:0.6;">
    Dimmed edges = low confidence
  </div>
</div>"""
