import random
import simpy
from typing import List

from app.models.schemas import OperationSchedule, SimulationConfig, SimulateRequest
from app.services.disturbance import (
    generate_random_downtimes,
    sample_process_factor,
    sample_release_delay,
    sample_setup_delay,
    sample_transfer_delay,
    machine_work_with_downtime,
)

# ======================================================
# SimPy：执行排程仿真
# ======================================================


def job_process(
    env: simpy.Environment,
    job_id: int,
    operations: List[OperationSchedule],
    machines,
    event_log: List[dict],
    downtimes,
    rng: random.Random,
    cfg: SimulationConfig,
):
    release_delay = sample_release_delay(rng, cfg)

    if release_delay > 0:
        yield env.timeout(release_delay)

    for index, op in enumerate(operations):

        # 如果工件提前完成上一道工序，则等待到计划开始时间
        if env.now < op.start:
            yield env.timeout(op.start - env.now)

        job_ready_time = env.now

        with machines[op.machine_id].request(priority=op.start) as req:
            yield req

            machine_acquired_time = env.now
            machine_wait = machine_acquired_time - job_ready_time

            # 随机准备/换型时间
            setup_delay = sample_setup_delay(rng, cfg)

            if setup_delay > 0:
                yield env.process(
                    machine_work_with_downtime(
                        env=env,
                        machine_id=op.machine_id,
                        work_time=setup_delay,
                        downtimes=downtimes,
                    )
                )

            actual_start = env.now

            # 随机加工时间
            process_factor = sample_process_factor(rng, cfg)
            actual_process_time = op.duration * process_factor

            yield env.process(
                machine_work_with_downtime(
                    env=env,
                    machine_id=op.machine_id,
                    work_time=actual_process_time,
                    downtimes=downtimes,
                )
            )

            actual_end = env.now

            event_log.append(
                {
                    "job_id": job_id,
                    "op_id": op.op_id,
                    "machine_id": op.machine_id,
                    "planned_start": op.start,
                    "planned_end": op.end,
                    "planned_duration": op.duration,
                    "release_delay": release_delay if index == 0 else 0.0,
                    "job_ready_time": job_ready_time,
                    "machine_acquired_time": machine_acquired_time,
                    "machine_wait": machine_wait,
                    "setup_delay": setup_delay,
                    "process_factor": process_factor,
                    "actual_process_time": actual_process_time,
                    "actual_start": actual_start,
                    "actual_end": actual_end,
                    "start_delay": actual_start - op.start,
                    "finish_delay": actual_end - op.end,
                    "machine_occupied_time": actual_end - machine_acquired_time,
                }
            )

        # 随机搬运延迟
        if index < len(operations) - 1:
            transfer_delay = sample_transfer_delay(rng, cfg)
            yield env.timeout(transfer_delay)


def simulate_schedule(req: SimulateRequest):
    schedule = req.schedule
    cfg = req.config

    rng = random.Random(cfg.seed)

    env = simpy.Environment()

    machine_ids = sorted(schedule.machines.keys())

    machines = {
        machine_id: simpy.PriorityResource(env, capacity=1)
        for machine_id in machine_ids
    }

    # 随机生成机器故障窗口
    horizon = schedule.makespan + 15.0

    downtimes = generate_random_downtimes(
        rng=rng,
        cfg=cfg,
        machine_ids=machine_ids,
        horizon=horizon,
    )

    event_log = []

    for job_id, operations in schedule.jobs.items():
        env.process(
            job_process(
                env=env,
                job_id=job_id,
                operations=operations,
                machines=machines,
                event_log=event_log,
                downtimes=downtimes,
                rng=rng,
                cfg=cfg,
            )
        )

    env.run()

    actual_makespan = max(e["actual_end"] for e in event_log)

    machine_summary = {}

    for machine_id in machine_ids:
        events = [e for e in event_log if e["machine_id"] == machine_id]

        occupied_time = sum(e["machine_occupied_time"] for e in events)
        productive_time = sum(e["actual_process_time"] for e in events)
        setup_time = sum(e["setup_delay"] for e in events)
        wait_time = sum(e["machine_wait"] for e in events)

        machine_summary[machine_id] = {
            "occupied_time": occupied_time,
            "productive_time": productive_time,
            "setup_time": setup_time,
            "machine_wait_time": wait_time,
            "occupied_rate": occupied_time / actual_makespan,
            "productive_rate": productive_time / actual_makespan,
        }

    return {
        "seed": cfg.seed,
        "planned_makespan": schedule.makespan,
        "actual_makespan": actual_makespan,
        "makespan_delay": actual_makespan - schedule.makespan,
        "downtimes": {
            machine_id: [
                {
                    "start": start,
                    "end": end,
                    "repair_time": end - start,
                }
                for start, end in windows
            ]
            for machine_id, windows in downtimes.items()
        },
        "events": sorted(event_log, key=lambda x: (x["actual_start"], x["machine_id"])),
        "machine_summary": machine_summary,
    }
