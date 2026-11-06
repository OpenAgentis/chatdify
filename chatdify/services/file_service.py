"""
文件服务模块
"""
import os
import yaml
from typing import Dict, List, Any, Optional, Tuple

from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import FileServiceError
from chatdify.paths import (
    NODE_REFERENCE_DIR,
    DSL_TEMPLATE_DIR,
    NODE_USAGE_FILENAME,
    EDGE_USAGE_FILENAME,
    NODE_SAMPLE_FILENAME,
    EDGE_SAMPLE_FILENAME,
    NODE_ERROR_FILENAME,
    COMMON_NODE_USAGE_FILENAME,
    COMMON_EDGE_USAGE_FILENAME,
    NODE_RAG_TOP_K,
    EDGE_RAG_TOP_K,
    NODE_TYPES_CONFIG_PATH,
    DSL_TEMPLATE_TYPES_CONFIG_PATH
)

logger = get_logger(__name__)

class FileService:
    """文件服务，处理文件读写操作"""
    
    def __init__(self, node_reference_dir: str = None, dsl_template_dir: str = None):
        """
        初始化文件服务
        
        Args:
            node_reference_dir: 节点参考目录，默认使用包内知识库
            dsl_template_dir: DSL 模版目录，默认使用包内知识库
        """
        self.node_reference_dir = str(node_reference_dir or NODE_REFERENCE_DIR)
        self.dsl_template_dir = str(dsl_template_dir or DSL_TEMPLATE_DIR)

        logger.info(f"文件服务初始化完成，节点参考目录: {self.node_reference_dir}")
    
    def get_available_node_types(self) -> List[str]:
        """
        获取可用的节点类型列表
        优先从 yaml 配置文件读取，如果不存在则降级到目录扫描
        
        Returns:
            节点类型列表
        """
        try:
            # 1. 优先尝试从 yaml 配置文件读取
            node_types = self._load_node_types_from_config()
            if node_types:
                logger.info(f"从配置文件加载了{len(node_types)}个节点类型")
                return node_types
            
            # 2. 降级到目录扫描方案
            logger.info("配置文件不存在或为空，降级使用目录扫描方案")
            return self._load_node_types_from_directory()
            
        except Exception as e:
            logger.error(f"获取节点类型失败: {str(e)}")
            raise FileServiceError(f"获取节点类型失败: {str(e)}")
    
    def _load_node_types_from_config(self) -> Optional[List[str]]:
        """
        从 yaml 配置文件加载节点类型
        
        Returns:
            节点类型列表，如果配置文件不存在或解析失败则返回 None
        """
        try:
            if not os.path.exists(NODE_TYPES_CONFIG_PATH):
                logger.debug(f"节点类型配置文件不存在: {NODE_TYPES_CONFIG_PATH}")
                return None
            
            with open(NODE_TYPES_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config or 'node_types' not in config:
                logger.warning(f"配置文件格式错误或缺少 node_types 字段: {NODE_TYPES_CONFIG_PATH}")
                return None
            
            node_types = config['node_types']
            if not isinstance(node_types, list):
                logger.warning(f"node_types 字段必须是列表格式: {NODE_TYPES_CONFIG_PATH}")
                return None
            
            # 过滤掉空值和非字符串值
            valid_node_types = [nt for nt in node_types if isinstance(nt, str) and nt.strip()]
            
            if not valid_node_types:
                logger.warning(f"配置文件中没有有效的节点类型: {NODE_TYPES_CONFIG_PATH}")
                return None
            
            logger.debug(f"从配置文件成功加载节点类型: {valid_node_types}")
            return valid_node_types
            
        except yaml.YAMLError as e:
            logger.error(f"解析 yaml 配置文件失败: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"读取节点类型配置文件失败: {str(e)}")
            return None
    
    def _load_node_types_from_directory(self) -> List[str]:
        """
        从目录扫描加载节点类型（原有逻辑）
        
        Returns:
            节点类型列表
        """
        if not os.path.exists(self.node_reference_dir):
            logger.warning(f"节点参考目录不存在: {self.node_reference_dir}")
            return []
        
        # 获取所有子目录名称作为节点类型
        node_types = [d for d in os.listdir(self.node_reference_dir) 
                     if os.path.isdir(os.path.join(self.node_reference_dir, d))]
        
        # 过滤掉以点开头的隐藏目录和常见的非节点目录
        excluded_dirs = {'.git', '.svn', '__pycache__', '.DS_Store'}
        node_types = [nt for nt in node_types if not nt.startswith('.') and nt not in excluded_dirs]
        
        logger.info(f"从目录扫描找到{len(node_types)}个可用节点类型")
        return node_types

    def read_node_reference(self, node_type: str, ref_type: str = "node", add_common_usage=True) -> str:
        """读取节点参考文件

        Args:
            node_type: 节点类型
            ref_type: 引用类型，"node" 或 "edge"
            add_common_usage: 是否添加通用使用规范，默认为True

        Returns:
            文件内容
        """
        return self._read_node_reference_v4(node_type, ref_type, add_common_usage)

    def _read_node_reference_v4(self, node_type: str, ref_type: str = "node", add_common_usage: bool = True) -> str:
        """读取节点参考文件 (v4版本逻辑)
        
        Args:
            node_type: 节点类型
            ref_type: 引用类型，"node" 或 "edge"
            add_common_usage: 是否添加通用使用规范，默认为True
            
        Returns:
            文件内容
        """
        try:
            if ref_type == "node":
                # v4版本node读取三个文件：usage, error, sample
                files_to_read = [NODE_USAGE_FILENAME, NODE_ERROR_FILENAME, NODE_SAMPLE_FILENAME]
            elif ref_type == "edge":
                # v4版本edge读取三个文件：usage, error, sample
                # files_to_read = [EDGE_USAGE_FILENAME, EDGE_ERROR_FILENAME, EDGE_SAMPLE_FILENAME]
                files_to_read = [EDGE_USAGE_FILENAME, EDGE_SAMPLE_FILENAME]
            else:
                logger.warning(f"未知的ref_type: {ref_type}")
                return ""
            
            # 读取多个文件内容到字典
            file_contents = {}
            for file_name in files_to_read:
                content = self._read_file_content(node_type, file_name)
                if content:
                    file_contents[file_name] = content
            
            desc =  self._generate_node_description_v4(node_type, ref_type, file_contents)

            if add_common_usage and ref_type == "node":
                common_usage = self._read_common_node_usage()
                if common_usage:
                    desc += f"\n{common_usage}"

            return desc

        except Exception as e:
            logger.error(f"读取节点参考文件失败 (v4): {str(e)}")
            raise FileServiceError(f"读取节点参考文件失败 (v4): {str(e)}")

    def _generate_node_description_v4(self, node_type: str, ref_type: str, file_contents: dict) -> str:
        """生成节点描述内容 (v4版本)
        
        Args:
            ref_type: 引用类型，"node" 或 "edge"
            file_contents: 文件内容字典，key为文件名，value为文件内容
            
        Returns:
            合并后的描述内容
        """
        if ref_type == "node":
            node_usage = file_contents.get(NODE_USAGE_FILENAME, "")
            node_error = file_contents.get(NODE_ERROR_FILENAME, "")
            node_sample = file_contents.get(NODE_SAMPLE_FILENAME, "")

            # 合并usage, error, sample内容
            desc = f"# node usage\n\n{node_usage} \n\n## node error\n\n{node_error} \n\n## node sample\n\n{node_sample}"
        else:
            # 合并usage, error, sample内容
            edge_usage = file_contents.get(EDGE_USAGE_FILENAME, "")
            # edge_error = file_contents.get(EDGE_ERROR_FILENAME, "")
            edge_sample = file_contents.get(EDGE_SAMPLE_FILENAME, "")
            # 合并usage, error, sample内容
            desc = f"# node type {node_type} ## {node_type}'s edge usage\n\n{edge_usage} \n\n## {node_type}'s edge sample\n\n{edge_sample}"

        return desc

    def _read_file_content(self, node_type: str, file_name: str) -> str:
        """读取单个文件内容
        
        Args:
            node_type: 节点类型
            file_name: 文件名
            
        Returns:
            文件内容
        """
        try:
            file_path = os.path.join(self.node_reference_dir, node_type, file_name)
            if not os.path.exists(file_path):
                logger.warning(f"节点参考文件不存在: {file_path}")
                return ""
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                content = self._get_node_reference_content(content)

            return content
        except Exception as e:
            logger.error(f"读取文件失败: {str(e)}")
            return ""
    
    def _get_node_reference_content(self, content: str) -> str:
        """
        读取节点参考文件（v2+版本）
        Args:
            content: 文件内容
        Returns:
            文件内容
        """
        
        try:
            data = yaml.safe_load(content)
            if not data:
                return ""
            if data.get("nodes"):
                nodes = data["nodes"][:NODE_RAG_TOP_K]
                return yaml.dump({"nodes": nodes}, allow_unicode=True, default_flow_style=False)
            elif data.get("edges"):
                edges = data["edges"][:EDGE_RAG_TOP_K]
                return yaml.dump({"edges": edges}, allow_unicode=True, default_flow_style=False)
            elif data.get("node_usage"):
                node_usage = data["node_usage"]
                return yaml.dump({"node_usage": node_usage}, allow_unicode=True, default_flow_style=False)
            elif data.get("edge_usage"):
                edge_usage = data["edge_usage"]
                return yaml.dump({"edge_usage": edge_usage}, allow_unicode=True, default_flow_style=False)
            elif data.get("node_error"):
                # node_sample = data["node_error"][:NODE_RAG_TOP_K]
                node_sample = data["node_error"]
                return yaml.dump({"node_error": node_sample}, allow_unicode=True, default_flow_style=False)
            elif data.get("edge_error"):
                edge_sample = data["edge_error"][:EDGE_RAG_TOP_K]
                return yaml.dump({"edge_error": edge_sample}, allow_unicode=True, default_flow_style=False)
            else:
                logger.warning(f"节点参考文件格式错误: {content}")
                return content
        except Exception as e:
            logger.warning(f"节点参考文件不是YAML格式: {content}")
            return content
    
    def read_node_list(self, select_node_types: Optional[List[str]] = None, add_common_usage: bool = True) -> Tuple[List[str], List[str]]:
        """
        读取节点列表
        Args:
            select_node_types: 要读取的节点类型列表，如果为None，则读取所有节点类型
            add_common_usage: 是否添加通用使用规范，默认为True
        Returns:
            节点描述列表
        """
        try:
            node_types = self.get_available_node_types()
            
            if not select_node_types:
                select_node_types = node_types

            node_list = []
            
            for node_type in select_node_types:
                node_description = self.read_node_reference(node_type, ref_type="edge", add_common_usage=False)
                if node_description:
                    node_list.append(node_description)
            
            if add_common_usage:
                common_edge_usage = self._read_common_edge_usage()
                if common_edge_usage:
                    node_list.append(common_edge_usage)

            return node_list, select_node_types
        except Exception as e:
            logger.error(f"读取节点列表失败: {str(e)}")
            raise FileServiceError(f"读取节点列表失败: {str(e)}")
    
    def _read_common_node_usage(self) -> str:
        """读取通用节点使用规范文件
        
        Returns:
            通用节点使用规范内容
        """
        try:
            file_path = os.path.join(self.node_reference_dir, COMMON_NODE_USAGE_FILENAME)
            if not os.path.exists(file_path):
                logger.warning(f"通用节点使用规范文件不存在: {file_path}")
                return ""
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 解析YAML格式
            try:
                data = yaml.safe_load(content)
                if data and data.get("common_node_usage"):
                    return f'# 通用节点规范：\n{data["common_node_usage"]}'
                else:
                    logger.warning(f"通用节点使用规范文件格式错误: {file_path}")
                    return f'# 通用节点规范: \n{content}'
            except yaml.YAMLError as e:
                logger.warning(f"通用节点使用规范文件不是有效的YAML格式: {e}")
                return f'# 通用节点规范: \n{content}'
                
        except Exception as e:
            logger.error(f"读取通用节点使用规范文件失败: {str(e)}")
            raise FileServiceError(f"读取通用节点使用规范文件失败: {str(e)}")
    
    def _read_common_edge_usage(self) -> str:
        """读取通用边使用规范文件
        
        Returns:
            通用边使用规范内容
        """
        try:
            file_path = os.path.join(self.node_reference_dir, COMMON_EDGE_USAGE_FILENAME)
            if not os.path.exists(file_path):
                logger.warning(f"通用边使用规范文件不存在: {file_path}")
                return ""
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 解析YAML格式
            try:
                data = yaml.safe_load(content)
                if data and data.get("common_edge_usage"):
                    return f'# 通用边生成规则: \n{data["common_edge_usage"]}'
                else:
                    logger.warning(f"通用边使用规范文件格式错误: {file_path}")
                    return f'# 通用边生成规则: \n{content}'
            except yaml.YAMLError as e:
                logger.warning(f"通用边使用规范文件不是有效的YAML格式: {e}")
                return content
                
        except Exception as e:
            logger.error(f"读取通用边使用规范文件失败: {str(e)}")
            raise FileServiceError(f"读取通用边使用规范文件失败: {str(e)}")

    def read_dsl(self, file_path: str) -> str:
        """
        读取DSL文件

        Args:
            file_name: 文件名

        Returns:
            文件内容
        """
        try:
            if not os.path.exists(file_path):
                logger.warning(f"DSL文件不存在: {file_path}")
                return ""

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"读取DSL文件失败: {str(e)}")
            raise FileServiceError(f"读取DSL文件失败: {str(e)}")
    
    def save_dsl(self, dsl_content: str, file_path: str) -> str:
        """
        保存DSL内容到文件
        
        Args:
            dsl_content: DSL内容
            file_name: 文件名，默认使用时间戳生成
            
        Returns:
            保存的文件路径
        """
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(dsl_content)
            
            logger.info(f"DSL已保存到: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"保存DSL失败: {str(e)}")
            raise FileServiceError(f"保存DSL失败: {str(e)}")

    def save_yaml(self, yaml_content: str | dict, file_path: str) -> str:
        """
        保存YAML内容到文件
        
        Args:
            yaml_content: YAML内容
            file_path: 文件路径
            
        Returns:
            保存的文件路径
        """
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(yaml.safe_dump(yaml_content, allow_unicode=True, default_flow_style=False))
            
            logger.info(f"YAML已保存到: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"保存YAML失败: {str(e)}")
            raise FileServiceError(f"保存YAML失败: {str(e)}")

    def _get_dsl_templates_with_desc_from_dir(self, template_dir) -> List[Dict[str, Any]]:
        """
        获取可用的DSL模板

        Args:
            template_dir: 模板目录

        Returns:
            List[Dict[str, Any]: 包含模板文件名的列表

        Raises:
        """
        try:
            templates = []
            desc_files = [f for f in os.listdir(template_dir) if f.endswith('.desc')]
            
            for desc_file in desc_files:
                base_name = desc_file[:-5]
                dsl_file = f"{base_name}.yml"
                dsl_path = os.path.join(template_dir, dsl_file)
                
                if not os.path.exists(dsl_path):
                    logger.warning(f"找不到对应的DSL文件: {dsl_file}")
                    continue
                
                try:
                    with open(os.path.join(template_dir, desc_file), 'r', encoding='utf-8') as f:
                        desc_content = f.read().strip()

                    with open(dsl_path, 'r', encoding='utf-8') as f:
                        dsl_content = f.read()

                    templates.append({
                        "desc": desc_content,
                        "dsl": dsl_content,
                        "dsl_path": dsl_path,
                    })
                except yaml.YAMLError as e:
                    logger.error(f"解析YAML文件失败 {dsl_file}: {str(e)}")
                    continue
                except (IOError, UnicodeDecodeError) as e:
                    logger.error(f"读取模板文件失败 {desc_file}: {str(e)}")
                    continue
            
            logger.info(f"从 {template_dir} 成功加载 {len(templates)} 个DSL模板")
            return templates
            
        except Exception as e:
            error_msg = f"从 {template_dir} 获取DSL模板失败: {str(e)}"
            logger.error(error_msg)
            raise FileServiceError(error_msg)

    def _load_dsl_template_types_from_config(self) -> List[str]:
        """
        从配置文件中加载DSL模板类型列表
        
        Returns:
            List[str]: DSL模板类型列表，如果配置文件不存在或解析失败则返回空列表
        """
        try:
            if not os.path.exists(DSL_TEMPLATE_TYPES_CONFIG_PATH):
                logger.warning(f"DSL模板类型配置文件不存在: {DSL_TEMPLATE_TYPES_CONFIG_PATH}")
                return [self.dsl_template_dir]
            
            with open(DSL_TEMPLATE_TYPES_CONFIG_PATH, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
            
            if not isinstance(config, dict):
                logger.error(f"DSL模板类型配置文件格式错误，应为字典格式: {DSL_TEMPLATE_TYPES_CONFIG_PATH}")
                return []
            
            template_types = config.get('template_types', [])
            if not isinstance(template_types, list):
                logger.error(f"DSL模板类型配置文件中的template_types应为列表格式: {DSL_TEMPLATE_TYPES_CONFIG_PATH}")
                return []
            
            logger.info(f"成功从配置文件加载 {len(template_types)} 个DSL模板类型")
            return [os.path.join(self.dsl_template_dir, template_type) for template_type in template_types]
            
        except yaml.YAMLError as e:
            logger.error(f"解析DSL模板类型配置文件失败: {e}")
            return []
        except Exception as e:
            logger.error(f"加载DSL模板类型配置文件时发生错误: {e}")
            return []

    def get_dsl_templates_with_desc(self) -> List[Dict[str, Any]]:
        """
        获取可用的DSL模板及其描述
        
        Returns:
            List[Dict[str, Any]]: 包含模板描述和DSL内容的列表
                每个字典包含两个键：
                - desc: 模板描述内容
                - dsl: DSL模板内容（YAML格式的字典）
        
        Raises:
            FileServiceError: 当读取模板文件失败时抛出
        """
        template_dirs = self._load_dsl_template_types_from_config()
        templates = []

        for template_dir in template_dirs:
            templates.extend(self._get_dsl_templates_with_desc_from_dir(template_dir))

        return templates
    