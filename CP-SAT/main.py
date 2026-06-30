import logging
from input_parser import parse_input
from solver import CpSatSolver
from device_allocator import GreedyDeviceAllocator

logging.basicConfig(level=logging.INFO)

BASE_TS = 1751961600

# ① 解析输入
request, devices, options = parse_input(
    "input.json", base_ts=BASE_TS, horizon_ms=1_800_000
)

# ② 调度层 —— 直接传 options ✅
solver = CpSatSolver(options)
schedule_result = solver.solve(request, now_ms=0)
print(
    f"调度状态: {schedule_result.status} " f"makespan={schedule_result.makespan_ms}ms"
)

# ③ 分配层
allocator = GreedyDeviceAllocator(devices=devices, tasks=request.tasks)
alloc_result = allocator.allocate(schedule_result)

print(f"\n分配状态: {alloc_result.status}")
for a in sorted(alloc_result.assignments, key=lambda x: x.planned_start_ms):
    print(
        f"  {a.task_id:14s} -> {a.device_id:14s} "
        f"[{a.planned_start_ms/1000:.0f}s, {a.planned_end_ms/1000:.0f}s]"
    )
if alloc_result.unassigned:
    print("未分配:", alloc_result.unassigned)
