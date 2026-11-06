from datetime import datetime
import random


def generate_task_id() -> str:
    """生成新的task_id"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = str(random.randint(100, 999))
    return f"{timestamp}{random_suffix}"