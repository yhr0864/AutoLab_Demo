import json
import logging
from input_parser import parse_input
from solver import CpSatSolver
from device_allocator import GreedyDeviceAllocator

logging.basicConfig(level=logging.WARNING)

BASE_TS = 1751961600

# ① 解析输入
request, devices, options, batch_id, task_operations = parse_input(
    "input.json", base_ts=BASE_TS, horizon_s=36000
)

# ② 调度层
solver = CpSatSolver(options)
schedule_result = solver.solve(request, now_s=0)

# ③ 分配层
allocator = GreedyDeviceAllocator(devices=devices, tasks=request.tasks)
alloc_result = allocator.allocate(schedule_result)

# ④ 输出结果（与 output.json 一致的结构）
output = {
    "batch_id": batch_id,
    "status": schedule_result.status.lower(),
    "makespan": schedule_result.makespan_s,
    "solver": "cpsat",
    "message": schedule_result.message,
    "assignments": [
        {
            "task_id": a.task_id,
            "device_id": a.device_id,
            "start_ts": BASE_TS + a.planned_start_s,
            "end_ts": BASE_TS + a.planned_end_s,
            "operations": task_operations.get(a.task_id, 1),
        }
        for a in sorted(alloc_result.assignments, key=lambda x: x.planned_start_s)
    ],
}
print(json.dumps(output, indent=2, ensure_ascii=False))
