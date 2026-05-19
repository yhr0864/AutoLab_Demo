from typing import Dict, List
from ortools.sat.python import cp_model

from app.models.schemas import OptimizeRequest, OperationSchedule, ScheduleResponse

# ======================================================
# OR-Tools：求 Job Shop 最优排程
# ======================================================


def solve_job_shop(req: OptimizeRequest) -> ScheduleResponse:
    model = cp_model.CpModel()

    all_machines = sorted({op.machine_id for job in req.jobs for op in job.operations})

    horizon = int(sum(op.duration for job in req.jobs for op in job.operations))

    task_vars = {}
    machine_to_intervals = {m: [] for m in all_machines}

    for job in req.jobs:
        for op_id, op in enumerate(job.operations):
            suffix = f"j{job.job_id}_o{op_id}_m{op.machine_id}"

            duration = int(op.duration)

            start = model.new_int_var(0, horizon, f"start_{suffix}")
            end = model.new_int_var(0, horizon, f"end_{suffix}")
            interval = model.new_interval_var(
                start, duration, end, f"interval_{suffix}"
            )

            task_vars[(job.job_id, op_id)] = {
                "start": start,
                "end": end,
                "interval": interval,
                "machine_id": op.machine_id,
                "duration": duration,
            }

            machine_to_intervals[op.machine_id].append(interval)

    # 同一机器同一时间只能加工一个工序
    for machine_id in all_machines:
        model.add_no_overlap(machine_to_intervals[machine_id])

    # 同一工件的工序必须按顺序执行
    for job in req.jobs:
        for op_id in range(len(job.operations) - 1):
            current_task = task_vars[(job.job_id, op_id)]
            next_task = task_vars[(job.job_id, op_id + 1)]

            model.add(next_task["start"] >= current_task["end"])

    # Makespan
    makespan = model.new_int_var(0, horizon, "makespan")

    last_ends = []
    for job in req.jobs:
        last_op_id = len(job.operations) - 1
        last_ends.append(task_vars[(job.job_id, last_op_id)]["end"])

    model.add_max_equality(makespan, last_ends)
    model.minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10

    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        raise RuntimeError("No feasible schedule found")

    jobs_schedule: Dict[int, List[OperationSchedule]] = {}
    machines_schedule: Dict[int, List[OperationSchedule]] = {
        m: [] for m in all_machines
    }

    for job in req.jobs:
        job_ops = []

        for op_id, op in enumerate(job.operations):
            task = task_vars[(job.job_id, op_id)]

            start = float(solver.Value(task["start"]))
            end = float(solver.Value(task["end"]))

            item = OperationSchedule(
                job_id=job.job_id,
                op_id=op_id,
                machine_id=op.machine_id,
                duration=float(op.duration),
                start=start,
                end=end,
            )

            job_ops.append(item)
            machines_schedule[op.machine_id].append(item)

        jobs_schedule[job.job_id] = sorted(job_ops, key=lambda x: x.op_id)

    for machine_id in machines_schedule:
        machines_schedule[machine_id] = sorted(
            machines_schedule[machine_id], key=lambda x: x.start
        )

    return ScheduleResponse(
        makespan=float(solver.Value(makespan)),
        jobs=jobs_schedule,
        machines=machines_schedule,
    )
