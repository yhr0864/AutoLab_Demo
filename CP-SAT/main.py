import json
import logging
from input_parser import parse_input
from solver import CpSatSolver

logging.basicConfig(level=logging.WARNING)

BASE_TS = 1751961600

# ① 解析输入
request, devices, options, batch_id, task_operations = parse_input(
    "input.json", base_ts=BASE_TS, horizon_s=36000
)

# ② 调度 + 分配（合并层，一次求解产出设备绑定）
solver = CpSatSolver(options)
schedule_result = solver.solve(request=request, devices=devices)

if schedule_result.unassigned:
    logging.warning("未能绑定设备的任务：%s", schedule_result.unassigned)

# ④ 输出结果（与 output.json 一致的结构）
output = {
    "batch_id": batch_id,
    "status": schedule_result.status.lower(),
    "makespan": schedule_result.makespan_s,
    "solver": "cpsat",
    "message": schedule_result.message,
    "unassigned": schedule_result.unassigned,
    "assignments": [
        {
            "task_id": a.task_id,
            "device_id": a.device_id,
            "start_ts": BASE_TS + a.planned_start_s,
            "end_ts": BASE_TS + a.planned_end_s,
            "operations": task_operations.get(a.task_id, 1),
        }
        for a in sorted(schedule_result.assignments, key=lambda x: x.planned_start_s)
    ],
}
print(json.dumps(output, indent=2, ensure_ascii=False))
