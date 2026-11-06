"""
LLM服务模块
"""
import copy
import json
import time
from typing import Dict, Any, Optional, Union, List, Tuple
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import SecretStr
import yaml

from chatdify.settings import get_settings
from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import LLMServiceError
from .token_stats import TokenStats, get_tokenizer


class LLMService:
    """LLM服务，封装对大语言模型的调用"""
    
    def __init__(
        self,
        model_name: str = None,
        api_key: str = None,
        base_url: str = None,
        proxy: str = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ):
        """初始化LLM服务
        
        Args:
            model_name: 模型名称，默认从配置获取
            api_key: API密钥，默认从配置获取
            base_url: API基础URL，默认从配置获取
            proxy: 代理地址，默认从配置获取，格式如 'http://proxy.example.com:8080'
            extra_body: 合并进请求体的额外参数（如深度思考开关），默认从配置获取
        """
        self.logger = get_logger(__name__)
        settings = get_settings()

        self.model_name = model_name or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.proxy = proxy or settings.llm_proxy
        self.extra_body = extra_body if extra_body is not None else settings.llm_extra_body
        self.debug_http = settings.llm_debug_http

        missing = [
            name for name, value in
            (("llm_model", self.model_name), ("llm_base_url", self.base_url), ("llm_api_key", self.api_key))
            if not value
        ]
        if missing:
            raise LLMServiceError(
                f"LLM 配置不完整，缺少: {', '.join(missing)}。"
                "请运行 `chatdify init`，或设置环境变量 CHATDIFY_LLM_MODEL / CHATDIFY_LLM_BASE_URL / CHATDIFY_LLM_API_KEY。"
            )

        # LLM 调用重试配置
        self.max_retries = settings.llm_max_retries
        self.retry_delay = settings.llm_retry_delay
        
        # 初始化token统计
        self.token_stats = TokenStats()
        
        # # 初始化tokenizer用于token计数
        self.tokenizer = get_tokenizer(self.model_name)
        
        self.llm = self._initialize_llm()

        self.logger.info(
            f"LLM服务初始化完成，使用模型: {self.model_name}, extra_body: {self.extra_body or '未配置'}"
        )
        if self.debug_http:
            default_params = getattr(self.llm, "_default_params", None)
            if default_params:
                self.logger.info(f"ChatOpenAI 默认请求参数: {default_params}")

    def _format_request_body_for_log(self, body: str) -> str:
        if not body:
            return "(empty)"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body[:2000]
        sanitized = copy.deepcopy(payload)
        for msg in sanitized.get("messages", []):
            content = msg.get("content")
            if isinstance(content, str) and len(content) > 500:
                msg["content"] = content[:500] + "...(truncated)"
        return json.dumps(sanitized, indent=2, ensure_ascii=False)

    def _attach_http_client(self, base_params: Dict[str, Any]) -> None:
        """按需挂载 httpx 客户端（代理 / 调试请求日志）。"""
        debug_http = self.debug_http
        if not debug_http and not self.proxy:
            return

        import httpx

        event_hooks: Dict[str, list] = {}
        if debug_http:

            def log_request(request: httpx.Request) -> None:
                body = request.content.decode("utf-8") if request.content else ""
                self.logger.info(
                    "LLM HTTP 请求 %s %s\nBody:\n%s",
                    request.method,
                    request.url,
                    self._format_request_body_for_log(body),
                )

            event_hooks["request"] = [log_request]

        client_kwargs: Dict[str, Any] = {}
        if self.proxy:
            client_kwargs["proxy"] = self.proxy
        if event_hooks:
            client_kwargs["event_hooks"] = event_hooks
        base_params["http_client"] = httpx.Client(**client_kwargs)

        if self.proxy:
            self.logger.info(f"使用代理: {self.proxy}")
        if debug_http:
            self.logger.info(
                "已开启 llm_debug_http，将在每次 chat/completions 请求前打印请求体"
            )

    def _initialize_llm(self) -> ChatOpenAI:
        """初始化LLM客户端"""
        try:
            base_params = {
                "model": self.model_name,
                "api_key": SecretStr(self.api_key),
                "base_url": self.base_url,
                "temperature": 0.0,
                "max_completion_tokens": 60000,
            }
            
            if self.extra_body:
                base_params["extra_body"] = self.extra_body

            self._attach_http_client(base_params)
            return ChatOpenAI(**base_params)
        except Exception as e:
            self.logger.error(f"初始化LLM客户端失败: {str(e)}")
            raise LLMServiceError(f"初始化LLM客户端失败: {str(e)}")
    
    def generate(
        self, 
        system_prompt: str, 
        user_prompt: str, 
        variables: Optional[Dict[str, Any]] = None, 
        is_stroutput: bool = True,
        call_type: Optional[str] = None
    ) -> Union[str, Any]:
        """
        生成文本
        
        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            variables: 提示中的变量
            is_stroutput: 是否返回字符串输出，默认True
            call_type: 调用类型，可选值：'node'（节点）、'edge'（边）、None（通用）
            
        Returns:
            生成的文本或原始响应
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])

        # 先构建不带StrOutputParser的chain获取原始响应
        base_chain = prompt | self.llm
        variables = variables or {}

        # 调用 LLM 支持重试，应对限流/超时/网络抖动等瞬时错误；递增退避
        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    delay = self.retry_delay * attempt
                    self.logger.warning(
                        f"LLM生成重试 第 {attempt + 1}/{self.max_retries} 次，等待 {delay:.1f}s"
                    )
                    time.sleep(delay)

                # 获取原始响应用于提取token信息
                raw_result = base_chain.invoke(variables)

                self.logger.info(f"原始响应: {raw_result}")

                # 尝试从原始响应中获取准确的token使用信息
                input_tokens, output_tokens, cached_tokens = self._extract_usage_from_response(raw_result)

                # 如果无法从响应中获取token信息，使用默认值
                if input_tokens == 0 and output_tokens == 0:
                    # 估算token数量（粗略估计：1个token约等于4个字符）
                    input_text = f"{system_prompt}\n{user_prompt}"
                    if variables:
                        formatted_prompt = prompt.format(**variables)
                        input_text = str(formatted_prompt)

                    output_text = str(raw_result.content if hasattr(raw_result, 'content') else raw_result)
                    input_tokens = max(1, len(input_text) // 4)
                    output_tokens = max(1, len(output_text) // 4)

                # 更新统计（包含类型信息）
                self.token_stats.add_usage(input_tokens, output_tokens, call_type, cached_tokens=cached_tokens)

                # 根据is_stroutput决定返回格式
                if is_stroutput:
                    # 如果需要字符串输出，从原始响应中提取内容
                    if hasattr(raw_result, 'content'):
                        result = raw_result.content
                    else:
                        # 使用StrOutputParser处理
                        str_parser = StrOutputParser()
                        result = str_parser.invoke(raw_result)
                else:
                    result = raw_result

                if attempt > 0:
                    self.logger.info(f"LLM生成第 {attempt + 1} 次重试成功")
                self.logger.info(f"文本生成成功，类型: {call_type or '通用'}，输入tokens: {input_tokens}（缓存命中 {cached_tokens}）, 输出tokens: {output_tokens}")
                return result

            except Exception as e:
                last_exception = e
                self.logger.error(
                    f"LLM生成失败（第 {attempt + 1}/{self.max_retries} 次）: {str(e)}"
                )

        # 所有重试均失败
        error_msg = f"LLM生成失败（已重试 {self.max_retries} 次）: {str(last_exception)}"
        self.logger.error(error_msg)
        raise LLMServiceError(error_msg)
    
    def generate_json(self, system_prompt: str, user_prompt: str, variables: Dict[str, Any]= None, call_type: str = None) -> List[Dict[str, Any]]:
        """
        生成JSON格式的文本并解析

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            variables: 提示中的变量
            call_type: 调用类型，可选值：'node'（节点）、'edge'（边）、None（通用）

        Returns:
            解析后的JSON对象
        """
       
        try:
            json_str = self.generate_code(system_prompt, user_prompt, variables, call_type=call_type, format_type="json")
            self.logger.info(f"处理后的JSON文本: {json_str}")
            return yaml.safe_load(json_str)

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {str(e)}, 原始文本: {json_str}")
            raise LLMServiceError(f"JSON解析失败: {str(e)}")
        except Exception as e:
            self.logger.error(f"生成JSON失败: {str(e)}")
            raise LLMServiceError(f"生成JSON失败: {str(e)}")

    def generate_code(self, system_prompt: str, user_prompt: str, 
                 variables: Optional[Dict[str, Any]] = None, 
                 call_type: Optional[str] = None, 
                 format_type: str = "json") -> str:
        """
        生成并提取指定格式的代码内容
    
        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            variables: 提示中的变量
            call_type: 调用类型，可选值：'node'（节点）、'edge'（边）、None（通用）
            format_type: 代码格式类型，默认为'sql'
    
        Returns:
            str: 生成的代码内容
            
        Raises:
            LLMServiceError: 当代码生成失败时抛出
        """
        # 参数验证
        if not system_prompt or not user_prompt:
            raise LLMServiceError("系统提示和用户提示不能为空")
        
        result = None
        try:
            # 生成LLM响应
            result = self.generate(system_prompt, user_prompt, variables, call_type=call_type)
            
            if not result or not result.strip():
                raise LLMServiceError("LLM返回空响应")
            
            # 提取代码块内容
            code = self._extract_code_block_content(result, format_type)
            
            if not code or not code.strip():
                self.logger.warning(f"未能从响应中提取到{format_type}代码块，返回原始响应\n{result}")
                return result.strip()
            
            self.logger.info(f"成功生成{format_type}代码，长度: {len(code)}")
            return code
    
        except Exception as e:
            self.logger.error(f"代码生成失败: {str(e)}, 原始响应: {result if result else 'N/A'}")
            raise LLMServiceError(f"代码生成失败: {str(e)}")

    def get_token_stats(self) -> Dict[str, Any]:
        """获取token使用统计"""
        return self.token_stats.get_stats()
    
    def reset_token_stats(self):
        """重置token统计"""
        self.token_stats.reset()
        self.logger.info("Token统计已重置")
    
    def log_token_stats(self):
        """记录当前token统计信息"""
        stats = self.get_token_stats()
        self.logger.info(f"Token使用统计: {stats}")

    def _extract_code_block_content(self, markdown_text: str, format_type: str = "json") -> str:
        """从markdown文本中提取指定格式的内容"""
        if not markdown_text:
            return ""

        stripped_text = markdown_text.strip()
        if format_type == "json" and stripped_text.startswith(("{", "[")):
            return stripped_text

        # 查找JSON代码块开始位置
        start = markdown_text.find(f'```{format_type}')
        if start == -1:
            if format_type == "json":
                return stripped_text
            start = markdown_text.find('```')
            if start == -1:
                return stripped_text
        
        # 定位内容开始位置
        content_start = markdown_text.find('\n', start)
        if content_start == -1:
            # 没有换行符，内容紧跟在```format_type之后
            start_offset = len(f'```{format_type}')
            content_start = start + start_offset
        else:
            # 内容在换行符之后
            content_start += 1
        
        # 查找结束位置，从content_start之后开始查找
        end = markdown_text.rfind('```')
        if end == -1:
            # 没有找到结束标记，返回从content_start到末尾的内容
            return markdown_text[content_start:].strip()
        
        # 验证start和end的有效性
        if content_start >= end:
            return markdown_text.strip()
        
        return markdown_text[content_start:end].strip()
    
    def _extract_usage_from_response(self, response: Any) -> Tuple[int, int, int]:
        """从LLM响应中提取 (输入, 输出, 输入中命中缓存的) token 数"""
        try:
            raw = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
            meta = getattr(response, "usage_metadata", None) or {}
            input_tokens = int(raw.get("prompt_tokens") or meta.get("input_tokens") or 0)
            output_tokens = int(raw.get("completion_tokens") or meta.get("output_tokens") or 0)
            cached_tokens = int(
                (raw.get("prompt_tokens_details") or {}).get("cached_tokens")  # OpenAI, GLM
                or raw.get("prompt_cache_hit_tokens")  # DeepSeek
                or raw.get("cache_read_input_tokens")  # Anthropic-style gateways
                or (meta.get("input_token_details") or {}).get("cache_read")
                or 0
            )
            return input_tokens, output_tokens, cached_tokens
        except Exception as e:
            self.logger.warning(f"无法从响应中提取token使用信息: {e}")
        return 0, 0, 0