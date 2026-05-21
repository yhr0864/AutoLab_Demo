class SchedulingInfeasibleError(Exception):
    """约束真正冲突，无论给多少时间都无解"""


class SchedulingInputError(ValueError):
    """输入数据校验失败"""


class SchedulingTimeoutNoSolution(Exception):
    """超时且无任何历史缓存，需上层决策"""
