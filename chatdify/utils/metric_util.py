"""
工作流工具函数模块
"""
from typing import Dict, Any, Tuple


def get_node_summary(nodes) -> Dict[str, Any]:
    """获取节点统计信息
    
    Args:
        nodes: 节点列表
        
    Returns:
        Dict[str, Any]: 包含节点总数和类型分布的字典
    """
    if not nodes:
        return {
            "total_count": 0,
            "type_distribution": {}
        }
    
    # 统计节点总数
    total_count = len(nodes)
    
    # 统计节点类型分布
    type_distribution = {}
    for node in nodes:
        if not node:
            node_type = "NoneType"
        else:
            node_type = node.data.get("type", "unknown")
            if node_type in type_distribution:
                type_distribution[node_type] += 1
            else:
                type_distribution[node_type] = 1
    
    return {
        "total_count": total_count,
        "type_distribution": type_distribution
    }


def get_workflow_errors_by_type(workflow):
    """
    从 workflow.total_errors 中获取并分类动态错误和静态错误
    按每次执行分别统计，不进行合并
    
    Args:
        workflow: Workflow 对象
        
    Returns:
        dict: {
            'execution_summary': dict  # 按执行次数统计的错误摘要
        }
    """
    attempts = sorted(k for k in workflow.total_errors if k >= 0)
    execution_summary = [[] for _ in range(attempts[-1] + 1)] if attempts else []
    last_attempt = attempts[-1] if attempts else None
    finally_status = "succeeded"
    
    for execution_count, workflow_errors in workflow.total_errors.items():
        if execution_count < 0:
            continue
        static_is_valid = True
        dynamic_is_valid = True
        
        # 收集静态错误
        execution_static = []
        execution_dynamic = []

        if workflow_errors.static_errors:
            static_is_valid = False
            for error in workflow_errors.static_errors:
                if error.error_type != "node":
                    execution_static.append(dict(
                        error_type=error.error_type,
                        error=error.error_message,
                    ))
                    continue

                node_errors = error.data["node"]
                error_node_types = node_errors.get_error_node_types()
                format_data = dict()
                for node_type in error_node_types:
                    format_data[node_type] = node_errors.get_errors_by_type(node_type)

                execution_static.append(dict(
                    error_type="node",
                    error=format_data,
                ))
        
        # 收集动态错误
        if workflow_errors.dynamic_errors:
            for error in workflow_errors.dynamic_errors:
                if error.is_valid:
                    continue

                dynamic_is_valid = False
                error_type = error.error_type
                assert error_type in ["runtime", "import", "testcase", "result_analysis"]
                if error_type == "runtime":
                    if not error.data:
                        execution_dynamic.append(dict(
                            error_type=error_type,
                            error=error.error_message,
                        ))
                    elif "data" not in error.data or "node_id" not in error.data["data"] or "node_type" not in error.data["data"]:
                        execution_dynamic.append(dict(
                            error_type=error_type,
                            error=error.data,
                        ))
                    else:
                        execution_dynamic.append(dict(
                            error_type=error_type,
                            node_id=error.data["data"]["node_id"],
                            node_type=error.data["data"]["node_type"],
                            error=error.data["data"]["error"],
                        )
                        )
                elif error_type == "testcase":
                    execution_dynamic.append(dict(
                        error_type=error_type,
                        error=error.error_message,
                    ))
                elif error_type == "result_analysis":
                    # 只保留 LLM 分析结论，避免把整段 workflow_result 写进摘要
                    analysis = (error.data or {}).get("data", {}).get("result_analysis")
                    execution_dynamic.append(dict(
                        error_type=error_type,
                        error=error.error_message,
                        analysis=analysis,
                    ))
                else:
                    if error.data:
                        execution_dynamic.append(dict(
                            error_type=error_type,
                            error=error.error_message,
                            data=error.data,
                        ))
                    else:   
                        execution_dynamic.append(dict(
                            error_type=error_type,
                            error=error.error_message,
                        ))
        else:
            dynamic_is_valid = None
                # xecution_dynamic.append(error.data["data"])   
        # 记录每次执行的错误摘要
        execution_summary[execution_count] = {
            'static_is_valid':  static_is_valid,
            'dynamic_is_valid': dynamic_is_valid,
            'static_errors': execution_static,
            'dynamic_errors': execution_dynamic
        }

        if execution_count == last_attempt:
            if dynamic_is_valid is False:
                finally_status = "failed"
            elif dynamic_is_valid is None:
                finally_status = "unextracted"
    
    return finally_status, execution_summary


def generate_workflow_summary(workflow) -> Dict[str, Any]:
    """生成工作流执行摘要
    
    Args:
        workflow: 工作流对象
        execution_time: 执行时间（秒），可选
        
    Returns:
        Dict[str, Any]: 包含工作流执行摘要的字典
    """
    # 统计节点信息
    node_summary = get_node_summary(workflow.nodes)
    
    # 获取错误信息
    
    # 将execution_summary转换为按执行顺序排列的列表
    status, errors = get_workflow_errors_by_type(workflow)
    
    # 从 total_execution_duration 中计算总执行时间
    # 格式: {执行次数: 执行时间}
    total_execution_time = sum(workflow.total_execution_duration.values())
    
    # 构建基础摘要
    summary = {
        "status": status,
        "execution_count": workflow.execution_count,
        "errors": errors,
        "node_summary": node_summary,
        "execution_duration": workflow.total_execution_duration,  # 每次执行的时间详情
        "total_execution_time": total_execution_time,  # 总执行时间（求和）
        "actual_status": getattr(workflow, 'is_valid', {}),
        "total_llm_token_stats": workflow.total_llm_token_stats,  # 每次执行的token统计详情
        "total_dynamic_validation_duration": workflow.total_dynamic_validation_duration,
    }
    
    return summary


def get_dynamic_running_output_and_log(workflow) -> Tuple[str, str]:
    """获取工作流输出和日志

    Args:
        workflow: 工作流对象

    Returns:
        Tuple[str, str]: 输出和日志
    """

    try:
        output = workflow.last_errors.get_dynamic_output()
    except Exception as e:
        output = ""

    try:
        log = workflow.last_errors.get_dynamic_running_result_summary()    
    except Exception as e:
        log = ""

    return output, log
