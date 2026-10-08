"""Rank root-cause candidates in the causal graph.

Groot ranks with "a customized PageRank" whose formula and weights eBay did not
publish. This is K8s-Hub's OWN design, built the same way:

1. Personalized PageRank on the graph with edges REVERSED (effect → cause): a
   walker starts at the symptoms and keeps stepping to a cause, choosing
   heavier edges more often; with probability 1-DAMPING it jumps back to a
   symptom. Events with no known cause keep the walker (a self-loop), so mass
   collects where explanations end — at root causes.
2. score = PPR × prior of the event type (model.EVENT_TYPES: a rollout or a
   memory limit is a usual root, "pod not ready" almost never is)
         × ROOT_BONUS when nothing in the graph explains the event further.
3. Ties go to the EARLIER event: of two equally likely causes, the one that
   came first is more likely to have started the chain.

Each hypothesis carries its causal chain — the heaviest path from it down to a
symptom — so the UI and the LLM can show WHY it ranks there.
"""

from __future__ import annotations

from collections import defaultdict

from app.modules.rca.causality import CausalGraph
from app.modules.rca.learning import NEUTRAL, Weights
from app.modules.rca.model import CausalEdge, Hypothesis

DAMPING = 0.85
ITERATIONS = 100
TOLERANCE = 1e-9
ROOT_BONUS = 1.3
TOP_K = 3


def pagerank(graph: CausalGraph) -> dict[str, float]:
    nodes = list(graph.events)
    if not nodes:
        return {}
    causes: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for e in graph.edges:
        causes[e.effect].append((e.cause, e.weight))
    seeds = [s for s in graph.seeds if s in graph.events] or nodes
    restart = {n: (1 / len(seeds) if n in seeds else 0.0) for n in nodes}
    rank = dict(restart)
    for _ in range(ITERATIONS):
        nxt = {n: (1 - DAMPING) * restart[n] for n in nodes}
        for n in nodes:
            out = causes.get(n)
            if not out:
                nxt[n] += DAMPING * rank[n]  # no further cause: the walker stays
                continue
            total = sum(w for _, w in out)
            for cause, w in out:
                nxt[cause] += DAMPING * rank[n] * w / total
        delta = sum(abs(nxt[n] - rank[n]) for n in nodes)
        rank = nxt
        if delta < TOLERANCE:
            break
    return rank


def _chain(graph: CausalGraph, root: str) -> tuple[list[str], list[str]]:
    """Heaviest path from `root` down (cause → effect) to a symptom."""
    effects: dict[str, list[CausalEdge]] = defaultdict(list)
    for e in graph.edges:
        effects[e.cause].append(e)
    seeds = set(graph.seeds)
    best: tuple[float, list[str], list[str]] = (-1.0, [root], [])

    def walk(node: str, score: float, path: list[str], rules: list[str]) -> None:
        nonlocal best
        # The graph is at most MAX_DEPTH hops deep; the length cap keeps the
        # search bounded even if cycles make it look deeper.
        if (node in seeds and len(path) > 1) or not effects.get(node) or len(path) > 7:
            if score > best[0] or (score == best[0] and len(path) > len(best[1])):
                best = (score, path, rules)
            return
        for e in effects[node]:
            if e.effect not in path:  # the graph may have cycles (A→B, B→A)
                walk(e.effect, score * e.weight, [*path, e.effect], [*rules, e.rule])

    walk(root, 1.0, [root], [])
    return best[1], best[2]


def rank(graph: CausalGraph, k: int = TOP_K, weights: Weights = NEUTRAL) -> list[Hypothesis]:
    ppr = pagerank(graph)
    has_cause = {e.effect for e in graph.edges}
    scored = []
    for event_id, value in ppr.items():
        ev = graph.events[event_id]
        prior = ev.prior * weights.type(ev.type)  # × what feedback taught about this type
        score = value * prior * (ROOT_BONUS if event_id not in has_cause else 1.0)
        scored.append((score, ev.start, event_id))
    # Highest score first; among (near-)equal scores, the earlier event.
    scored.sort(key=lambda x: (-round(x[0], 6), x[1]))
    total = sum(s for s, _, _ in scored) or 1.0
    out = []
    for i, (score, _, event_id) in enumerate(scored[:k], start=1):
        chain, rules = _chain(graph, event_id)
        out.append(Hypothesis(i, event_id, round(score / total, 4), chain, rules))
    return out


__all__ = ["DAMPING", "ROOT_BONUS", "TOP_K", "pagerank", "rank"]
