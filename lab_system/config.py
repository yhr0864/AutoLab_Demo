# 配置文件
NATS_URL = "nats://localhost:4222"

# Stream 配置
STREAM_NAME = "LAB_MONITOR"
STREAM_SUBJECTS = [
    "lab.centrifuge.>",
    "lab.incubator.>"
]
STREAM_STORAGE              = "file"       # "file" | "memory"
STREAM_RETENTION            = "limits"     # "limits" | "workqueue" | "interest"
STREAM_DISCARD              = "old"        # "old" | "new"
STREAM_MAX_AGE_DAYS         = 7
STREAM_MAX_MSGS             = 100000
STREAM_MAX_BYTES            = 1024 ** 3    # 1 GB
STREAM_MAX_MSGS_PER_SUBJECT = 1000
STREAM_MAX_MSG_SIZE         = 1024 * 1024  # 1 MB

# Subject 定义
SUBJECTS = {
    # 上报通道
    "centrifuge_status": "lab.centrifuge.status",
    "centrifuge_alert":  "lab.centrifuge.alert",
    "incubator_status":  "lab.incubator.status",
    "incubator_alert":   "lab.incubator.alert",

    # 指令通道
    "cmd_centrifuge": "cmd.centrifuge.{device_id}",
    "cmd_incubator":  "cmd.incubator.{device_id}",
}

# 设备ID
CENTRIFUGE_ID = "centrifuge-01"
INCUBATOR_ID  = "incubator-01"

# 告警阈值
ALERT_THRESHOLDS = {
    "centrifuge": {
        "max_rpm":  15000,
        "max_temp": 40.0,
    },
    "incubator": {
        "max_temp": 42.0,
        "min_temp": 35.0,
        "max_co2":  6.0,
    }
}
