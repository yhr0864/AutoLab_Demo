#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scheduler_service/subjects.py — NATS Subject 构建（参考 move.txt / release.txt）

from .config import SchedulerConfig


def move_subject(cfg: SchedulerConfig) -> str:
    """构建 move subject: {tenant}.{env}.{lab}.device._.motor.control.move"""
    return f"{cfg.tenant}.{cfg.env}.{cfg.lab}.device._.motor.control.move"


def release_subject(cfg: SchedulerConfig) -> str:
    """构建 release subject: {tenant}.{env}.{lab}.device._.motor.control.release"""
    return f"{cfg.tenant}.{cfg.env}.{cfg.lab}.device._.motor.control.release"
