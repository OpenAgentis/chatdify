from typing import Dict, Any, Set, Tuple
from dataclasses import dataclass, field
import re

from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.dify_compat.entities import (
    HttpRequestNodeBody,
    HttpRequestNodeData,
    VariableTemplateParser,
)


from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class HttpRequestValidationResult(BaseNodeValidationResult):
    """HTTP请求节点验证结果"""
    url_selectors: Set[Tuple[str, ...]] = field(default_factory=set)
    header_selectors: Set[Tuple[str, ...]] = field(default_factory=set)
    param_selectors: Set[Tuple[str, ...]] = field(default_factory=set)
    body_selectors: Set[Tuple[str, ...]] = field(default_factory=set)


class HttpRequestNodeValidator(BaseNodeValidator[HttpRequestNodeData]):
    """HTTP请求节点验证器"""
    
    MAX_URL_LENGTH = 2000
    MAX_HEADER_LENGTH = 2000
    MAX_PARAM_LENGTH = 2000
    MAX_BODY_LENGTH = 10000
    
    # HTTP请求节点支持的输出变量
    SUPPORTED_OUTPUTS = {"status_code", "body", "headers", "files"}
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> HttpRequestValidationResult:
        """验证HTTP请求节点配置"""
        result = HttpRequestValidationResult(is_valid=True, errors=[])
        
        try:
            # 获取节点数据并进行类型检查
            node_data = cls._get_node_data(node_data_config)
            if node_data is None:
                result.is_valid = False
                result.errors.append("无法解析HTTP请求节点配置数据")
                return result
                
            logger.debug(f"开始验证HTTP请求节点配置: {node_data.method} {node_data.url}")
            
            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证URL
            cls._validate_url(node_data, variable_pool, result)
            
            # 验证请求头
            cls._validate_headers(node_data, variable_pool, result)
            
            # 验证请求参数
            cls._validate_params(node_data, variable_pool, result)
            
            # 验证请求体
            cls._validate_body(node_data, variable_pool, result)
            
            # 验证授权配置
            cls._validate_authorization(node_data, variable_pool, result)
            
            # 验证超时配置
            cls._validate_timeout(node_data, result)
            
            # 记录验证统计信息
            cls._log_validation_summary(result)
            
            return result
            
        except Exception as e:
            logger.error(f"HTTP请求节点验证过程发生错误: {str(e)}", exc_info=True)
            return HttpRequestValidationResult(
                is_valid=False,
                errors=[f"HTTP请求节点验证过程发生错误: {str(e)}"]
            )
    
    @classmethod
    def _validate_basic_config(
        cls,
        node_data: HttpRequestNodeData,
        result: HttpRequestValidationResult
    ) -> None:
        """验证基础配置完整性"""
        # 验证HTTP方法
        if not node_data.method:
            result.is_valid = False
            result.errors.append("HTTP方法不能为空")
        elif node_data.method.upper() not in {
            "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"
        }:
            result.is_valid = False
            result.errors.append(f"不支持的HTTP方法: {node_data.method}")
            
        # 验证URL
        if not node_data.url:
            result.is_valid = False
            result.errors.append("URL不能为空")
    
    @classmethod
    def _validate_url(
        cls,
        node_data: HttpRequestNodeData,
        variable_pool: Dict[str, Any],
        result: HttpRequestValidationResult
    ) -> None:
        """验证URL配置"""
        if not node_data.url:
            return
            
        # 验证URL长度
        if len(node_data.url) > cls.MAX_URL_LENGTH:
            result.is_valid = False
            result.errors.append(f"URL长度超过最大限制({cls.MAX_URL_LENGTH}字符)")
            
        # 验证URL格式（支持变量模板）
        url_without_vars = re.sub(r'\{\{[^}]+\}\}', 'placeholder', node_data.url)
        if not re.match(r'^https?://', url_without_vars) and not node_data.url.startswith('{{'):
            result.is_valid = False
            result.errors.append("URL必须以http://或https://开头，或使用变量模板")
            
        # 提取URL中的变量选择器
        selectors = cls._extract_variable_selectors(node_data.url)
        for selector in selectors:
            result.url_selectors.add(tuple(selector))
            result.variable_selectors.add(tuple(selector))
            
            # 验证变量是否存在
            error = cls._validate_variable_exists(selector, variable_pool)
            if error:
                result.is_valid = False
                result.errors.append(f"URL变量验证失败: {error}")
    
    @classmethod
    def _validate_headers(
        cls,
        node_data: HttpRequestNodeData,
        variable_pool: Dict[str, Any],
        result: HttpRequestValidationResult
    ) -> None:
        """验证请求头配置"""
        if not node_data.headers:
            return
            
        # 验证请求头长度
        if len(node_data.headers) > cls.MAX_HEADER_LENGTH:
            result.is_valid = False
            result.errors.append(f"请求头长度超过最大限制({cls.MAX_HEADER_LENGTH}字符)")
            
        # 验证请求头格式
        lines = node_data.headers.strip().split('\n')
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
                
            if ':' not in line:
                result.is_valid = False
                result.errors.append(f"请求头第{line_num}行格式错误，应为'key: value'格式")
                continue
                
            key, value = line.split(':', 1)
            key = key.strip()
            if not key:
                result.is_valid = False
                result.errors.append(f"请求头第{line_num}行的键不能为空")
            
        # 提取请求头中的变量选择器
        selectors = cls._extract_variable_selectors(node_data.headers)
        for selector in selectors:
            result.header_selectors.add(tuple(selector))
            result.variable_selectors.add(tuple(selector))
            
            # 验证变量是否存在
            error = cls._validate_variable_exists(selector, variable_pool)
            if error:
                result.is_valid = False
                result.errors.append(f"请求头变量验证失败: {error}")
    
    @classmethod
    def _validate_params(
        cls,
        node_data: HttpRequestNodeData,
        variable_pool: Dict[str, Any],
        result: HttpRequestValidationResult
    ) -> None:
        """验证请求参数配置"""
        if not node_data.params:
            return
            
        # 验证请求参数长度
        if len(node_data.params) > cls.MAX_PARAM_LENGTH:
            result.is_valid = False
            result.errors.append(f"请求参数长度超过最大限制({cls.MAX_PARAM_LENGTH}字符)")
            
        # 验证请求参数格式
        lines = node_data.params.strip().split('\n')
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
                
            if ':' not in line:
                result.is_valid = False
                result.errors.append(f"请求参数第{line_num}行格式错误，应为'key: value'格式")
                continue
                
            key, value = line.split(':', 1)
            key = key.strip()
            if not key:
                result.is_valid = False
                result.errors.append(f"请求参数第{line_num}行的键不能为空")
            
        # 提取请求参数中的变量选择器
        selectors = cls._extract_variable_selectors(node_data.params)
        for selector in selectors:
            result.param_selectors.add(tuple(selector))
            result.variable_selectors.add(tuple(selector))
            
            # 验证变量是否存在
            error = cls._validate_variable_exists(selector, variable_pool)
            if error:
                result.is_valid = False
                result.errors.append(f"请求参数变量验证失败: {error}")
    
    @classmethod
    def _validate_body(
        cls,
        node_data: HttpRequestNodeData,
        variable_pool: Dict[str, Any],
        result: HttpRequestValidationResult
    ) -> None:
        """验证请求体配置"""
        if not node_data.body:
            return
            
        # 验证请求体数据
        if not node_data.body.data:
            if node_data.body.type != "none":
                result.is_valid = False
                result.errors.append(f"请求体类型为{node_data.body.type}时必须有数据")
            return
            
        # 验证请求体长度
        body_length = sum(len(str(item.value)) for item in node_data.body.data if hasattr(item, 'value'))
        if body_length > cls.MAX_BODY_LENGTH:
            result.is_valid = False
            result.errors.append(f"请求体长度超过最大限制({cls.MAX_BODY_LENGTH}字符)")
            
        # 验证请求体类型特定规则
        cls._validate_body_type_specific(node_data.body, result)
            
        # 提取请求体中的变量选择器
        for item in node_data.body.data:
            if item.type == "text" and hasattr(item, 'value'):
                selectors = cls._extract_variable_selectors(item.value)
                for selector in selectors:
                    result.body_selectors.add(tuple(selector))
                    result.variable_selectors.add(tuple(selector))
                    
                    # 验证变量是否存在
                    error = cls._validate_variable_exists(selector, variable_pool)
                    if error:
                        result.is_valid = False
                        result.errors.append(f"请求体变量验证失败: {error}")
            elif item.type == "file" and hasattr(item, 'file'):
                result.body_selectors.add(tuple(item.file))
                result.variable_selectors.add(tuple(item.file))
                
                # 验证文件变量是否存在
                error = cls._validate_variable_exists(item.file, variable_pool)
                if error:
                    result.is_valid = False
                    result.errors.append(f"请求体文件变量验证失败: {error}")
    
    @classmethod
    def _validate_body_type_specific(
        cls,
        body: HttpRequestNodeBody,
        result: HttpRequestValidationResult
    ) -> None:
        """验证请求体类型特定规则"""
        if body.type == "json":
            if len(body.data) != 1:
                result.is_valid = False
                result.errors.append("JSON请求体必须只包含一个数据项")
            elif body.data:
                try:
                    import json
                    # 尝试解析JSON（去除变量模板后）：将变量模板替换为有效的JSON值
                    json_str = re.sub(r'"\{\{[^}]+\}\}"', '"placeholder"', body.data[0].value)
                    # 处理非字符串值中的变量模板
                    json_str = re.sub(r'\{\{[^}]+\}\}', 'null', json_str)
                    json.loads(json_str)
                except (json.JSONDecodeError, AttributeError):
                    result.is_valid = False
                    result.errors.append("JSON请求体格式无效")
                    
        elif body.type == "binary":
            if len(body.data) != 1:
                result.is_valid = False
                result.errors.append("二进制请求体必须只包含一个文件")
                
        elif body.type == "raw-text":
            if len(body.data) != 1:
                result.is_valid = False
                result.errors.append("原始文本请求体必须只包含一个数据项")
    
    @classmethod
    def _validate_authorization(
        cls,
        node_data: HttpRequestNodeData,
        variable_pool: Dict[str, Any],
        result: HttpRequestValidationResult
    ) -> None:
        """验证授权配置"""
       
        if node_data.authorization.type == "api-key":
            if not node_data.authorization.config:
                result.is_valid = False
                result.errors.append("API Key授权方式必须配置授权信息")
            elif not node_data.authorization.config.api_key:
                result.is_valid = False
                result.errors.append("API Key不能为空")
            else:
                # 提取API Key中的变量选择器
                selectors = cls._extract_variable_selectors(node_data.authorization.config.api_key)
                for selector in selectors:
                    result.variable_selectors.add(tuple(selector))
                    
                    # 验证变量是否存在
                    error = cls._validate_variable_exists(selector, variable_pool)
                    if error:
                        result.is_valid = False
                        result.errors.append(f"授权API Key变量验证失败: {error}")
    
    @classmethod
    def _validate_timeout(
        cls,
        node_data: HttpRequestNodeData,
        result: HttpRequestValidationResult
    ) -> None:
        """验证超时配置"""
        if not node_data.timeout:
            return
            
        if node_data.timeout.connect <= 0:
            result.is_valid = False
            result.errors.append("连接超时必须大于0")
            
        if node_data.timeout.read <= 0:
            result.is_valid = False
            result.errors.append("读取超时必须大于0")
            
        if node_data.timeout.write <= 0:
            result.is_valid = False
            result.errors.append("写入超时必须大于0")
            
        # 验证超时值的合理性
        max_timeout = 600  # 10分钟
        if node_data.timeout.connect > max_timeout:
            result.is_valid = False
            result.errors.append(f"连接超时不能超过{max_timeout}秒")
            
        if node_data.timeout.read > max_timeout:
            result.is_valid = False
            result.errors.append(f"读取超时不能超过{max_timeout}秒")
            
        if node_data.timeout.write > max_timeout:
            result.is_valid = False
            result.errors.append(f"写入超时不能超过{max_timeout}秒")
    
    @classmethod
    def _log_validation_summary(
        cls,
        result: HttpRequestValidationResult
    ) -> None:
        """记录验证统计信息"""
        logger.info(
            f"HTTP请求节点验证完成 - 有效: {result.is_valid}, "
            f"错误数: {len(result.errors)}, "
            f"URL选择器数: {len(result.url_selectors)}, "
            f"请求头选择器数: {len(result.header_selectors)}, "
            f"请求参数选择器数: {len(result.param_selectors)}, "
            f"请求体选择器数: {len(result.body_selectors)}"
        )
        
        if result.errors:
            logger.error(f"HTTP请求节点验证错误: {result.errors}")
    
    @staticmethod
    def _extract_variable_selectors(text: str) -> list[list[str]]:
        """从文本中提取变量选择器
        
        使用VariableTemplateParser来提取变量选择器
        
        Args:
            text: 包含变量模板的文本
            
        Returns:
            list[list[str]]: 变量选择器列表
        """
        try:
            variable_template_parser = VariableTemplateParser(template=text)
            selectors = variable_template_parser.extract_variable_selectors()
            value_selectors = []
            for selector in selectors:
                value_selector = selector.value_selector
                value_selectors.append(value_selector)
            return value_selectors
        except Exception as e:
            logger.warning(f"提取变量选择器时发生错误: {e}")
            return []