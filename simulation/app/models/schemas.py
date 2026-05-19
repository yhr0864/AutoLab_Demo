from pydantic import BaseModel, Field
from typing import Dict, List, Optional

# ======================================================
# API 数据模型
# ======================================================


class OperationInput(BaseModel):
    machine_id: int
    duration: float


class JobInput(BaseModel):
    job_id: int
    operations: List[OperationInput]


class OptimizeRequest(BaseModel):
    jobs: List[JobInput]


class OperationSchedule(BaseModel):
    job_id: int
    op_id: int
    machine_id: int
    duration: float
    start: float
    end: float


class ScheduleResponse(BaseModel):
    makespan: float
    jobs: Dict[int, List[OperationSchedule]]
    machines: Dict[int, List[OperationSchedule]]


class SimulationConfig(BaseModel):
    seed: int = 42

    # 加工时间随机波动系数范围
    process_factor_min: float = 0.90
    process_factor_mode: float = 1.03
    process_factor_max: float = 1.25

    # 初始释放延迟
    release_delay_probability: float = 0.15
    release_delay_min: float = 0.10
    release_delay_max: float = 0.50

    # 换型/准备延迟
    setup_delay_probability: float = 0.20
    setup_delay_min: float = 0.05
    setup_delay_max: float = 0.30

    # 搬运延迟
    transfer_small_probability: float = 0.70
    transfer_medium_probability: float = 0.25
    transfer_large_probability: float = 0.05

    # 机器随机故障参数，平均故障间隔，单位小时
    mtbf_machine_0: float = 12.0
    mtbf_machine_1: float = 10.0
    mtbf_machine_2: float = 11.0

    # 维修时间三角分布
    repair_min: float = 0.15
    repair_mode: float = 0.40
    repair_max: float = 1.20


class SimulateRequest(BaseModel):
    schedule: ScheduleResponse
    config: SimulationConfig = Field(default_factory=SimulationConfig)


class PipelineRequest(BaseModel):
    jobs: List[JobInput]
    config: SimulationConfig = Field(default_factory=SimulationConfig)
