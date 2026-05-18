# DAG dict → RCPSPModel
# ──────────────────────────────────────────────────────────────

from collections import defaultdict
from .models import TaskModel, RCPSPModel


def parse(dag: dict) -> RCPSPModel:
    """
    将上层传入的 DAG dict 转换为 CP-SAT 建模直接可用的 RCPSPModel。

    Parameters
    ----------
    dag : dict
        必须包含 "resources"、"tasks"、"edges" 三个键。

    Returns
    -------
    RCPSPModel

    Raises
    ------
    ValueError
        字段缺失 / 未知资源引用 / 需求超容量 / 存在环路。
    """

    # ── 顶层字段校验 ─────────────────────────────────────────
    for key in ("resources", "tasks", "edges"):
        if key not in dag:
            raise ValueError(f"DAG 缺少必要字段: '{key}'")

    raw_resources = dag["resources"]
    raw_tasks = dag["tasks"]
    raw_edges = dag["edges"]

    # ── 1. 资源容量 ──────────────────────────────────────────
    resource_capacities: dict = {}
    for res, cap in raw_resources.items():
        if not isinstance(cap, int) or cap <= 0:
            raise ValueError(f"资源 '{res}' 容量须为正整数，当前: {cap}")
        resource_capacities[res] = cap

    # ── 2. 任务 ──────────────────────────────────────────────
    tasks: list = []
    task_map: dict = {}

    for name, info in raw_tasks.items():
        for field in ("duration", "resources"):
            if field not in info:
                raise ValueError(f"任务 '{name}' 缺少字段 '{field}'")

        dur = info["duration"]
        if not isinstance(dur, int) or dur <= 0:
            raise ValueError(f"任务 '{name}' duration 须为正整数，当前: {dur}")

        demands: dict = {}
        for res, demand in info["resources"].items():
            if res not in resource_capacities:
                raise ValueError(f"任务 '{name}' 引用未定义资源 '{res}'")
            if not isinstance(demand, int) or demand <= 0:
                raise ValueError(f"任务 '{name}' 对 '{res}' 需求须为正整数")
            if demand > resource_capacities[res]:
                raise ValueError(
                    f"任务 '{name}' 对 '{res}' 需求({demand}) 超过容量({resource_capacities[res]})"
                )
            demands[res] = demand

        task = TaskModel(name=name, duration=dur, resource_demands=demands)
        tasks.append(task)
        task_map[name] = task

    # ── 3. 前序关系 ──────────────────────────────────────────
    precedences: list = []
    successors: dict = defaultdict(list)
    predecessors: dict = defaultdict(list)

    for edge in raw_edges:
        if len(edge) != 2:
            raise ValueError(f"边格式错误（应为二元组）: {edge}")
        pred, succ = edge
        for n in (pred, succ):
            if n not in task_map:
                raise ValueError(f"边 {edge} 中任务 '{n}' 未定义")
        if pred == succ:
            raise ValueError(f"任务 '{pred}' 存在自环")

        precedences.append((pred, succ))
        successors[pred].append(succ)
        predecessors[succ].append(pred)

    # ── 4. 环路检测 ──────────────────────────────────────────
    _check_no_cycle(task_map, successors)

    # ── 5. 资源-任务索引 ─────────────────────────────────────
    resource_tasks: dict = defaultdict(list)
    for task in tasks:
        for res in task.resource_demands:
            resource_tasks[res].append(task.name)

    # ── 6. 时间上界 ──────────────────────────────────────────
    horizon = sum(t.duration for t in tasks)

    return RCPSPModel(
        tasks=tasks,
        precedences=precedences,
        resource_capacities=resource_capacities,
        horizon=horizon,
        task_map=dict(task_map),
        successors=dict(successors),
        predecessors=dict(predecessors),
        resource_tasks=dict(resource_tasks),
    )


def _check_no_cycle(task_map: dict, successors: dict) -> None:
    in_degree = {n: 0 for n in task_map}
    for preds in successors.values():
        for s in preds:
            in_degree[s] += 1

    queue = [n for n, d in in_degree.items() if d == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for s in successors.get(node, []):
            in_degree[s] -= 1
            if in_degree[s] == 0:
                queue.append(s)

    if visited != len(task_map):
        raise ValueError("DAG 中存在环路")


if __name__ == "__main__":
    pass
