# Module: Root Cause Analysis

Pipeline: `trigger -> collect evidence -> correlate -> hypothesize -> rank -> report`

| File | Responsibility |
|---|---|
| `agent.py` | LangGraph graph orchestrating RCA |
| `triggers.py` | Trigger sources: user request / alert webhook / scheduled |
| `collectors/` | Collect evidence from K8s, Prometheus, Loki |
| `analyzers/` | Symptom-based detectors (CrashLoop, OOM, ImagePull...) |
| `correlator.py` | Align evidence on a timeline, find the most recent change |
| `hypothesis.py` | LLM generates + ranks root-cause hypotheses |
| `reporter.py` | Build the final report: timeline + evidence + suggested fix |
