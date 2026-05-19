from typing import Dict, List, Optional
from app.models.schemas import JobInput, OperationInput

# ======================================================
# 默认 Job Shop 数据
# ======================================================


def default_jobs() -> List[JobInput]:
    return [
        JobInput(
            job_id=0,
            operations=[
                OperationInput(machine_id=0, duration=3),
                OperationInput(machine_id=1, duration=2),
                OperationInput(machine_id=2, duration=2),
            ],
        ),
        JobInput(
            job_id=1,
            operations=[
                OperationInput(machine_id=0, duration=2),
                OperationInput(machine_id=2, duration=1),
                OperationInput(machine_id=1, duration=4),
            ],
        ),
        JobInput(
            job_id=2,
            operations=[
                OperationInput(machine_id=1, duration=4),
                OperationInput(machine_id=2, duration=3),
            ],
        ),
    ]
