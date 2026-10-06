"""Score model predictions by executing them.

Exactly the same verifier that graded the hand-written references and baselines is
used here. That is the point: the model is held to the identical standard as
`sqlglot`, `ora2pg` and the reference translations, with the same comparison
rules, the same timeouts and the same treatment of statements that cannot be
value-compared. A metric that applied different rules to different systems would
not be a comparison.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orashift.config import Settings
from orashift.db import oracle, postgres
from orashift.logging import get_logger
from orashift.units import store
from orashift.units.types import Unit
from orashift.verify.run import DEFAULT_TIMEOUT_MS, POSTGRES_TIMEOUT_MS, verify_one

log = get_logger(__name__)

RESULTS_DIR = Path("results")

PREDICTION_FILES = {
    "base": RESULTS_DIR / "predictions_base.jsonl",
    "finetuned": RESULTS_DIR / "predictions_finetuned.jsonl",
}


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    model: str
    scored: int
    verified: int
    ran: int

    @property
    def execution_accuracy(self) -> float:
        return self.verified / self.scored if self.scored else 0.0

    @property
    def runs_without_error(self) -> float:
        return self.ran / self.scored if self.scored else 0.0


def load_predictions(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Run notebooks/predict.ipynb and fetch its output:\n"
            "  python scripts/kaggle_run.py push --kernel predict --wait"
        )
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score_model(
    settings: Settings,
    model: str,
    predictions: list[dict[str, object]],
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    resume: bool = True,
    limit: int | None = None,
) -> ScoreSummary:
    """Execute every prediction and record whether it matched Oracle."""
    with store.connect(db_path) as conn:
        units: dict[str, Unit] = {u.unit_key: u for u in store.all_units(conn)}
        already = store.scored_keys(conn, model) if resume else set()

        todo = [p for p in predictions if str(p["unit_key"]) not in already]
        if limit is not None:
            todo = todo[:limit]

        log.info(
            "scoring_started", model=model, todo=len(todo), skipped=len(predictions) - len(todo)
        )

        if todo:
            with (
                oracle.connect(settings) as ora_conn,
                postgres.connect(settings, autocommit=False) as pg_conn,
            ):
                ora_conn.call_timeout = DEFAULT_TIMEOUT_MS
                with pg_conn.cursor() as cursor:
                    cursor.execute(f"SET statement_timeout = {POSTGRES_TIMEOUT_MS}")
                pg_conn.commit()

                for index, prediction in enumerate(todo, start=1):
                    unit_key = str(prediction["unit_key"])
                    unit = units.get(unit_key)
                    if unit is None:
                        # A prediction for a unit no longer in the pool: record it
                        # as a failure rather than dropping it, so counts still add up.
                        store.record_score(
                            conn,
                            model,
                            unit_key,
                            str(prediction["split"]),
                            prediction=str(prediction.get("prediction") or ""),
                            ok=False,
                            ran=False,
                            reason="unit not found in the pool",
                        )
                        continue

                    candidate = str(prediction.get("prediction") or "").strip()
                    if not candidate:
                        store.record_score(
                            conn,
                            model,
                            unit_key,
                            str(prediction["split"]),
                            prediction="",
                            ok=False,
                            ran=False,
                            reason="empty prediction",
                        )
                        continue

                    outcome = verify_one(ora_conn, pg_conn, unit, candidate)
                    store.record_score(
                        conn,
                        model,
                        unit_key,
                        str(prediction["split"]),
                        prediction=candidate,
                        ok=outcome.ok,
                        ran=outcome.ran_on_postgres,
                        reason=outcome.reason,
                        detail=outcome.detail,
                        duration_ms=outcome.duration_ms,
                    )

                    if index % 50 == 0:
                        conn.commit()
                        log.info("scoring_progress", model=model, done=index, total=len(todo))

        keys = {str(p["unit_key"]) for p in predictions}
        rows = [r for r in store.score_rows(conn) if r["model"] == model and r["unit_key"] in keys]

    return ScoreSummary(
        model=model,
        scored=len(rows),
        verified=sum(1 for r in rows if r["ok"]),
        ran=sum(1 for r in rows if r["ran"]),
    )


def score_all(
    settings: Settings,
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    resume: bool = True,
    limit: int | None = None,
) -> dict[str, ScoreSummary]:
    summaries: dict[str, ScoreSummary] = {}
    for model, path in PREDICTION_FILES.items():
        predictions = load_predictions(path)
        summaries[model] = score_model(
            settings, model, predictions, db_path=db_path, resume=resume, limit=limit
        )
    return summaries
