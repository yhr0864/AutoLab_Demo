#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/subjects.py — NATS Subject 构建（参考 小车服务业务代码摘录 §4）

from .config import SchedulerConfig


# ---- 发布端精确 subject ----

def move_subject(cfg: SchedulerConfig) -> str:
    """构建 move subject（发布端）。

    bioflow.{tenant}.{env}.{lab}.device._.motor.control.move
    """
    return f"bioflow.{cfg.tenant}.{cfg.env}.{cfg.lab}.device._.motor.control.move"


def release_subject(cfg: SchedulerConfig) -> str:
    """构建 release subject（发布端）。

    bioflow.{tenant}.{env}.{lab}.device._.motor.control.release
    """
    return f"bioflow.{cfg.tenant}.{cfg.env}.{cfg.lab}.device._.motor.control.release"


# ---- 订阅端通配符 subject ----

def motor_control_subject(cfg: SchedulerConfig) -> str:
    """构建 motor.control 通配符 subject（订阅端）。

    bioflow.*.*.*.device._.motor.control.>
    * 匹配任意 tenant/env/lab，> 匹配 move/release。
    """
    return "bioflow.*.*.*.device._.motor.control.>"


def arrived_subject(cfg: SchedulerConfig) -> str:
    """构建 motor.status.arrived subject（上报端）。

    bioflow.{tenant}.{env}.{lab}.device._.motor.status.arrived
    """
    return f"bioflow.{cfg.tenant}.{cfg.env}.{cfg.lab}.device._.motor.status.arrived"


# ---- 辅助函数 ----

def get_motor_action(subject: str) -> str:
    """从 subject 提取 action（"move" 或 "release"）。

    subject 格式: bioflow.{tenant}.{env}.{lab}.device._.motor.control.{action}
    action 在第 9 段（索引 8）。
    """
    parts = subject.split(".")
    if len(parts) >= 9 and parts[8] in ("move", "release"):
        return parts[8]
    return "unknown"
