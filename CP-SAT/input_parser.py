"""
解析新版输入 JSON，拆分为：
  - ScheduleRequest（调度层输入）
  - List[Device]    （分配层 + 容量统计输入）
  - options dict     （timeout/权重等配置）

字段映射：
  depends_on        -> precedence_pairs
  eligible_devices  -> Task.eligible_devices + required_capabilities
  operations        -> duration_ms = operations × 设备单操作时长
  priority          -> priority_weights
  options.*         -> solver 参数
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple, Union

from models_base import Task, ScheduleRequest, Device


def parse_input(
    source: Union[str, Path, dict],
    base_ts: int = 0,
    horizon_ms: int = 1_800_000,
) -> Tuple[ScheduleRequest, List[Device], dict]:
    """
    Returns
    -------
    (ScheduleRequest, devices, options)
    """
    data = _load(source)

    # ── 1. 设备 ──
    devices = [Device.from_json(d, base_ts=base_ts) for d in data.get("devices", [])]
    dev_duration: Dict[str, int] = {d.device_id: d.duration_ms for d in devices}

    # ── 2. 任务 ──
    tasks: List[Task] = []
    precedence_pairs: List[Tuple[str, str]] = []
    priority_weights: Dict[str, float] = {}

    for t in data.get("tasks", []):
        tid = t["task_id"]
        eligible: Dict[str, List[str]] = t.get("eligible_devices", {})
        operations: int = t.get("operations", 1)

        # 每种能力需求量为 1
        required_caps: Dict[str, int] = {cap: 1 for cap in eligible.keys()}

        # 任务时长 = operations × 白名单内设备单操作时长（取最大，保守）
        per_op_ms = 0
        for cap, dev_ids in eligible.items():
            for did in dev_ids:
                per_op_ms = max(per_op_ms, dev_duration.get(did, 0))
        duration_ms = max(1, operations * per_op_ms)

        tasks.append(
            Task(
                id=tid,
                duration_ms=duration_ms,
                required_capabilities=required_caps,
                eligible_devices=eligible,
            )
        )

        for pred in t.get("depends_on", []):
            precedence_pairs.append((pred, tid))

        priority_weights[tid] = float(t.get("priority", 1))

    request = ScheduleRequest(
        tasks=tasks,
        precedence_pairs=precedence_pairs,
        resources=[],  # ✅ 不再用，容量由 eligible_devices 推导
        horizon_ms=horizon_ms,
        priority_weights=priority_weights,
    )

    options = data.get("options", {})
    return request, devices, options


def _load(source: Union[str, Path, dict]) -> dict:
    if isinstance(source, dict):
        return source
    if isinstance(source, (str, Path)) and Path(source).exists():
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(source)


if __name__ == "__main__":
    json.loads("input.json")
