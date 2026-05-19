import random
import simpy
from typing import Dict, List, Tuple

from app.models.schemas import SimulationConfig

# ======================================================
# SimPy：随机扰动函数
# ======================================================


def sample_process_factor(rng: random.Random, cfg: SimulationConfig) -> float:
    return rng.triangular(
        cfg.process_factor_min,
        cfg.process_factor_max,
        cfg.process_factor_mode,
    )


def sample_release_delay(rng: random.Random, cfg: SimulationConfig) -> float:
    if rng.random() < cfg.release_delay_probability:
        return rng.uniform(cfg.release_delay_min, cfg.release_delay_max)
    return 0.0


def sample_setup_delay(rng: random.Random, cfg: SimulationConfig) -> float:
    if rng.random() < cfg.setup_delay_probability:
        return rng.uniform(cfg.setup_delay_min, cfg.setup_delay_max)
    return 0.0


def sample_transfer_delay(rng: random.Random, cfg: SimulationConfig) -> float:
    p = rng.random()

    if p < cfg.transfer_small_probability:
        return rng.uniform(0.00, 0.15)
    elif p < cfg.transfer_small_probability + cfg.transfer_medium_probability:
        return rng.uniform(0.15, 0.50)
    else:
        return rng.uniform(0.50, 1.00)


def sample_repair_time(rng: random.Random, cfg: SimulationConfig) -> float:
    return rng.triangular(
        cfg.repair_min,
        cfg.repair_max,
        cfg.repair_mode,
    )


def generate_random_downtimes(
    rng: random.Random,
    cfg: SimulationConfig,
    machine_ids: List[int],
    horizon: float,
):
    mtbf_map = {
        0: cfg.mtbf_machine_0,
        1: cfg.mtbf_machine_1,
        2: cfg.mtbf_machine_2,
    }

    downtimes = {}

    for machine_id in machine_ids:
        mtbf = mtbf_map.get(machine_id, 12.0)

        t = 0.0
        windows = []

        while t < horizon:
            time_to_failure = rng.expovariate(1.0 / mtbf)
            failure_start = t + time_to_failure

            if failure_start >= horizon:
                break

            repair_time = sample_repair_time(rng, cfg)
            failure_end = failure_start + repair_time

            windows.append((failure_start, failure_end))

            t = failure_end

        downtimes[machine_id] = windows

    return downtimes


def get_current_downtime(now: float, windows):
    for start, end in windows:
        if start <= now < end:
            return start, end
    return None


def get_next_downtime(now: float, windows):
    future = [(s, e) for s, e in windows if s > now]

    if not future:
        return None

    return min(future, key=lambda x: x[0])


def machine_work_with_downtime(
    env: simpy.Environment,
    machine_id: int,
    work_time: float,
    downtimes,
):
    remaining = work_time
    windows = sorted(downtimes.get(machine_id, []))

    while remaining > 1e-9:
        now = env.now

        current_down = get_current_downtime(now, windows)

        if current_down is not None:
            _, down_end = current_down
            yield env.timeout(down_end - now)
            continue

        next_down = get_next_downtime(now, windows)

        if next_down is None:
            yield env.timeout(remaining)
            remaining = 0.0
            break

        down_start, down_end = next_down
        time_until_down = down_start - env.now

        if remaining <= time_until_down:
            yield env.timeout(remaining)
            remaining = 0.0
        else:
            if time_until_down > 0:
                yield env.timeout(time_until_down)
                remaining -= time_until_down

            yield env.timeout(down_end - env.now)
