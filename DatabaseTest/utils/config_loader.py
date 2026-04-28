import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    """
    加载 YAML 配置文件

    :param config_path: 配置文件路径
    :return: 解析后的 Python dict
    """
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
