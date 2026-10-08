"""Run the RCA evaluation on lab1 and score it against an LLM-only baseline.

For each scenario: clean the lab → healthy setup → inject the fault → wait →
  1. K8s-Hub RCA (stored as a normal diagnosis, with the AI report): hit@1,
     hit@3 of the ranked causes, and whether the AI's chosen root cause is right;
  2. baseline: the chat assistant with the same read-only tools (no
     diagnose_incident, no write tools) asked "what is the root cause?";
     graded by keywords on its ROOT CAUSE line;
→ clean up. Results go to rca_eval/results/<timestamp>.{json,md}.

    PYTHONUTF8=1 .venv/Scripts/python.exe -m rca_eval.run                 # all scenarios
    PYTHONUTF8=1 .venv/Scripts/python.exe -m rca_eval.run --only oom,bad-image --no-baseline

Writes to the cluster, in namespace rca-lab only. Needs KUBECONFIG for lab1,
the database (runs are stored) and an LLM key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rca_eval import lab
from rca_eval.scenarios import BY_ID, SCENARIOS, Scenario

RESULTS = Path(__file__).parent / "results"
REQUESTER = "rca-eval@k8s-hub"


@dataclass
class Result:
    scenario: str
    title: str
    expected: str
    rca_ranked: list[str] = field(default_factory=list)
    rca_hit_rank: int | None = None  # 1-based rank of the first correct cause
    ai_root: str | None = None
    ai_hit: bool | None = None
    rca_seconds: float = 0.0
    report_seconds: float = 0.0
    rca_tokens: int = 0
    run_id: str | None = None
    baseline_answer: str | None = None
    baseline_hit: bool | None = None
    baseline_seconds: float = 0.0
    baseline_tokens: int = 0
    k8sgpt_findings: list[str] = field(default_factory=list)
    k8sgpt_hit: bool | None = None
    error: str | None = None


def matches(event_id: str, s: Scenario) -> bool:
    """`Rollout:Workload/rca-lab/web` → right type, and the entity is the expected
    object or one of its pods (`hog-7d9f…`)."""
    etype, _, key = event_id.partition(":")
    name = key.rsplit("/", 1)[-1]
    return etype in s.expect_types and (
        name == s.expect_entity or name.startswith(f"{s.expect_entity}-")
    )


async def run_rca(
    s: Scenario,
    since: datetime,
    r: Result,
    provider: str | None,
    model: str | None,
    with_report: bool = True,
    feedback: bool = False,
) -> None:
    from sqlalchemy import select

    from app.db.models.rca import RcaHypothesis, RcaRun
    from app.db.session import get_sessionmaker
    from app.modules.rca import pipeline, report

    # Just this scenario: a wider window would pick up events of the previous one.
    minutes = max(5, int((datetime.now(UTC) - since).total_seconds() // 60) + 2)
    run = await pipeline.create_run(
        namespace=lab.NAMESPACE, trigger="manual", requested_by=None, requested_by_email=REQUESTER,
        target_kind="Workload", target_name=s.target, lookback_minutes=minutes,
    )  # fmt: skip
    r.run_id = str(run.id)
    t0 = time.perf_counter()
    await pipeline.execute_run(run.id, with_report=False)
    r.rca_seconds = round(time.perf_counter() - t0, 2)
    if with_report:
        t1 = time.perf_counter()
        await report.write_report(run.id, provider=provider, model=model)
        r.report_seconds = round(time.perf_counter() - t1, 2)

    async with get_sessionmaker()() as db:
        row = await db.get(RcaRun, run.id)
        hyps = (
            await db.scalars(
                select(RcaHypothesis)
                .where(RcaHypothesis.run_id == run.id)
                .order_by(RcaHypothesis.rank)
            )
        ).all()
    if row is None or row.status != "completed":
        r.error = (row.error if row else None) or "the diagnosis failed"
        return
    r.rca_ranked = [h.event_id for h in hyps]
    r.rca_hit_rank = next((h.rank for h in hyps if matches(h.event_id, s)), None)
    if feedback and hyps:
        # The scenario's ground truth as feedback (learning.py): the true cause is
        # "right", everything ranked above it "not it" (all of the top-3 if missed).
        from app.modules.rca import learning

        last = r.rca_hit_rank or len(hyps)
        for h in hyps[:last]:
            await learning.record(run.id, h.rank, h.rank == r.rca_hit_rank, by=REQUESTER)
    rep = row.report or {}
    tokens = rep.get("tokens") or {}
    r.rca_tokens = int(tokens.get("input", 0)) + int(tokens.get("output", 0))
    chosen = rep.get("root_cause_rank")
    if chosen:
        root = next((h.event_id for h in hyps if h.rank == chosen), None)
        r.ai_root = root
        r.ai_hit = bool(root and matches(root, s))
    elif row.report_status == "done":
        r.ai_hit = False


BASELINE_QUESTION = (
    "Workload {target} in namespace rca-lab is having problems. Investigate with your tools and "
    "find the ROOT CAUSE (what changed or what is wrong), not just the symptom. "
    "End your answer with one line: ROOT CAUSE: <cause>."
)


async def run_baseline(s: Scenario, r: Result, provider: str | None, model: str | None) -> None:
    from langchain_core.messages import HumanMessage

    from app.modules.nl_command.agent import build_chat_graph
    from app.modules.tools.registry import registry
    from app.modules.tools.schema import Danger

    tools = [
        spec.tool
        for spec in registry.all()
        if spec.danger == Danger.READ
        and spec.name != "diagnose_incident"
        and registry.can_run(spec) is None
    ]
    graph = build_chat_graph(provider=provider, model=model, tools=tools)
    t0 = time.perf_counter()
    state = await graph.ainvoke(
        {"messages": [HumanMessage(BASELINE_QUESTION.format(target=s.target))]},
        config={"recursion_limit": 40, "metadata": {"user": REQUESTER, "user_role": "user"}},
    )
    r.baseline_seconds = round(time.perf_counter() - t0, 2)
    messages = state["messages"]
    for m in messages:
        usage = getattr(m, "usage_metadata", None) or {}
        r.baseline_tokens += int(usage.get("input_tokens") or 0) + int(
            usage.get("output_tokens") or 0
        )
    content = messages[-1].content
    if isinstance(content, list):
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    r.baseline_answer = str(content)
    line = next(
        (ln for ln in r.baseline_answer.splitlines()[::-1] if "root cause" in ln.lower()),
        r.baseline_answer,
    )
    r.baseline_hit = any(re.search(k, line, re.I) for k in s.keywords)


async def run_k8sgpt(s: Scenario, r: Result, binary: str) -> None:
    """k8sgpt's built-in analyzers (no AI backend): what a popular existing tool reports.

    k8sgpt lists problems per object and doesn't rank causes, so the grading is
    lenient: a hit when ANY finding mentions the root cause (same keywords as
    the baseline). It is a symptom finder, not RCA — the comparison shows what
    the ranking and the change events add on top.
    """
    proc = await asyncio.create_subprocess_exec(
        binary, "analyze", "--namespace", lab.NAMESPACE, "--output", "json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    out, _ = await proc.communicate()
    data = json.loads(out.decode() or "{}")
    for item in data.get("results") or []:
        texts = "; ".join(e.get("Text", "") for e in item.get("error") or [])
        r.k8sgpt_findings.append(f"{item.get('kind')} {item.get('name')}: {texts}"[:300])
    blob = "\n".join(r.k8sgpt_findings)
    r.k8sgpt_hit = any(re.search(k, blob, re.I) for k in s.keywords)


async def run_scenario(s: Scenario, args: argparse.Namespace) -> Result:
    r = Result(s.id, s.title, f"{'/'.join(sorted(s.expect_types))} on {s.expect_entity}")
    print(f"\n=== {s.id}: {s.title}")
    try:
        await lab.cleanup()
        since = datetime.now(UTC)
        if s.setup:
            from rca_eval.scenarios import manifest

            await lab.apply(manifest(*s.setup))
            for d in s.ready:
                await lab.wait_ready(d)
        print("  healthy; injecting the fault")
        await s.fault()
        print(f"  waiting {s.wait_seconds}s for symptoms")
        await asyncio.sleep(s.wait_seconds)
        if args.k8sgpt:
            await run_k8sgpt(s, r, args.k8sgpt)
            print(f"  k8sgpt hit={r.k8sgpt_hit} findings={len(r.k8sgpt_findings)}")
        await run_rca(
            s,
            since,
            r,
            args.provider,
            args.model,
            with_report=not args.no_report,
            feedback=args.feedback,
        )
        print(f"  RCA: hit@{r.rca_hit_rank} ai_hit={r.ai_hit} ranked={r.rca_ranked}")
        if not args.no_baseline:
            await run_baseline(s, r, args.provider, args.model)
            print(f"  baseline hit={r.baseline_hit}")
    except Exception as exc:  # one broken scenario must not stop the others
        r.error = f"{type(exc).__name__}: {exc}"
        print("  ERROR", r.error)
    finally:
        if not args.keep:
            await lab.cleanup()
    return r


def summarize(results: list[Result], args: argparse.Namespace) -> str:
    n = len(results) or 1

    def rate(xs: list[bool | None]) -> str:
        return (
            f"{sum(1 for x in xs if x)}/{len(results)} ({100 * sum(1 for x in xs if x) / n:.0f}%)"
        )

    top3 = [r.rca_hit_rank is not None and r.rca_hit_rank <= 3 for r in results]
    ai_rate = "—" if args.no_report else rate([r.ai_hit for r in results])
    lines = [
        f"# RCA evaluation — {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        f"Provider/model: {args.provider or 'default'} / {args.model or 'default'}. "
        "Scenarios: backend/rca_eval/scenarios.py. Namespace: rca-lab on lab1.",
        "",
        "| Metric | K8s-Hub RCA | LLM agent + tools | k8sgpt analyzers |",
        "|---|---|---|---|",
        f"| Top-1 | {rate([r.rca_hit_rank == 1 for r in results])} | "
        f"{rate([r.baseline_hit for r in results]) if not args.no_baseline else '—'} | "
        f"{rate([r.k8sgpt_hit for r in results]) + ' (any finding)' if args.k8sgpt else '—'} |",
        f"| Top-3 | {rate(top3)} | — | — |",
        f"| AI-chosen root cause | {ai_rate} | — | — |",
        f"| Mean time (s) | {sum(r.rca_seconds for r in results) / n:.1f} deterministic + "
        f"{sum(r.report_seconds for r in results) / n:.1f} report | "
        f"{sum(r.baseline_seconds for r in results) / n:.1f} | < 2 |",
        f"| Mean tokens | {sum(r.rca_tokens for r in results) / n:.0f} | "
        f"{sum(r.baseline_tokens for r in results) / n:.0f} | 0 |",
        "",
        "| Scenario | Expected | RCA rank of truth | AI root ok | Agent ok | k8sgpt ok | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.scenario} | {r.expected} | {r.rca_hit_rank or 'miss'} | {r.ai_hit} | "
            f"{r.baseline_hit} | {r.k8sgpt_hit} | {r.error or ''} |"
        )
    return "\n".join(lines) + "\n"


def limit_llm_rate(rpm: float) -> None:
    """One shared client-side limiter for every model call of the run (report + baseline).

    Free tiers count requests per minute; an agent loop fires several in a few
    seconds and the provider answers 429 mid-investigation. Waiting before each
    call is slower but keeps the comparison complete.
    """
    from langchain_core.rate_limiters import InMemoryRateLimiter

    from app.integrations.llm import client
    from app.modules.nl_command import agent
    from app.modules.rca import report

    limiter = InMemoryRateLimiter(
        requests_per_second=rpm / 60, check_every_n_seconds=0.5, max_bucket_size=1
    )

    def limited(**kw: Any) -> Any:
        return client.get_llm(**kw, rate_limiter=limiter)

    agent.get_llm = limited  # type: ignore[assignment]
    report.get_llm = limited  # type: ignore[assignment]


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--only", help="comma-separated scenario ids: " + ", ".join(BY_ID))
    parser.add_argument("--no-baseline", action="store_true", help="skip the LLM-only baseline")
    parser.add_argument(
        "--no-report", action="store_true", help="skip the AI report (ranking only, no LLM)"
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="record each scenario's ground truth as feedback (trains rca_weights)",
    )
    parser.add_argument("--keep", action="store_true", help="leave the last fault in place")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--k8sgpt", help="path to the k8sgpt binary, to compare with its analyzers")
    parser.add_argument(
        "--rpm", type=float, help="cap LLM requests per minute (free tiers: Gemini allows 5)"
    )
    args = parser.parse_args()
    if args.rpm:
        limit_llm_rate(args.rpm)

    chosen = [BY_ID[x] for x in args.only.split(",")] if args.only else SCENARIOS
    await lab.ensure_namespace()
    results = [await run_scenario(s, args) for s in chosen]

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (RESULTS / f"{stamp}.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report_md = summarize(results, args)
    (RESULTS / f"{stamp}.md").write_text(report_md, encoding="utf-8")
    print("\n" + report_md)
    print(f"Saved rca_eval/results/{stamp}.md and .json")


if __name__ == "__main__":
    asyncio.run(main())
