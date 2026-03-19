"""
query.py — Translates plain-English questions into graph traversal plans,
executes them, and returns cited answers. Uses local Ollama (free).
"""

import json
import os
import re
from typing import List, Dict, Any

import requests
import networkx as nx
from rich.console import Console

from devgraph.models import QueryResult
from devgraph.graph import find_nodes_by_name, find_nodes_by_type, get_neighbors, top_nodes_by_degree

console = Console()

OLLAMA_BASE   = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


def _get_model() -> str:
    return os.getenv("DEVGRAPH_MODEL", DEFAULT_MODEL)


def _call_ollama(system: str, user: str, model: str, max_tokens: int = 600) -> str:
    """Try /api/chat, fall back to /api/generate for older Ollama versions."""
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        }
        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=120)
        if resp.status_code == 404:
            raise ValueError("use generate")
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        if "use generate" not in str(e) and "404" not in str(e):
            raise

    prompt = f"System: {system}\n\nUser: {user}\n\nAssistant:"
    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens},
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["response"].strip()


PLANNER_SYSTEM = """You are a graph query planner. Given a question about a software engineering knowledge graph, produce a JSON execution plan.

Node types: Engineer, Service, Module, Bug, PR, Deployment, Error
Edge types: AUTHORED, REVIEWED, FIXED, BROKE, DEPENDS_ON, MENTIONED_IN, DEPLOYED_BY, CAUSED_BY

Return ONLY valid JSON, no markdown, no explanation:
{
  "intent": "find_top_contributors | find_related | find_bugs | general_search",
  "entity_name": "name to search for, or null",
  "entity_type": "node type filter, or null",
  "rel_type": "edge type filter, or null",
  "limit": 10,
  "summary_instruction": "brief instruction"
}"""


def _plan_query(question: str, model: str) -> dict:
    raw = _call_ollama(PLANNER_SYSTEM, question, model, max_tokens=200)
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    return json.loads(raw)


def _execute_plan(G: nx.DiGraph, plan: dict) -> Dict[str, Any]:
    intent      = plan.get("intent", "general_search")
    entity_name = plan.get("entity_name")
    entity_type = plan.get("entity_type")
    rel_type    = plan.get("rel_type")
    limit       = plan.get("limit", 10)

    nodes, edges, sources = [], [], []

    if intent == "find_top_contributors":
        target_ids = find_nodes_by_name(G, entity_name) if entity_name else []
        for tid in target_ids[:3]:
            neighbours = get_neighbors(G, tid, rel_type)
            for src, _, data in G.in_edges(tid, data=True):
                if not rel_type or data.get("type") == rel_type:
                    neighbours.append({"node": src, "data": dict(G.nodes[src]), "edge": data})
            if entity_type:
                neighbours = [n for n in neighbours if n["data"].get("type") == entity_type]
            neighbours.sort(key=lambda x: G.degree(x["node"]), reverse=True)
            for n in neighbours[:limit]:
                nodes.append({"id": n["node"], **n["data"]})
                edges.append({**n["edge"], "source": tid, "target": n["node"]})
                if n["edge"].get("source_url"):
                    sources.append(n["edge"]["source_url"])

    elif intent in ("find_related", "find_bugs"):
        target_ids = find_nodes_by_name(G, entity_name) if entity_name else []
        for tid in target_ids[:3]:
            all_n = list(get_neighbors(G, tid, rel_type)) + [
                {"node": s, "data": dict(G.nodes[s]), "edge": d}
                for s, _, d in G.in_edges(tid, data=True)
            ]
            if entity_type:
                all_n = [n for n in all_n if n["data"].get("type") == entity_type]
            for n in all_n[:limit]:
                nodes.append({"id": n["node"], **n["data"]})
                if n["edge"].get("source_url"):
                    sources.append(n["edge"]["source_url"])

    else:  # general_search
        if entity_type:
            for nid, data in find_nodes_by_type(G, entity_type)[:limit]:
                nodes.append({"id": nid, **data})
        elif entity_name:
            for nid in find_nodes_by_name(G, entity_name)[:limit]:
                nodes.append({"id": nid, **G.nodes[nid]})
        else:
            for nid, data in top_nodes_by_degree(G, n=limit):
                nodes.append({"id": nid, **data})

    return {"nodes": nodes, "edges": edges, "sources": list(set(sources))}


def _summarize(question: str, raw_results: dict, model: str) -> str:
    if not raw_results["nodes"]:
        return "No matching entities found in the graph for that question."
    context = json.dumps({"question": question, "results": raw_results["nodes"][:20]}, default=str, indent=2)
    system  = (
        "You answer questions about a software engineering knowledge graph. "
        "Given JSON with a question and graph results, write a clear plain-English answer. "
        "Be specific — name actual engineers, services, and bugs. Keep it under 150 words."
    )
    return _call_ollama(system, context, model, max_tokens=300)


def answer_question(G: nx.DiGraph, question: str) -> QueryResult:
    model = _get_model()
    try:
        plan = _plan_query(question, model)
    except Exception as e:
        console.print(f"[yellow]Planning fell back to general search: {e}[/yellow]")
        plan = {"intent": "general_search", "entity_name": None, "entity_type": None, "rel_type": None, "limit": 10}

    raw    = _execute_plan(G, plan)
    answer = _summarize(question, raw, model)
    return QueryResult(answer=answer, entities=raw["nodes"], edges=raw["edges"], sources=raw["sources"])
