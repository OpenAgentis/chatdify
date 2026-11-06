from typing import Dict, Any, Optional, Tuple
import yaml
import json
import time
from chatdify.services.llm_service import LLMService
from chatdify.client.dify import AppClient
from chatdify.prompts.testcase_prompts import (
    ADVANCED_CHAT_QUERY_KEY,
    ADVANCED_CHAT_MULTI_TURN_KEY,
    GENERATE_DSL_TESTCASES_PROMPT_SYSTEM,
    GENERATE_DSL_TESTCASES_PROMPT_USER,
    GENERATE_MULTI_TURN_QUERIES_PROMPT_SYSTEM,
    GENERATE_MULTI_TURN_QUERIES_PROMPT_USER,
)
from chatdify.utils.logging import get_logger
from chatdify.utils.decorators import timing_decorator


logger = get_logger(__name__)


class TestCaseGenerator:
    """测试用例生成器
    
    负责为 DSL 工作流生成测试用例，支持文件上传和多种输入类型
    """
    
    def __init__(self, llm_service: LLMService, client: AppClient):
        """初始化测试用例生成器
        
        Args:
            llm_service: LLM服务实例
            client: Dify客户端实例
        """
        self._llm_service = llm_service
        self._client = client
    
    @timing_decorator
    def generate_testcases(self, dsl_content: str, input_file: Optional[str | list] = None, user_request: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[str]]:
        """生成测试用例

        Args:
            dsl_content: DSL内容
            input_file: 可选的输入文件路径

        Returns:
            (test_inputs, error_message)：成功时 error_message 为 None；失败时 test_inputs 为空 dict，error_message 为原因说明。
        """
        context = '[generate_testcases]'

        try:
            # 解析DSL获取文件变量
            file_input, file_err = self._extract_file_inputs(dsl_content, input_file, context)
            if file_err is not None:
                return {}, file_err
            
            # 生成基础测试输入
            test_inputs, base_err = self._generate_base_inputs(dsl_content, context, user_request=user_request)
            if base_err is not None:
                return {}, base_err
            if not test_inputs:
                return {}, f"{context} 未能生成基础测试输入（结果为空）"
            
            test_inputs.update(file_input)

            # advanced-chat 多轮对话工作流：生成连续多轮用户输入，用于多轮串联测试
            if self._is_multi_turn_advanced_chat(dsl_content):
                multi_turn_queries = self._generate_multi_turn_queries(
                    dsl_content=dsl_content, user_request=user_request,
                    base_inputs=test_inputs, context=context
                )
                if multi_turn_queries:
                    test_inputs[ADVANCED_CHAT_MULTI_TURN_KEY] = multi_turn_queries
                    logger.info(f"{context} 已生成 {len(multi_turn_queries)} 轮多轮对话测试输入")

            logger.info(f"{context} 成功: test_inputs: {test_inputs}")
            return test_inputs, None

        except Exception as e:
            err = f"{context} 异常: {type(e).__name__}: {e}"
            logger.error(err, exc_info=True)
            return {}, err
    
    def _extract_file_inputs(self, dsl_content: str, input_file: Optional[str | list], context: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """提取文件输入参数
        
        Args:
            dsl_content: DSL内容
            input_file: 输入文件路径
            context: 日志上下文
            
        Returns:
            (file_input, error_message)：若需要文件但未提供则 error_message 非空；无需文件时 file_input 可为空 dict。
            DSL 解析或结构异常时返回空 dict 与 error_message，不向外抛异常。
        """
        try:
            dsl_dict = yaml.safe_load(dsl_content)
            nodes = dsl_dict['workflow']['graph']['nodes']
            
            file_vars: list = []
            for node in nodes:
                if node['data']['type'] == 'start':
                    for var in node['data']['variables']:
                        if var['type'] in ['file', 'file-list']:
                            file_vars.append({
                                "name": var['variable'],
                                "type": var['type'],
                                "required": var.get('required', True),
                            })
                    break

            if not file_vars:
                return {}, None

            if not input_file:
                vars_desc = ", ".join(f"{v['type']} {v['name']}" for v in file_vars)
                msg = f"{context} 未获取到输入文件（start 节点存在文件类型变量: {vars_desc}）"
                logger.error(msg)
                return {}, msg

            input_files: list = [input_file] if isinstance(input_file, str) else list(input_file)

            if len(file_vars) == 1:
                file_var = file_vars[0]
                if file_var['type'] == 'file-list':
                    upload_file_info_list = []
                    for file_path in input_files:
                        upload_file_info = self._client.upload_file(file_path=file_path)
                        upload_file_info_list.append(upload_file_info["upload_file"].copy())
                    return {file_var['name']: upload_file_info_list}, None

                if len(input_files) > 1:
                    logger.warning(
                        f"{context} start 节点仅声明 1 个 file 类型变量 {file_var['name']}, "
                        f"但提供了 {len(input_files)} 个输入文件, 仅使用首个文件 {input_files[0]}"
                    )
                upload_file_info = self._client.upload_file(file_path=input_files[0])
                return {file_var['name']: upload_file_info["upload_file"].copy()}, None

            if any(v['type'] == 'file-list' for v in file_vars):
                msg = (
                    f"{context} start 节点同时存在多个文件变量且包含 file-list 类型, "
                    f"暂不支持该组合: {[v['name'] + ':' + v['type'] for v in file_vars]}"
                )
                logger.error(msg)
                return {}, msg

            if len(input_files) < len(file_vars):
                required = [v for v in file_vars if v['required']]
                if len(input_files) < len(required):
                    msg = (
                        f"{context} start 节点声明了 {len(required)} 个必填 file 类型变量"
                        f"({[v['name'] for v in required]}), 但只提供了 {len(input_files)} 个输入文件"
                    )
                    logger.error(msg)
                    return {}, msg
                optional = [v for v in file_vars if not v['required']]
                skipped = optional[len(input_files) - len(required):]
                logger.warning(
                    f"{context} 输入文件不足, 可选文件变量 {[v['name'] for v in skipped]} 不传"
                )
                file_vars = [v for v in file_vars if v not in skipped]

            if len(input_files) > len(file_vars):
                logger.warning(
                    f"{context} start 节点声明了 {len(file_vars)} 个 file 类型变量, "
                    f"但提供了 {len(input_files)} 个输入文件, 仅按顺序匹配前 {len(file_vars)} 个"
                )

            result: Dict[str, Any] = {}
            for file_var, file_path in zip(file_vars, input_files):
                upload_file_info = self._client.upload_file(file_path=file_path)
                result[file_var['name']] = upload_file_info["upload_file"].copy()
            return result, None
        except Exception as e:
            err = f"{context} 提取文件输入失败: {type(e).__name__}: {e}"
            logger.error(err, exc_info=True)
            return {}, err
    
    def _extract_dsl_mode(self, dsl_content: str) -> str:
        """提取DSL模式
        
        Args:
            dsl_content: DSL内容
            
        Returns:
            DSL模式: 'workflow' 或 'advanced-chat'
        """
        try:
            dsl_dict = yaml.safe_load(dsl_content)
            app_data = dsl_dict.get("app", {})
            dsl_mode = app_data.get('mode', 'workflow')
            return dsl_mode
        except Exception as e:
            logger.warning(f"提取DSL模式异常: {str(e)}，默认使用workflow模式")
            return 'workflow'

    def _generate_base_inputs(self, dsl_content: str, context: str, max_retries: int = 3, retry_delay: float = 1.0, user_request: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """生成基础测试输入（支持重试和变量完整性验证）
        
        Args:
            dsl_content: DSL内容
            context: 日志上下文
            max_retries: 最大重试次数
            retry_delay: 重试延迟时间
            user_request: 用户请求
            
        Returns:
            (基础测试输入字典, error_message)：成功时第二项为 None；失败时第一项为 None 且第二项为原因。
        """
        # 检测DSL模式
        dsl_mode = self._extract_dsl_mode(dsl_content)
        logger.info(f"{context} 检测到DSL模式: {dsl_mode}")
        
        # 获取 start 节点的所有变量信息（异常转为 (None, error_message) 向上返回，避免被误认为「无变量」）
        try:
            required_vars = self._extract_start_variables(dsl_content)
        except Exception as e:
            err = f"{context} 提取 start 节点变量失败: {type(e).__name__}: {e}"
            logger.error(err, exc_info=True)
            return None, err
        
        # advanced-chat 模式必须包含 sys.query（与 start 节点的 query 变量相互独立）
        if dsl_mode == "advanced-chat":
            if ADVANCED_CHAT_QUERY_KEY not in required_vars:
                required_vars[ADVANCED_CHAT_QUERY_KEY] = {
                    'type': 'paragraph',
                    'required': True,
                    'config': {
                        'label': '用户聊天输入',
                        'description': '用户的聊天输入内容（Dify 系统变量 sys.query）',
                        'variable': ADVANCED_CHAT_QUERY_KEY,
                    }
                }
                logger.info(f"{context} 为 advanced-chat 模式添加 {ADVANCED_CHAT_QUERY_KEY} 变量")
        
        if not required_vars:
            msg = f"{context} 未找到 start 节点变量信息"
            logger.warning(msg)
            return None, msg
        
        system_prompt = GENERATE_DSL_TESTCASES_PROMPT_SYSTEM
        user_prompt = GENERATE_DSL_TESTCASES_PROMPT_USER
        
        last_exception = None
        missing_vars_feedback = None  # 用于存储缺失变量的反馈信息
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"{context} 第 {attempt + 1} 次重试生成测试输入")
                    time.sleep(retry_delay * attempt)  # 递增延迟
                
                # 准备变量字典
                variables = {
                    "workflow_dsl": dsl_content,
                    "dsl_mode": dsl_mode
                }
                
                # 如果有缺失变量的反馈信息，添加到变量中
                if missing_vars_feedback:
                    variables["missing_variables_feedback"] = missing_vars_feedback
                    logger.info(f"{context} 向大模型反馈缺失变量信息: {missing_vars_feedback}")
                else:
                    variables["missing_variables_feedback"] = ""

                if user_request:
                    variables["user_request"] = user_request
                    logger.info(f"{context} 向大模型提供用户请求信息: {user_request}")
                else:
                    variables["user_request"] = ""
                
                test_inputs = self._llm_service.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    variables=variables,
                    call_type='testcase_generator'
                )
                
                if not test_inputs:
                    if attempt < max_retries - 1:
                        logger.warning(f"{context} 第 {attempt + 1} 次尝试未获取到测试输入参数，将重试")
                        continue
                    else:
                        err_msg = f"{context} 未获取到测试输入参数（已重试 {max_retries} 次）"
                        logger.error(err_msg)
                        # 提供默认值
                        if dsl_mode == "advanced-chat":
                            return {ADVANCED_CHAT_QUERY_KEY: "请帮我处理这个任务"}, None
                        return None, err_msg
                
                if isinstance(test_inputs, list):
                    test_inputs = test_inputs[0]
                
                
                # 验证变量完整性
                validation_result = self._validate_variables_completeness(test_inputs, required_vars, context)
                if not validation_result['is_complete']:
                    if attempt < max_retries - 1:
                        # 准备缺失变量的详细反馈信息
                        missing_vars_feedback = self._prepare_missing_vars_feedback(
                            validation_result, required_vars, test_inputs
                        )
                        logger.warning(f"{context} 第 {attempt + 1} 次尝试变量不完整: {validation_result['missing_vars']}，将重试")
                        continue
                    else:
                        logger.warning(f"{context} 变量不完整（已重试 {max_retries} 次）: {validation_result['missing_vars']}")
                        # 即使不完整也继续处理，但记录警告
                
                # 处理 select 类型变量
                self._process_select_variables(test_inputs, required_vars)

                if dsl_mode == "advanced-chat":
                    test_inputs = self._normalize_advanced_chat_query(test_inputs, required_vars)
                
                if attempt > 0:
                    logger.info(f"{context} 第 {attempt + 1} 次尝试成功生成测试输入")
                
                return test_inputs, None
                
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(f"{context} 第 {attempt + 1} 次尝试异常: {str(e)}，将重试")
                    continue
                else:
                    break
        
        # 所有重试都失败了，提供默认值
        err_msg = f"{context} 生成测试输入异常（已重试 {max_retries} 次）: {str(last_exception)}"
        logger.error(err_msg)
        if dsl_mode == "advanced-chat":
            logger.info(f"{context} 提供默认 {ADVANCED_CHAT_QUERY_KEY} 值")
            return {ADVANCED_CHAT_QUERY_KEY: "请帮我处理这个任务"}, None
        return None, err_msg

    def _normalize_advanced_chat_query(
        self,
        test_inputs: Dict[str, Any],
        required_vars: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """将 LLM 误输出的 query 键迁移为 sys.query（不与 start 节点的 query 变量冲突）。"""
        if ADVANCED_CHAT_QUERY_KEY in test_inputs:
            return test_inputs

        legacy_query = test_inputs.get("query")
        if legacy_query is None:
            return test_inputs

        # start 节点也有 query 变量时，两者独立，不能自动迁移
        if "query" in required_vars:
            return test_inputs

        normalized = dict(test_inputs)
        normalized.pop("query")
        normalized[ADVANCED_CHAT_QUERY_KEY] = legacy_query
        logger.info(f"将测试输入键 query 迁移为 {ADVANCED_CHAT_QUERY_KEY}")
        return normalized

    def _prepare_missing_vars_feedback(self, validation_result: Dict[str, Any], required_vars: Dict[str, Dict[str, Any]], current_inputs: Dict[str, Any]) -> str:
        """准备缺失变量的反馈信息
        
        Args:
            validation_result: 变量验证结果
            required_vars: 必需的变量信息
            current_inputs: 当前生成的输入
            
        Returns:
            格式化的缺失变量反馈信息
        """
        feedback_parts = []
        
        # 添加总体统计信息
        feedback_parts.append(f"变量完整性检查结果:")
        feedback_parts.append(f"- 总变量数: {len(validation_result['total_vars'])}")
        feedback_parts.append(f"- 已提供变量数: {len(validation_result['provided_vars'])}")
        feedback_parts.append(f"- 缺失变量数: {len(validation_result['missing_vars'])}")
        
        if validation_result['missing_vars']:
            feedback_parts.append(f"\n缺失的变量详情:")
            for var_name in validation_result['missing_vars']:
                if var_name in required_vars:
                    var_info = required_vars[var_name]
                    feedback_parts.append(f"- {var_name}:")
                    feedback_parts.append(f"  类型: {var_info['type']}")
                    feedback_parts.append(f"  必需: {var_info['required']}")
                    
                    # 如果是 select 类型，提供选项信息
                    if var_info['type'] == 'select' and 'options' in var_info['config']:
                        options = var_info['config']['options']
                        feedback_parts.append(f"  可选值: {options}, 只支持单选。")
        
        # 添加当前已生成的变量信息
        if current_inputs:
            feedback_parts.append(f"\n当前已生成的变量:")
            for var_name, var_value in current_inputs.items():
                if var_name in required_vars:
                    feedback_parts.append(f"- {var_name}: {var_value} (类型: {required_vars[var_name]['type']})")
        
        feedback_parts.append(f"\n请重新生成测试输入，确保包含所有缺失的变量，并为每个变量提供合适的测试值。")
        
        return "\n".join(feedback_parts)
    
    def _extract_start_variables(self, dsl_content: str) -> Dict[str, Dict[str, Any]]:
        """提取 start 节点的所有变量信息
        
        Args:
            dsl_content: DSL内容
            
        Returns:
            变量信息字典，key为变量名，value为变量配置；未找到 start 节点时返回空 dict。
        
        Raises:
            Exception: YAML 解析失败、缺少 workflow.graph.nodes、或节点结构异常时抛出，由 _generate_base_inputs 捕获并转为 error_message。
        """
        dsl_dict = yaml.safe_load(dsl_content)
        nodes = dsl_dict['workflow']['graph']['nodes']

        for node in nodes:
            if node['data']['type'] == 'start':
                variables = {}
                for var in node['data']['variables']:
                    var_name = var['variable']
                    variables[var_name] = {
                        'type': var['type'],
                        'required': var.get('required', True),
                        'config': var
                    }
                return variables

        return {}
    
    def _validate_variables_completeness(self, test_inputs: Dict[str, Any], required_vars: Dict[str, Dict[str, Any]], context: str) -> Dict[str, Any]:
        """验证变量完整性
        
        Args:
            test_inputs: 生成的测试输入
            required_vars: 必需的变量信息
            context: 日志上下文
            
        Returns:
            验证结果字典
        """
        missing_vars = []
        
        for var_name, var_info in required_vars.items():
            # 跳过文件类型变量（由 _extract_file_inputs 处理）
            if var_info['type'] in ['file', 'file-list']:
                continue
                
            # 检查必需变量是否存在
            if var_info['required'] and var_name not in test_inputs:
                missing_vars.append(var_name)
           
        is_complete = len(missing_vars) == 0
        
        return {
            'is_complete': is_complete,
            'missing_vars': missing_vars,
            'total_vars': required_vars,
            'provided_vars': [v for v in required_vars.keys() if v in test_inputs]
        }
    
    def _is_multi_turn_advanced_chat(self, dsl_content: str) -> bool:
        """判断是否为多轮对话工作流：advanced-chat 模式且声明了会话变量。

        会话变量（conversation_variables）是多轮对话保存跨轮状态的标志，
        据此判定需要进行多轮串联测试。
        """
        try:
            if self._extract_dsl_mode(dsl_content) != "advanced-chat":
                return False
            dsl_dict = yaml.safe_load(dsl_content)
            conv_vars = dsl_dict.get("workflow", {}).get("conversation_variables", [])
            return bool(conv_vars)
        except Exception as e:
            logger.warning(f"判断多轮对话工作流异常: {str(e)}")
            return False

    def _generate_multi_turn_queries(
        self, dsl_content: str, user_request: Optional[str], context: str,
        base_inputs: Optional[Dict[str, Any]] = None
    ) -> list:
        """为多轮对话工作流生成连续多轮用户输入（sys.query 序列）。

        base_inputs 为第一步已生成的结构化 start 输入（含轮数等字段，如 total_rounds），
        作为 LLM 确定对话轮数 N、避免在 query 里复述这些参数的首要依据。

        失败时返回空列表，调用方据此回退为单轮测试，不影响主流程。
        """
        try:
            # 仅传非聊天/非多轮的结构化输入字段，过滤掉 sys.query 与多轮序列本身
            filtered_inputs = {
                k: v for k, v in (base_inputs or {}).items()
                if k not in (ADVANCED_CHAT_QUERY_KEY, ADVANCED_CHAT_MULTI_TURN_KEY)
            }
            variables = {
                "workflow_dsl": dsl_content,
                "user_request": user_request or "",
                "base_inputs": json.dumps(filtered_inputs, ensure_ascii=False),
            }
            result = self._llm_service.generate_json(
                system_prompt=GENERATE_MULTI_TURN_QUERIES_PROMPT_SYSTEM,
                user_prompt=GENERATE_MULTI_TURN_QUERIES_PROMPT_USER,
                variables=variables,
                call_type='testcase_generator',
            )

            # 兼容 LLM 可能返回 {"queries": [...]} 或直接数组
            if isinstance(result, dict):
                for key in ("queries", "multi_turn_queries", "turns", ADVANCED_CHAT_MULTI_TURN_KEY):
                    if isinstance(result.get(key), list):
                        result = result[key]
                        break

            if isinstance(result, list):
                queries = [str(q).strip() for q in result if isinstance(q, (str, int, float)) and str(q).strip()]
                if len(queries) >= 2:
                    return queries
                logger.warning(f"{context} 多轮对话输入不足 2 轮，回退单轮测试: {queries}")
            else:
                logger.warning(f"{context} 多轮对话输入格式非预期: {type(result)}")
        except Exception as e:
            logger.warning(f"{context} 生成多轮对话输入失败，回退单轮测试: {str(e)}")
        return []

    def _process_select_variables(self, test_inputs: Dict[str, Any], required_vars: Dict[str, Dict[str, Any]]) -> None:
        """处理 select 类型变量
        
        Args:
            test_inputs: 测试输入字典（会被修改）
            required_vars: 变量信息字典
        """
        for var_name, var_info in required_vars.items():
            if var_info['type'] == 'select' and var_name in test_inputs:
                val = test_inputs[var_name]
                if val and isinstance(val, list):
                    test_inputs[var_name] = val[0]
    
    