import logging


def setup_logger(name: str = "iot_app") -> logging.Logger:
    """
    初始化日志对象
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return logging.getLogger(name)
