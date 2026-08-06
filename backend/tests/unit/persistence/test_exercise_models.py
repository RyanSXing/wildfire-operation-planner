import subprocess
import sys


def test_exercise_models_register_idempotency_table_in_isolation() -> None:
    script = """
from wildfireops.persistence.base import Base
from wildfireops.persistence.exercise_models import ExercisePlanRunModel

assert ExercisePlanRunModel.__tablename__ == "exercise_plan_runs"
assert "idempotency_keys" in Base.metadata.tables
"""

    subprocess.check_call([sys.executable, "-c", script])
