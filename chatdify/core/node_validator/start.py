from typing import Dict, Any, Set
from dataclasses import dataclass, field
from .base import BaseNodeValidator, BaseNodeValidationResult

from chatdify.dify_compat.entities import StartNodeData, VariableEntity, VariableEntityType
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class StartValidationResult(BaseNodeValidationResult):
    """开始节点验证结果"""
    variable_names: Set[str] = field(default_factory=set)  # 存储变量名称
    variable_types: Dict[str, str] = field(default_factory=dict)  # 存储变量类型映射


class StartNodeValidator(BaseNodeValidator[StartNodeData]):
    """开始节点验证器"""
    
    # 支持的变量类型
    SUPPORTED_VARIABLE_TYPES = {
        VariableEntityType.TEXT_INPUT,
        VariableEntityType.SELECT,
        VariableEntityType.PARAGRAPH,
        VariableEntityType.NUMBER,
        VariableEntityType.EXTERNAL_DATA_TOOL,
        VariableEntityType.FILE,
        VariableEntityType.FILE_LIST,
        VariableEntityType.CHECKBOX
    }
    
    # 变量名称最大长度
    MAX_VARIABLE_NAME_LENGTH = 50
    MAX_LABEL_LENGTH = 100
    MAX_DESCRIPTION_LENGTH = 500
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> StartValidationResult:
        """验证开始节点配置"""
        try:
            # 获取节点数据
            node_data = cls._get_node_data(node_data_config)
            
            result = StartValidationResult(
                is_valid=True,
                errors=[],
                variable_selectors=set(),
                variable_names=set(),
                variable_types={}
            )
            
            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证变量配置
            cls._validate_variables_config(node_data, result)
            
            # 验证变量名称唯一性
            cls._validate_variable_uniqueness(node_data, result)
            
            # 验证变量类型和约束
            cls._validate_variable_constraints(node_data, result)
                
            return result
            
        except Exception as e:
            logger.error(f"开始节点验证过程发生错误: {str(e)}", exc_info=True)
            return StartValidationResult(
                is_valid=False,
                errors=[f"开始节点验证过程发生错误: {str(e)}"],
                variable_selectors=set(),
                variable_names=set(),
                variable_types={}
            )
    
    @classmethod
    def _validate_basic_config(
        cls,
        node_data: StartNodeData,
        result: StartValidationResult
    ) -> None:
        """验证基础配置"""
        # 验证节点数据完整性
        if not hasattr(node_data, 'variables'):
            result.is_valid = False
            result.errors.append("缺少变量配置")
            return
            
        # 验证variables是否为序列类型
        if not hasattr(node_data.variables, '__iter__'):
            result.is_valid = False
            result.errors.append("变量配置必须是序列类型")
            return
    
    @classmethod
    def _validate_variables_config(
        cls,
        node_data: StartNodeData,
        result: StartValidationResult
    ) -> None:
        """验证变量配置"""
        if not node_data.variables:
            # 开始节点可以没有变量，这是合法的
            logger.info("开始节点没有配置变量(variables)")
            return
            
        for i, variable in enumerate(node_data.variables):
            cls._validate_single_variable(variable, i, result)
    
    @classmethod
    def _validate_single_variable(
        cls,
        variable: VariableEntity,
        index: int,
        result: StartValidationResult
    ) -> None:
        """验证单个变量配置"""
        variable_prefix = f"变量[{index}]"
        
        # 验证变量名称
        if not variable.variable:
            result.is_valid = False
            result.errors.append(f"{variable_prefix}: 变量名称不能为空")
            return

        # 验证变量名称格式
        if not cls._validate_selector_naming(variable.variable):
            result.is_valid = False
            result.errors.append(
                f"{variable_prefix}: 变量名称 '{variable.variable}' 格式无效，"
                "必须是有效的Python标识符"
            )
            return
            
        # 验证变量名称长度
        if len(variable.variable) > cls.MAX_VARIABLE_NAME_LENGTH:
            result.is_valid = False
            result.errors.append(
                f"{variable_prefix}: 变量名称长度不能超过 {cls.MAX_VARIABLE_NAME_LENGTH} 个字符"
            )
            
        # 验证标签
        if not variable.label:
            result.is_valid = False
            result.errors.append(f"{variable_prefix}: 变量标签不能为空")
        elif len(variable.label) > cls.MAX_LABEL_LENGTH:
            result.is_valid = False
            result.errors.append(
                f"{variable_prefix}: 变量标签长度不能超过 {cls.MAX_LABEL_LENGTH} 个字符"
            )
            
        # 验证描述长度
        if variable.description and len(variable.description) > cls.MAX_DESCRIPTION_LENGTH:
            result.is_valid = False
            result.errors.append(
                f"{variable_prefix}: 变量描述长度不能超过 {cls.MAX_DESCRIPTION_LENGTH} 个字符"
            )
            
        # 验证变量类型
        if variable.type not in cls.SUPPORTED_VARIABLE_TYPES:
            result.is_valid = False
            result.errors.append(
                f"{variable_prefix}: 不支持的变量类型 '{variable.type}'，"
                f"支持的类型: {[t.value for t in cls.SUPPORTED_VARIABLE_TYPES]}"
            )
            
        # 记录变量信息
        result.variable_names.add(variable.variable)
        result.variable_types[variable.variable] = variable.type.value
    
    @classmethod
    def _validate_variable_uniqueness(
        cls,
        node_data: StartNodeData,
        result: StartValidationResult
    ) -> None:
        """验证变量名称唯一性"""
        variable_names = []
        for variable in node_data.variables:
            if variable.variable:
                variable_names.append(variable.variable)
                
        # 检查重复的变量名称
        seen = set()
        duplicates = set()
        for name in variable_names:
            if name in seen:
                duplicates.add(name)
            seen.add(name)
            
        if duplicates:
            result.is_valid = False
            result.errors.append(
                f"发现重复的变量名称: {', '.join(sorted(duplicates))}"
            )
    
    @classmethod
    def _validate_variable_constraints(
        cls,
        node_data: StartNodeData,
        result: StartValidationResult
    ) -> None:
        """验证变量类型特定的约束"""
        for i, variable in enumerate(node_data.variables):
            variable_prefix = f"变量[{i}] '{variable.variable}'"
            
            # 验证SELECT类型的选项
            if variable.type == VariableEntityType.SELECT:
                if not variable.options:
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: SELECT类型变量必须提供选项列表"
                    )
                elif len(variable.options) == 0:
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: SELECT类型变量的选项列表不能为空"
                    )
                    
            # 验证NUMBER类型的最大长度
            if variable.type == VariableEntityType.NUMBER and variable.max_length:
                if variable.max_length <= 0:
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: NUMBER类型变量的最大长度必须大于0"
                    )
                    
            # 验证文件类型的配置
            if variable.type in [VariableEntityType.FILE, VariableEntityType.FILE_LIST]:
                cls._validate_file_type_constraints(variable, variable_prefix, result)
    
    @classmethod
    def _validate_file_type_constraints(
        cls,
        variable: VariableEntity,
        variable_prefix: str,
        result: StartValidationResult
    ) -> None:
        """验证文件类型变量的约束"""
        from chatdify.dify_compat.entities import FileType, FileTransferMethod
        
        # 验证文件类型配置
        if not variable.allowed_file_types and not variable.allowed_file_extensions:
            result.is_valid = False
            result.errors.append(
                f"{variable_prefix}: 建议为文件类型变量配置允许的文件类型(allowed_file_types)或扩展名(allowed_file_extensions)"
            )
        
        # 验证allowed_file_types的有效性
        if variable.allowed_file_types:
            valid_file_types = {ft.value for ft in FileType}
            for file_type in variable.allowed_file_types:
                if file_type not in valid_file_types:
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: 无效的文件类型 '{file_type}'，"
                        f"支持的文件类型: {sorted(valid_file_types)}"
                    )
        
        # 验证allowed_file_extensions的格式
        if variable.allowed_file_extensions:
            for ext in variable.allowed_file_extensions:
                if not isinstance(ext, str):
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: 文件扩展名必须是字符串类型"
                    )
                elif ext and not ext.startswith('.'):
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: 文件扩展名 '{ext}' 建议以点号(.)开头"
                    )
                elif len(ext) > 10:  # 合理的扩展名长度限制
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: 文件扩展名 '{ext}' 过长，建议不超过10个字符"
                    )
        
        # 验证allowed_file_upload_methods的有效性
        valid_upload_methods = {method.value for method in FileTransferMethod}

        if variable.allowed_file_upload_methods:
            for method in variable.allowed_file_upload_methods:
                if method not in valid_upload_methods:
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: 无效的文件上传方式 '{method}'，"
                        f"支持的上传方式: {sorted(valid_upload_methods)}"
                    )
        else:
            # 如果没有配置上传方式，给出建议
            result.is_valid = False
            result.errors.append(
                f"{variable_prefix}: 建议配置文件上传方式(allowed_file_upload_methods), "
                f"支持的上传方式: {sorted(valid_upload_methods)}"
            )
        
        if not result.is_valid:
            return
            
        # 验证文件类型和扩展名的一致性
        cls._validate_file_type_extension_consistency(
            variable, variable_prefix, result
        )
    
    @classmethod
    def _validate_file_type_extension_consistency(
        cls,
        variable: VariableEntity,
        variable_prefix: str,
        result: StartValidationResult
    ) -> None:
        """验证文件类型和扩展名的一致性"""
        # 如果两者都没有配置，跳过验证
        if not variable.allowed_file_types and not variable.allowed_file_extensions:
            return
            
        # 定义文件类型和常见扩展名的双向映射
        type_extension_mapping = {
            'image': {".pg", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"},
            'document': {'.pdf', '.doc', '.docx', '.txt', '.md', 'mdx', '.rtf', '.odt', '.xls', '.xlsx', '.ppt', '.pptx', '.xml', '.csv', '.html', '.eml', '.msg', '.epub'},
            'audio': {".mp3", ".m4a", ".wav", ".webm", ".amr"},
            'video': {".mp4", ".mov", ".mpeg", ".mpga"},
            'custom': set()  # custom类型不做限制
        }
        
        # 创建扩展名到文件类型的反向映射
        extension_type_mapping = {}
        for file_type, extensions in type_extension_mapping.items():
            if file_type != 'custom':
                for ext in extensions:
                    extension_type_mapping[ext] = file_type
        
        # 情况1: 只有扩展名，没有文件类型 - 推荐文件类型
        if variable.allowed_file_extensions and not variable.allowed_file_types:
            inferred_types = set()
            unknown_extensions = []
            
            for ext in variable.allowed_file_extensions:
                if not ext:
                    continue
                ext_lower = ext.lower()
                if ext_lower in extension_type_mapping:
                    inferred_types.update(extension_type_mapping[ext_lower])
                else:
                    unknown_extensions.append(ext)
            
            if inferred_types:
                result.is_valid = False
                result.errors.append(
                    f"{variable_prefix}: 建议根据扩展名配置文件类型（allowed_file_types）: {sorted(inferred_types)}"
                )
            
            if unknown_extensions:
                result.is_valid = False
                result.errors.append(
                    f"{variable_prefix}: 发现未知扩展名 {unknown_extensions}，建议配置文件类型（allowed_file_types）: 'custom' "
                )
            return
        
        # 情况2: 两者都有配置 - 验证一致性
        if variable.allowed_file_types and variable.allowed_file_extensions:
            configured_types = set(variable.allowed_file_types)
        
            unknown_extensions = []
            extension_type_conflicts = {}
            
            for ext in variable.allowed_file_extensions:
                if not ext:
                    continue
                ext_lower = ext.lower()
                if ext_lower in extension_type_mapping:
                    ext_types = extension_type_mapping[ext_lower]
                    # 检查扩展名是否与配置的类型冲突
                    conflicting_types = set([ext_types]) - configured_types
                    if conflicting_types:
                        extension_type_conflicts[ext] = conflicting_types
                else:
                    unknown_extensions.append(ext)
            
            # 报告冲突和建议
            if extension_type_conflicts:
                result.is_valid = False
                for ext, conflicting_types in extension_type_conflicts.items():
                    result.errors.append(
                        f"{variable_prefix}: 扩展名 '{ext}' 属于文件类型 {sorted(conflicting_types)}，但未在 allowed_file_types 中配置"
                    )
        
            if unknown_extensions:
                if 'custom' not in configured_types:
                    result.is_valid = False
                    result.errors.append(
                        f"{variable_prefix}: 发现未知扩展名 {unknown_extensions}，建议配置文件类型（allowed_file_types）: 'custom'"
                    )
            
           
    