"""RCA evaluation: inject labelled faults into the `rca-lab` namespace, diagnose, score top-k.

    cd backend && PYTHONUTF8=1 .venv/Scripts/python.exe -m rca_eval.run --help

Writes to the cluster (only in rca-lab) — run it on purpose, never from CI.
See docs/ke-hoach/rca-groot.md §3.10 and deploy/rca-lab/base.yaml.
"""
