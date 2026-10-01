"""RCA data survives a database round trip with its parent-child links."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.rca_report import RcaEvidence, RcaHypothesis, RcaRun


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_test(element, compiler, **kwargs):
    return "JSON"


def test_rca_run_evidence_and_hypothesis_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[RcaRun.__table__, RcaEvidence.__table__, RcaHypothesis.__table__],
    )
    evidence_id = uuid4()

    with Session(engine) as session:
        run = RcaRun(target_kind="Deployment", target_name="api", namespace="default")
        run.evidence.append(
            RcaEvidence(
                id=evidence_id,
                source="event",
                data={"reason": "OOMKilled"},
                ts=datetime(2026, 10, 1, tzinfo=UTC),
            )
        )
        run.hypotheses.append(
            RcaHypothesis(
                rank=1,
                title="Memory limit too low",
                confidence=0.9,
                evidence_ids=[str(evidence_id)],
            )
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()

    with Session(engine) as session:
        saved_run = session.get(RcaRun, run_id)
        saved_evidence = session.scalar(select(RcaEvidence).where(RcaEvidence.run_id == run_id))
        saved_hypothesis = session.scalar(
            select(RcaHypothesis).where(RcaHypothesis.run_id == run_id)
        )

        assert saved_run is not None
        assert saved_run.status == "pending"
        assert saved_run.target_name == "api"
        assert saved_evidence is not None
        assert saved_evidence.data == {"reason": "OOMKilled"}
        assert saved_hypothesis is not None
        assert saved_hypothesis.evidence_ids == [str(evidence_id)]
