"""节点配置管理器"""
from typing import Dict, Any, Optional

from .config_loader import ConfigLoader
from .built_in_configs import BuiltInConfigs
from .field_processors import FieldProcessor
from chatdify import dify_compat
from chatdify.utils.logging import get_logger


logger = get_logger(__name__)


def _deep_merge(dict1: Dict, dict2: Dict) -> Dict:
    """递归合并字典，dict2 优先"""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class NodeConfig:
    """节点配置管理器"""

    def __init__(self, node_type: str, generator_config: Dict[str, Any]):
        """初始化节点配置管理器
        
        Args:
            node_type: 节点类型
            generator_config: chatdify生成的配置
        """
        self._node_type = node_type
        self._generator_config = generator_config
        self._config_loader = ConfigLoader()
        
    def get_node_config(self) -> Dict[str, Any]:
        """获取节点完整配置
        
        配置优先级：workflow_* 模型配置 > chatdify生成的配置 > 内置配置 > model_fields配置
        """
        # 1. 获取model_fields配置（最低优先级）
        model_fields_config = self._get_model_fields_config()
        
        # 2. 获取内置配置
        built_in_config = BuiltInConfigs.get_built_in_defaults(self._node_type)
        base_config = BuiltInConfigs.get_base_defaults()
        built_in_config.update(base_config)

        # 3. 获取 workflow_* 模型配置（最高优先级）
        external_config = self._config_loader.load_node_config(self._node_type, self._generator_config)
        
        # 4. 按优先级合并配置
        merged_config = _deep_merge(model_fields_config, built_in_config)
        merged_config = _deep_merge(merged_config, self._generator_config)
        merged_config = _deep_merge(merged_config, external_config)

        # # 5. 验证配置
        self._validate(merged_config)
        
        return merged_config
    
    def _get_model_fields_config(self) -> Dict[str, Any]:
        """获取从模型字段生成的配置"""
        if not dify_compat.is_available():
            return {}

        try:
            node_data_cls = self._get_node_data_cls()
            if not node_data_cls:
                logger.warning(f"节点类型 {self._node_type} 没有数据类定义")
                return {}
                
            default_config = {}
            FieldProcessor.process_model_fields(
                node_data_cls.model_fields, 
                default_config
            )
            return default_config
            
        except Exception as e:
            logger.warning(f"生成节点配置失败: {str(e)}")
            return {}

    def _validate(self, config) -> None:
        """验证节点数据"""
        if not dify_compat.is_available():
            return

        node_data_cls = self._get_node_data_cls()
        if node_data_cls:
            node_data_cls.model_validate(config)

    def _get_node_data_cls(self) -> Optional[Any]:
        from chatdify.dify_compat.entities import get_node_data_cls

        return get_node_data_cls(self._node_type)
