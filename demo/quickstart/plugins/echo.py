"""Echo plugin - 简单示例，返回输入内容"""


async def generate(query: str, config: dict, **kwargs) -> dict:
    """
    Plugin 入口函数。

    Args:
        query: 用户输入
        config: providers.yaml 中的配置（除 type/plugin 外的所有字段）

    Returns:
        必须包含 "output" 字段
    """
    prefix = config.get("prefix", "Echo")
    return {"output": f"{prefix}: {query}"}
