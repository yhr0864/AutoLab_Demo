from fastapi import APIRouter

from app.data_demo.demo_jobs import default_jobs
from app.services.optimizer import solve_job_shop
from app.services.simulator import simulate_schedule
from app.models.schemas import (
    ScheduleResponse,
    OptimizeRequest,
    SimulateRequest,
    SimulationConfig,
    PipelineRequest,
)

# ======================================================
# FastAPI 接口
# ======================================================


def run_pipeline(jobs, config):
    """
    公共流程：
    1. OR-Tools 求最优排程
    2. SimPy 加随机扰动仿真
    """
    schedule = solve_job_shop(OptimizeRequest(jobs=jobs))

    simulation_result = simulate_schedule(
        SimulateRequest(
            schedule=schedule,
            config=config,
        )
    )

    return {
        "schedule": schedule,
        "simulation": simulation_result,
    }


app = APIRouter()


@app.get("/demo/jobs")
def get_demo_jobs():
    return {"jobs": default_jobs()}


@app.post("/optimize", response_model=ScheduleResponse)
def optimize(req: OptimizeRequest):
    """
    使用 OR-Tools 求解 Job Shop 最优排程。
    """
    return solve_job_shop(req)


@app.post("/simulate")
def simulate(req: SimulateRequest):
    """
    使用 SimPy 对已有排程加入随机扰动进行仿真。
    """
    return simulate_schedule(req)


@app.post("/pipeline")
def pipeline(req: PipelineRequest):
    """
    正式接口：使用用户提交的 jobs 和 config。
    """
    return run_pipeline(req.jobs, req.config)


@app.get("/demo/pipeline")
def demo_pipeline(seed: int = 42):
    """
    Demo接口: 使用内置示例 jobs, 只允许通过 seed 改变随机结果。
    """
    return run_pipeline(default_jobs(), SimulationConfig(seed=seed))
