# metrics/reporter.py
from __future__ import annotations

from typing import Literal


class MetricsReporter:
    """
    纯静态报告格式化器。

    职责
    ────
    • 接收 to_dict() 返回的字典
    • 输出人类可读字符串
    • 与任何数据容器解耦，可独立测试
    """

    WIDTH = 55

    @staticmethod
    def render(
        data: dict,
        mode: Literal["sim", "real"] = "sim",
    ) -> str:
        w = MetricsReporter.WIDTH
        sep = "═" * w
        div = "─" * w

        lines = [
            f"\n{sep}",
            f"  {'仿真结果汇总' if mode == 'sim' else '真实运行结果汇总'}",
            f"{div}",
        ]

        # ── 任务完成 ──────────────────────────────────────────
        lines += [
            f"  总任务数           : {data['total_tasks']}",
            f"  完成任务数         : {data['completed_tasks']}",
            f"  完成率             : {data['completion_rate']:.1%}",
            f"  迁移任务数         : {data['migrated_tasks']}",
        ]

        # ── 设备 ──────────────────────────────────────────────
        lines += [
            f"{div}",
            f"  设备故障次数       : {data['fault_count']}",
            f"  设备恢复次数       : {data['recovery_count']}",
        ]

        # ★ 真实模式专有字段
        if mode == "real" and "hw_fail_count" in data:
            lines.append(f"  硬件通信失败次数   : {data['hw_fail_count']}")

        # ── 重规划 ────────────────────────────────────────────
        lines += [
            f"{div}",
            f"  触发重规划次数     : {data['reschedule_count']}",
            f"  平均重规划耗时     : {data['avg_reschedule_latency_ms']:.1f} ms",
        ]

        # ── 时间 ──────────────────────────────────────────────
        lines += [
            f"{div}",
            f"  总 Makespan        : {data['makespan_ms'] / 3_600_000:.2f} h",
            f"  平均完成偏差       : {data['avg_drift_ms'] / 3_600_000:.2f} h",
            f"  最大完成偏差       : {data['max_drift_ms'] / 3_600_000:.2f} h",
        ]

        # ★ 真实模式：挂钟耗时
        if mode == "real" and data.get("wall_elapsed_s") is not None:
            lines.append(f"  挂钟总耗时         : {data['wall_elapsed_s']:.1f} s")

        lines.append(f"{sep}")
        return "\n".join(lines)
