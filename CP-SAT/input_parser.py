import json
from pathlib import Path
from typing import Dict, List, Tuple, Union

from models_base import Task, ScheduleRequest, Device


def parse_input(
    source: Union[str, Path, dict],
    base_ts: int = 0,
    horizon_s: int = 1800,
) -> Tuple[ScheduleRequest, List[Device], dict, str, Dict[str, int]]:
    """
    Returns
    -------
    (ScheduleRequest, devices, options, batch_id, task_operations)
    """
    data = _load(source)

    batch_id: str = data.get("batch_id", "")

    # ── 1. 设备 ──
    devices = [Device.from_json(d, base_ts=base_ts) for d in data.get("devices", [])]
    dev_duration: Dict[str, int] = {d.device_id: d.duration_s for d in devices}

    # ── 2. 任务 ──
    tasks: List[Task] = []
    precedence_pairs: List[Tuple[str, str]] = []
    priority_weights: Dict[str, float] = {}
    task_operations: Dict[str, int] = {}

    for t in data.get("tasks", []):
        tid = t["task_id"]
        eligible: Dict[str, List[str]] = t.get("eligible_devices", {})
        operations: int = t.get("operations", 1)
        earliest_start_s: int = t.get("earliest_start_s", 0)
        deadline_s = t.get("deadline_s", None)
        task_operations[tid] = operations

        # 每种能力需求量为 1
        required_caps: Dict[str, int] = {cap: 1 for cap in eligible.keys()}

        # 任务时长 = operations × 白名单内设备单操作时长（取最大，保守）
        per_op_s = 0
        for cap, dev_ids in eligible.items():
            for did in dev_ids:
                per_op_s = max(per_op_s, dev_duration.get(did, 0))
        duration_s = max(1, operations * per_op_s)

        tasks.append(
            Task(
                id=tid,
                duration_s=duration_s,
                required_capabilities=required_caps,
                eligible_devices=eligible,
                earliest_start_s=earliest_start_s,
                deadline_s=deadline_s,
            )
        )

        for pred in t.get("depends_on", []):
            precedence_pairs.append((pred, tid))

        priority_weights[tid] = float(t.get("priority", 1))

    request = ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        horizon_s=horizon_s,
        priority_weights=priority_weights,
    )

    options = data.get("options", {})
    return request, devices, options, batch_id, task_operations


def _load(source: Union[str, Path, dict]) -> dict:
    if isinstance(source, dict):
        return source
    if isinstance(source, (str, Path)) and Path(source).exists():
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(source)


if __name__ == "__main__":
    req, devices, opts, bid, ops = parse_input("input.json")
    print(req)
