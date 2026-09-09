# Module: Root Cause Analysis

Pipeline: `trigger -> collect evidence -> correlate -> hypothesize -> rank -> report`

| File | Trach nhiem |
|---|---|
| `agent.py` | LangGraph graph dieu phoi RCA |
| `triggers.py` | Nguon kich hoat: user request / alert webhook / scheduled |
| `collectors/` | Thu thap evidence tu K8s, Prometheus, Loki |
| `analyzers/` | Detector theo trieu chung (CrashLoop, OOM, ImagePull...) |
| `correlator.py` | Ghep evidence theo timeline, tim thay doi gan nhat |
| `hypothesis.py` | LLM sinh + xep hang gia thuyet nguyen nhan |
| `reporter.py` | Dung report cuoi: timeline + evidence + de xuat fix |
