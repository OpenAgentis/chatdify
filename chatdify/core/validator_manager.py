from typing import Dict, Any, Optional, List, Callable
import yaml
import time
from chatdify.services.llm_service import LLMService
from chatdify.services.file_service import FileService
from chatdify.settings import get_settings
from chatdify.utils.decorators import timing_decorator
from chatdify.prompts.testcase_prompts import (
    ADVANCED_CHAT_QUERY_KEY,
    ADVANCED_CHAT_MULTI_TURN_KEY,
)
from chatdify.utils.logging import get_logger
from chatdify.models.workflow import ValidationResult


logger = get_logger(__name__)


class ValidatorManager:
    def __init__(self, llm_service: LLMService, file_service: FileService, base_url: Optional[str] = None):
        """初始化验证器"""
        settings = get_settings()

        self._validators: List[tuple[Callable, Dict[str, Any]]]  = []
        self._llm_service = llm_service
        self._file_service = file_service
        self._dynamic_enabled = bool(base_url or settings.dify_url) and settings.dify_dynamic_validation
        self._result_analysis_enabled = settings.dify_result_analysis
        self.client = None
        self._testcase_generator = None

        # 动态验证需要 Dify 实例；客户端在首次验证时再登录
        if self._dynamic_enabled:
            from chatdify.client.dify import AppClient
            from chatdify.core.testcase_generator import TestCaseGenerator

            self.client = AppClient(base_url or settings.dify_url)
            self._testcase_generator = TestCaseGenerator(llm_service, self.client)

    @property
    def dynamic_enabled(self) -> bool:
        return self._dynamic_enabled

    def accepts(self, workflow_errors, result: ValidationResult) -> bool:
        """判断本轮结果是否可接受：有 Dify 实例时以动态验证为准，否则以静态校验为准。"""
        if self._dynamic_enabled:
            return result.is_valid
        return result.is_valid and workflow_errors.static_is_valid()

    @timing_decorator    
    def validate(
        self,
        dsl_content: str,
        test_inputs: Optional[Dict[str, Any]] = None,
        input_file: Optional[str | list] = None,
        user_request: Optional[str] = None
    ) -> ValidationResult:
        """验证入口 - 返回结构化结果"""
        logger.info(f"[validate] 开始验证")
        
        if not self._dynamic_enabled:
            return ValidationResult(is_valid=True)
        
        # 解析DSL获取mode
        try:
            dsl_data = yaml.safe_load(dsl_content)
            app_data = dsl_data.get("app", {})
            dsl_mode = app_data.get('mode', 'workflow')  # 默认为workflow模式
        except yaml.YAMLError:
            dsl_mode = 'workflow'  # 解析失败时默认为workflow模式
        
        # 生成测试用例
        testcase_error: Optional[str] = None
        if not test_inputs:
            test_inputs, testcase_error = self._testcase_generator.generate_testcases(
                dsl_content=dsl_content, input_file=input_file, user_request=user_request
            )

        if not test_inputs:
            return ValidationResult(
                is_valid=False,
                error_type="testcase",
                error_message=testcase_error
                or "[validate] 未能生成测试用例（generate_testcases 未返回原因，结果为空）。",
            )

        # 根据mode选择验证器
        if dsl_mode == 'advanced-chat':
            validators = [
                (self._validate_dsl_import, {'dsl_content': dsl_content}),
                (
                    self._validate_run_draft_advanced_chat,
                    {
                        'app_id': None,
                        'dsl_content': dsl_content,
                        'test_inputs': test_inputs,
                        'user_request': user_request,
                    }
                )
            ]
        else:
            validators = [
                (self._validate_dsl_import, {'dsl_content': dsl_content}),
                (
                    self._validate_run_draft_workflow,
                    {
                        'app_id': None,
                        'dsl_content': dsl_content,
                        'test_inputs': test_inputs,
                        'user_request': user_request,
                    }
                )
            ]
        
        self._validators = validators
        
        result = ValidationResult(is_valid=True)

        result_data = None

        for validator, args in self._validators:
            if 'app_id' in args and args['app_id'] is None and result_data:
                args['app_id'] = result_data.get('app_id')
                
            current_result = validator(**args)

            if not current_result.is_valid:
                logger.error(f"验证失败: {current_result.error_message}")
                return current_result

            result_data = current_result.data
            result = current_result
            
        return result
    
    def _validate_dsl_import(self, dsl_content: str, max_retries: int = 3, retry_delay: float = 1.0) -> ValidationResult:
        """验证DSL导入 - 返回结构化结果（支持重试）"""
        context = '[validate_dsl_import]'
        
        # 检查格式
        try:
            yaml.safe_load(dsl_content)
        except yaml.YAMLError as e:
            return ValidationResult(
                is_valid=False,
                error_type='import',
                error_message=f"{context} DSL格式错误: {str(e)}"
            )
       
        # 尝试导入应用（支持重试）
        last_exception = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"{context} 第 {attempt + 1} 次重试导入应用")
                    time.sleep(retry_delay * attempt)  # 递增延迟
                
                import_result = self.client.import_app(
                    mode='yaml-content',
                    yaml_content=dsl_content
                )
                
                if import_result.get('error'):
                    error_msg = import_result['error']
                    # 检查是否为可重试的错误
                    if self._is_retryable_error(error_msg) and attempt < max_retries - 1:
                        logger.warning(f"{context} 导入失败（第 {attempt + 1} 次尝试）: {error_msg}，将重试")
                        continue
                    
                    return ValidationResult(
                        is_valid=False,
                        error_type='import',
                        error_message=f"{context} 导入失败: {error_msg}",
                        data=import_result
                    )
                    
                app_id = import_result.get('app_id')
                if not app_id:
                    if attempt < max_retries - 1:
                        logger.warning(f"{context} 未获取到应用ID（第 {attempt + 1} 次尝试），将重试")
                        continue
                    
                    return ValidationResult(
                        is_valid=False,
                        error_type='import',
                        error_message=f"{context} 导入失败: 未获取到应用ID",
                        data=import_result
                    )
                
                # 成功导入
                if attempt > 0:
                    logger.info(f"{context} 第 {attempt + 1} 次尝试成功导入应用")
                
                return ValidationResult(
                    is_valid=True,
                    data=import_result
                )
                
            except Exception as e:
                last_exception = e
                if self._is_retryable_exception(e) and attempt < max_retries - 1:
                    logger.warning(f"{context} 导入异常（第 {attempt + 1} 次尝试）: {str(e)}，将重试")
                    continue
                else:
                    break
        
        # 所有重试都失败了
        error_msg = f"{context} 导入验证异常（已重试 {max_retries} 次）: {str(last_exception)}。请检查DSL是否正确。"
        return ValidationResult(
            is_valid=False,
            error_type='import',
            error_message=error_msg
        )
    
    def _is_retryable_error(self, error_msg: str) -> bool:
        """判断错误是否可重试"""
        retryable_keywords = [
            'timeout',
            'connection',
            'network',
            'temporary',
            '503',
            '502',
            '500',
            'rate limit',
            'too many requests'
        ]
        error_lower = error_msg.lower()
        return any(keyword in error_lower for keyword in retryable_keywords)
    
    def _is_retryable_exception(self, exception: Exception) -> bool:
        """判断异常是否可重试"""
        import requests
        
        # 网络相关异常
        if isinstance(exception, (requests.exceptions.ConnectionError, 
                                requests.exceptions.Timeout,
                                requests.exceptions.RequestException)):
            return True
        
        # HTTP 状态码相关
        if hasattr(exception, 'response') and exception.response is not None:
            status_code = exception.response.status_code
            # 5xx 服务器错误和 429 限流错误可重试
            if status_code >= 500 or status_code == 429:
                return True
        
        return False
    
    def _validate_run_draft_workflow(
        self,
        app_id: str,
        dsl_content: str,
        test_inputs: Dict[str, Any],
        user_request: Optional[str] = None
    ) -> ValidationResult:
        """验证工作流运行 - 返回结构化结果"""
        context = '[validate_run_draft_workflow]'
        
        try:
            workflow_result, running_results = self.client.run_draft_workflow(
                app_id=app_id,
                inputs=test_inputs
            )

            if 'data' not in workflow_result:
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=f"{context} 运行失败: 响应格式错误。",
                    data=workflow_result,
                    running_data=running_results
                )
                
            data = workflow_result['data']
            node_id = data.get('node_id')
            node_type = data.get('node_type')
            error = data.get('error')

            if error:
                # 根据节点类型，对error信息进行单独处理；
                error_message = self._process_node_error(context, node_id, node_type, error)
                
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=error_message,
                    data=workflow_result,
                    running_data=running_results
                )
                
            if not data.get('outputs'):
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=f"{context} 节点[node_id: {node_id}, node_type: {node_type}] 运行失败: 未获取到输出结果。请仔细检查DSL，是否存在节点配置错误。",
                    data=workflow_result,
                    running_data=running_results
                )
                
            return self._validate_result_analysis(
                context=context,
                workflow_result=workflow_result,
                running_results=running_results,
                dsl_content=dsl_content,
                test_inputs=test_inputs,
                user_request=user_request
            )
            
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_type='runtime',
                error_message=f"{context} 运行验证异常: {str(e)}"
            )
    
    def _process_node_error(self, context: str, node_id: str, node_type: str, error: str) -> str:
        """根据节点类型，处理节点错误信息"""
        extra_info = ''
        if node_type == 'code':
            if 'No module named' in error:
                extra_info = '\n DIFY 当前环境不支持该Python依赖项，请使用其他PYTHON依赖项'
            if 'JavaScript execution error' in error:
                extra_info = """\n DIFY code节点输出变量名中不能包含'error'命名字段。请用其他名字替代，比如'err'。"""
                
        error += extra_info
        error_message = f"{context} 节点[node_id: {node_id}, node_type: {node_type}] 运行错误: {error}"
        
        return error_message
    
    # advanced-chat 测试输入中无需作为 inputs 透传的控制键（聊天内容/多轮序列单独处理）
    _ADVANCED_CHAT_RESERVED_KEYS = {ADVANCED_CHAT_QUERY_KEY, "query", ADVANCED_CHAT_MULTI_TURN_KEY}

    def _resolve_advanced_chat_inputs(self, test_inputs: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """解析 advanced-chat 测试输入：聊天内容走 query 参数，其余走 inputs。"""
        other_inputs = {
            k: v for k, v in test_inputs.items() if k not in self._ADVANCED_CHAT_RESERVED_KEYS
        }

        if ADVANCED_CHAT_QUERY_KEY in test_inputs:
            return test_inputs[ADVANCED_CHAT_QUERY_KEY], other_inputs

        return "请帮我处理这个任务", other_inputs
    
    def _validate_run_draft_advanced_chat(
        self,
        app_id: str,
        dsl_content: str,
        test_inputs: Dict[str, Any],
        user_request: Optional[str] = None
    ) -> ValidationResult:
        """验证高级聊天工作流运行 - 返回结构化结果"""
        context = '[validate_run_draft_advanced_chat]'

        # 多轮对话：存在多轮输入序列时，按轮次串联 conversation_id 运行
        multi_turn_queries = test_inputs.get(ADVANCED_CHAT_MULTI_TURN_KEY)
        if isinstance(multi_turn_queries, list) and len(multi_turn_queries) >= 2:
            return self._validate_multi_turn_advanced_chat(
                context=context,
                app_id=app_id,
                dsl_content=dsl_content,
                test_inputs=test_inputs,
                multi_turn_queries=multi_turn_queries,
                user_request=user_request,
            )

        try:
            query, other_inputs = self._resolve_advanced_chat_inputs(test_inputs)
            
            workflow_result, running_results = self.client.run_draft_advanced_chat(
                app_id=app_id,
                query=query,
                inputs=other_inputs,
            )

            if 'data' not in workflow_result:
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=f"{context} 运行失败: 响应格式错误。",
                    data=workflow_result,
                    running_data=running_results
                )
                
            data = workflow_result['data']
            node_id = data.get('node_id')
            node_type = data.get('node_type')
            error = data.get('error')

            if error:
                # 根据节点类型，对error信息进行单独处理
                error_message = self._process_node_error(context, node_id, node_type, error)
                
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=error_message,
                    data=workflow_result,
                    running_data=running_results
                )
                
            if not data.get('outputs'):
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=f"{context} 节点[node_id: {node_id}, node_type: {node_type}] 运行失败: 未获取到输出结果。请仔细检查DSL，是否存在节点配置错误。",
                    data=workflow_result,
                    running_data=running_results
                )
                
            return self._validate_result_analysis(
                context=context,
                workflow_result=workflow_result,
                running_results=running_results,
                dsl_content=dsl_content,
                test_inputs=test_inputs,
                user_request=user_request
            )
            
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_type='runtime',
                error_message=f"{context} 运行验证异常: {str(e)}"
            )

    def _validate_multi_turn_advanced_chat(
        self,
        context: str,
        app_id: str,
        dsl_content: str,
        test_inputs: Dict[str, Any],
        multi_turn_queries: List[str],
        user_request: Optional[str] = None,
    ) -> ValidationResult:
        """按轮次串联 conversation_id 运行多轮对话，逐轮校验运行时错误，最后整体做结果分析。"""
        _, other_inputs = self._resolve_advanced_chat_inputs(test_inputs)

        conversation_id: Optional[str] = None
        transcript: List[Dict[str, Any]] = []
        last_workflow_result: Optional[Dict[str, Any]] = None
        last_running_results: List[Dict[str, Any]] = []

        for turn_index, query in enumerate(multi_turn_queries, start=1):
            turn_ctx = f"{context} 第{turn_index}/{len(multi_turn_queries)}轮"
            try:
                # Dify 草稿运行每一轮都会校验 input form 必填变量，需逐轮透传 inputs，
                # 否则第 2 轮起会报「xxx is required in input form」。
                workflow_result, running_results = self.client.run_draft_advanced_chat(
                    app_id=app_id,
                    query=query,
                    inputs=other_inputs,
                    conversation_id=conversation_id,
                )
            except Exception as e:
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=f"{turn_ctx} 运行验证异常: {str(e)}",
                    running_data=last_running_results,
                )

            last_workflow_result = workflow_result
            last_running_results = running_results

            if not isinstance(workflow_result, dict) or 'data' not in workflow_result:
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=f"{turn_ctx} 运行失败: 响应格式错误。",
                    data=workflow_result,
                    running_data=running_results,
                )

            data = workflow_result['data']
            error = data.get('error')
            if error:
                error_message = self._process_node_error(
                    turn_ctx, data.get('node_id'), data.get('node_type'), error
                )
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=error_message,
                    data=workflow_result,
                    running_data=running_results,
                )

            if not data.get('outputs'):
                return ValidationResult(
                    is_valid=False,
                    error_type='runtime',
                    error_message=(
                        f"{turn_ctx} 节点[node_id: {data.get('node_id')}, "
                        f"node_type: {data.get('node_type')}] 运行失败: 未获取到输出结果。"
                        f"请检查多轮对话状态（conversation 会话变量）与节点配置。"
                    ),
                    data=workflow_result,
                    running_data=running_results,
                )

            # 串联会话：用本轮返回的 conversation_id 驱动下一轮
            new_conversation_id = workflow_result.get('conversation_id')
            if new_conversation_id:
                conversation_id = new_conversation_id

            transcript.append({
                "turn": turn_index,
                "query": query,
                "outputs": data.get('outputs'),
            })

        logger.info(f"{context} 多轮对话 {len(multi_turn_queries)} 轮均运行成功，conversation_id={conversation_id}")

        # 整体结果分析：把多轮对话记录交给大模型，判断是否真正实现了多轮推进
        return self._validate_result_analysis(
            context=context,
            workflow_result=last_workflow_result,
            running_results=last_running_results,
            dsl_content=dsl_content,
            test_inputs=test_inputs,
            user_request=user_request,
            multi_turn_transcript=transcript,
        )

    def _validate_result_analysis(
        self,
        context: str,
        workflow_result: Dict[str, Any],
        running_results: List[Dict[str, Any]],
        dsl_content: str,
        test_inputs: Dict[str, Any],
        user_request: Optional[str] = None,
        multi_turn_transcript: Optional[List[Dict[str, Any]]] = None,
    ) -> ValidationResult:
        """可选：用大模型分析 Dify 运行结果是否满足用户需求。"""
        if not self._result_analysis_enabled:
            return ValidationResult(
                is_valid=True,
                data=workflow_result,
                running_data=running_results
            )

        if not user_request:
            logger.warning(f"{context} 已开启结果分析，但未提供用户需求，跳过结果分析")
            return ValidationResult(
                is_valid=True,
                data=workflow_result,
                running_data=running_results
            )

        try:
            analysis = self._analyze_result_with_llm(
                user_request=user_request,
                dsl_content=dsl_content,
                test_inputs=test_inputs,
                workflow_result=workflow_result,
                running_results=running_results,
                multi_turn_transcript=multi_turn_transcript,
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_type='result_analysis',
                error_message=f"{context} 运行结果大模型分析失败: {str(e)}",
                data=workflow_result,
                running_data=running_results
            )

        is_satisfied = self._parse_bool(analysis.get("is_satisfied"))
        feedback = analysis.get("feedback") or analysis.get("suggestion") or ""
        reason = analysis.get("reason") or ""

        workflow_result.setdefault("data", {})["result_analysis"] = analysis

        if is_satisfied:
            logger.info(f"{context} 运行结果分析通过: {reason or feedback}")
            return ValidationResult(
                is_valid=True,
                data=workflow_result,
                running_data=running_results
            )

        message_parts = [
            f"{context} 运行结果不符合用户需求。"
        ]
        if reason:
            message_parts.append(f"修改DSL原因: {reason}")
        if feedback:
            message_parts.append(f"修改DSL建议: {feedback}")
        
        logger.info(f"{context} 运行结果不符合用户需求。is_satisfied: {is_satisfied}, reason: {reason}, feedback: {feedback}")

        return ValidationResult(
            is_valid=False,
            error_type='result_analysis',
            error_message="\n".join(message_parts),
            data=workflow_result,
            running_data=running_results
        )

    def _analyze_result_with_llm(
        self,
        user_request: str,
        dsl_content: str,
        test_inputs: Dict[str, Any],
        workflow_result: Dict[str, Any],
        running_results: List[Dict[str, Any]],
        multi_turn_transcript: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        is_multi_turn = bool(multi_turn_transcript)

        system_prompt = """你是 Dify 工作流运行结果评估专家。请基于"本次测试输入对应的运行结果"，判断输出是否与用户需求一致，并结合 DSL 原始内容给出可操作的修改建议。

评估范围与判定规则：
1. 评估范围仅限"本次测试输入产生的输出"是否符合用户需求；测试输入只是单次采样，不要求覆盖用户的全部使用场景。
2. 仅当输出与用户意图明显冲突，或结构/字段/语义存在明显错误时，才判 is_satisfied=false；其余情况（包括证据不足、仅是采样覆盖度不够）一律判 is_satisfied=true，并在 reason 中说明依据。
3. 如果输出是文件/图片/音频/URL/二进制元数据等非纯文本，视为有效输出，根据用户需求判断该类型是否合理，而不要求结果一定是可读文本。
4. 反馈建议要可指导下一轮修改 DSL：结合 DSL 中的节点结构、变量映射、提示词、条件分支、工具调用、输出节点配置等定位问题；引用节点时优先使用节点 title，可附 node_id，不确定时只描述节点类型或逻辑位置即可。

输出要求：
- 严格输出 JSON 对象，可放在 ```json 代码块中；除 JSON 外不要输出任何解释文字。
- JSON 字段说明：
  - is_satisfied: boolean，true 表示符合用户需求，false 表示不符合。
  - reason: string，仅描述"运行结果与用户需求之间的对齐或差距"，不要写修改建议。
  - feedback: string，is_satisfied=false 时仅写"如何修改 DSL"的可操作建议（节点/字段/取值/分支等），不要重复 reason；is_satisfied=true 时给出简短肯定说明即可。
"""

        if is_multi_turn:
            system_prompt += """
多轮对话（advanced-chat）专项评估：
- 本次为多轮对话测试，下方提供按轮次排列的「用户输入 → 本轮输出」记录。
- 重点判断对话是否真正"多轮推进"：各轮输出应随对话上下文/会话变量（conversation.*）的变化而变化，体现阶段流转。
- 若多轮输出几乎完全重复、不随用户输入变化、或忽略了上一轮上下文，判 is_satisfied=false，并在 feedback 中指出应使用 conversation 会话变量 + assigner + if-else 维护跨轮状态。
"""

        sections = [
            "请基于本次测试输入对应的运行结果，结合 DSL 原始内容评估是否符合用户需求。\n",
            f"用户原始需求：\n{user_request}\n",
            f"DSL 原始内容：\n{dsl_content}\n",
            f"本次动态运行测试输入：\n{self._dump_for_prompt(test_inputs)}\n",
        ]
        if is_multi_turn:
            sections.append(
                f"多轮对话逐轮记录（按发送顺序，含每轮用户输入与该轮输出）：\n"
                f"{self._dump_for_prompt(multi_turn_transcript)}\n"
            )
        sections.extend([
            f"最终运行结果：\n{self._dump_for_prompt(workflow_result.get('data', {}).get('outputs'))}\n",
            f"所有节点运行摘要：\n{self._dump_for_prompt(self._extract_running_summary(running_results))}\n",
        ])
        user_prompt = "\n".join(sections)

        # langchain ChatPromptTemplate 默认按 f-string 解析，DSL / outputs 中的 {、} 会被误当成变量占位符并报错。
        # 这里已在 Python 端拼好 prompt，再对花括号统一转义，避免运行时 KeyError。
        safe_system_prompt = self._escape_curly_braces(system_prompt)
        safe_user_prompt = self._escape_curly_braces(user_prompt)

        logger.info(
            f"[result_analysis] dsl_len={len(dsl_content)}, "
            f"user_prompt_len={len(safe_user_prompt)}, "
            f"running_events={len(running_results or [])}"
        )

        analysis = self._llm_service.generate_json(
            system_prompt=safe_system_prompt,
            user_prompt=safe_user_prompt,
            variables={},
            call_type='result_analysis'
        )

        if isinstance(analysis, list):
            analysis = analysis[0] if analysis else {}

        if not isinstance(analysis, dict):
            raise ValueError(f"分析结果格式错误: {analysis}")

        return analysis

    def _extract_running_summary(self, running_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        summary = []
        for event in running_results or []:
            data = event.get("data", {})
            summary.append({
                "event": event.get("event"),
                "node_id": data.get("node_id"),
                "node_type": data.get("node_type"),
                "error": data.get("error"),
                "outputs": data.get("outputs"),
            })
        return summary

    def _dump_for_prompt(self, value: Any) -> str:
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)

    def _escape_curly_braces(self, text: str) -> str:
        """转义文本中的所有花括号，避免 langchain f-string 模板把内容当成变量占位符。"""
        return text.replace("{", "{{").replace("}", "}}")

    def _parse_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "符合", "满足")
        return bool(value)
