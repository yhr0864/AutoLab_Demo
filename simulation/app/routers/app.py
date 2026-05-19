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
    一次性完成：
    1. OR-Tools 求最优排程
    2. SimPy 加随机扰动仿真
    """
    schedule = solve_job_shop(OptimizeRequest(jobs=req.jobs))

    simulation_result = simulate_schedule(
        SimulateRequest(
            schedule=schedule,
            config=req.config,
        )
    )

    return {
        "schedule": schedule,
        "simulation": simulation_result,
    }


@app.get("/demo/pipeline")
def demo_pipeline(seed: int = 42):
    """
    使用内置示例数据：
    1. OR-Tools 求排程
    2. SimPy 加随机扰动仿真
    """
    jobs = default_jobs()

    schedule = solve_job_shop(OptimizeRequest(jobs=jobs))

    simulation_result = simulate_schedule(
        SimulateRequest(
            schedule=schedule,
            config=SimulationConfig(seed=seed),
        )
    )

    return {
        "schedule": schedule,
        "simulation": simulation_result,
    }
