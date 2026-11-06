from typing import List, Dict, Any, Optional, Tuple, Set



from dataclasses import dataclass
from langchain_core.documents import Document

from chatdify.services.file_service import FileService
from chatdify.services.vector_service import ScoreAggregationStrategy, VectorConfig, VectorService
from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import FileServiceError, VectorStoreError
from chatdify.paths import NODE_REFERENCE_DIR
from chatdify.settings import get_settings


logger = get_logger(__name__)


class NodeSelectorConstants:
    """节点选择器常量"""
    DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "；", "，", " ", ""]
    MIN_BATCH_SIZE = 1  # 降低最小批次大小
    DEFAULT_NODES = {"start", "end", "answer", "llm", "code", "if-else", "parameter-extractor"}
    DEPENDENCY_PAIRS = {
        ("loop", "loop-start"),
        ("iteration", "iteration-start")
    }
    
    
class IntentAnalyzer:
    """用户意图分析器"""
    
    INTENT_KEYWORDS = {
        'qa': ['问答', '回答', '对话', 'chat', 'answer'],
        'search': ['搜索', '检索', '查找', 'search', 'find', 'retrieval'],
        'condition': ['判断', '条件', '分支', 'if', 'condition'],
        'code': ['代码', '执行', 'code', 'python', 'execute'],
        'api': ['api', '请求', 'http', 'request']
    }
    
    NODE_MAPPINGS = {
        'qa': ['llm', 'answer'],
        'search': ['knowledge-retrieval'],
        'condition': ['if-else'],
        'code': ['code'],
        'api': ['http-request']
    }
    
    @classmethod
    def analyze(cls, user_query: str) -> List[str]:
        """分析用户查询意图"""
        query_lower = user_query.lower()
        suggestions = []
        
        for intent, keywords in cls.INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                suggestions.extend(cls.NODE_MAPPINGS.get(intent, []))
                
        return suggestions


@dataclass
class NodeRetrievalConfig:
    """节点召回配置"""
    node_reference_path: str = NODE_REFERENCE_DIR
    top_k: int = 20
    similarity_threshold: float = 0
    score_aggregation_strategy: ScoreAggregationStrategy = ScoreAggregationStrategy.MIN
    top_k_for_aggregation: int = 3  # 用于TOP_K_MEAN策略
    retrieval_multiplier: int = 3  # 检索候选数量倍数
    
    # 向量服务配置
    vector_config: Optional[VectorConfig] = None
    
    def __post_init__(self) -> None:
        """配置验证"""
        if self.vector_config is None:
            self.vector_config = VectorConfig(
                top_k=self.top_k,
                score_aggregation_strategy=self.score_aggregation_strategy,
                top_k_for_aggregation=self.top_k_for_aggregation,
                retrieval_multiplier=self.retrieval_multiplier
            )
        self.validate()
    
    def validate(self) -> None:
        """验证配置参数"""
        validations = [
            (self.top_k > 0, "top_k必须大于0"),
        ]
        
        for condition, message in validations:
            if not condition:
                raise ValueError(message)


class NodeSelector:
    """根据用户需求召回相关节点"""
    
    def __init__(self, 
                 config: Optional[NodeRetrievalConfig] = None,
                 file_service: Optional[FileService] = None,
                 vector_service: Optional[VectorService] = None):
        """
        初始化节点选择器
        
        Args:
            config: 召回配置
            file_service: 文件服务实例
            vector_service: 向量服务实例
        """
        self.config = config or NodeRetrievalConfig()
        self.file_service = file_service or FileService()
        self.vector_service = vector_service or VectorService(config=self.config.vector_config)
        
        # 初始化组件
        self.vector_store = None
        self.node_metadata: Dict[str, Dict[str, Any]] = {}
        self._initialized = False
        
        logger.info(f"NodeSelector初始化，配置: {self.config}")
    
    def _ensure_initialized(self) -> None:
        """确保召回器已初始化"""
        if self._initialized:
            return
            
        embedding_dir = str(get_settings().node_reference_embedding_dir)

        # 先尝试加载现有的向量存储
        try:
            self.vector_store = self.vector_service.load_vector_store(embedding_dir)
            self._initialized = True
            return
        except Exception as e:
            logger.error(f"加载节点召回器向量存储失败: {e}")

        # 如果加载失败，重新创建
        documents = self._load_node_documents()
        
        if not documents:
            raise VectorStoreError("未找到任何节点文档")

        self.vector_store = self.vector_service.create_vector_store(
            documents, 
            save_path=embedding_dir
        )
        self._initialized = True
        logger.info("节点召回器初始化完成")
    
    def _load_node_documents(self) -> List[Document]:
        """使用FileService加载所有节点文档"""
        documents = []
        
        try:
            # 获取可用节点类型
            node_types = self.file_service.get_available_node_types()
            logger.info(f"发现 {len(node_types)} 个节点类型")
            
            for node_type in node_types:
                try:
                    node_content = self._extract_node_content(node_type)
                    
                    if node_content:
                        # 创建文档
                        doc = Document(
                            page_content=node_content['content'],
                            metadata={'node_type': node_type}
                        )
                        documents.append(doc)
                        
                        # 保存节点元数据
                        self.node_metadata[node_type] = node_content
                        
                except Exception as e:
                    logger.warning(f"加载节点 {node_type} 失败: {e}")
                    continue
            
            logger.info(f"成功加载 {len(documents)} 个节点文档")
            return documents
            
        except Exception as e:
            logger.error(f"加载节点文档失败: {e}")
            raise FileServiceError(f"加载节点文档失败: {e}")

    def _extract_node_content(self, node_type: str) -> Optional[Dict[str, Any]]:
        """使用FileService提取节点内容信息"""
        try:
            content_parts = []
            
            # 使用FileService读取节点参考信息
            node_usage = self.file_service.read_node_reference(node_type, "node", add_common_usage=False)
            if node_usage:
                content_parts.append(f"节点使用规范:\n{node_usage}")
                
            # 读取边信息（包含用例）
            edge_info = self.file_service.read_node_reference(node_type, "edge", add_common_usage=False)
            if edge_info:
                content_parts.append(f"节点连接和用例:\n{edge_info}")
            
            if not content_parts:
                return None
                
            return {'content': '\n\n'.join(content_parts)}
            
        except Exception as e:
            logger.error(f"提取节点内容失败 {node_type}: {e}")
            return None
    
    def _aggregate_node_scores(self, node_type: str, docs_scores: List[Tuple[Document, float]]) -> Optional[Dict[str, Any]]:
        """聚合同一节点的多个文档得分"""
        if not docs_scores:
            return None
        
        # 使用向量服务的聚合功能
        aggregated_result = self.vector_service.aggregate_scores(
            docs_scores, 
            self.config.score_aggregation_strategy
        )
        
        if not aggregated_result:
            return None
        
        return {
            'node_type': node_type,
            'relevance_score': aggregated_result['aggregated_score'],
            'chunk_count': aggregated_result['chunk_count'],
            'individual_scores': aggregated_result['individual_scores'],
        }

    def retrieve_nodes(self, user_query: str) -> List[Dict[str, Any]]:
        """根据用户查询召回相关节点和相关信息"""
        self._ensure_initialized()
        
        # 验证向量存储已初始化
        if self.vector_store is None:
            raise VectorStoreError("向量存储未初始化")
        
        # 使用向量服务进行检索
        retrieved_docs = self.vector_service.search_similar_documents(
            self.vector_store, 
            user_query
        )
        
        # 按node_type分组收集所有相关文档
        node_docs_map: Dict[str, List[Tuple[Document, float]]] = {}
        for doc, score in retrieved_docs:
            node_type = doc.metadata.get('node_type')
            if node_type:
                if node_type not in node_docs_map:
                    node_docs_map[node_type] = []
                node_docs_map[node_type].append((doc, score))
        
        # 为每个节点计算综合得分
        aggregated_results = []
        for node_type, docs_scores in node_docs_map.items():
            aggregated_node = self._aggregate_node_scores(node_type, docs_scores)
            if aggregated_node:
                aggregated_results.append(aggregated_node)
        
        return aggregated_results

    def _ensure_node_dependencies(self, node_types: Set[str]) -> Set[str]:
        """确保节点依赖关系完整"""
        for primary, secondary in NodeSelectorConstants.DEPENDENCY_PAIRS:
            if primary in node_types or secondary in node_types:
                node_types.update([primary, secondary])
        return node_types

    def get_selected_node(self, user_query: str) -> List[str]:
        """获取节点推荐结果"""
        try:
            # 检索相关节点
            nodes = self.retrieve_nodes(user_query)
            
            # 按相关性得分排序并限制数量
            top_nodes = sorted(nodes, key=lambda x: x.get('relevance_score', 0))[:self.config.top_k]
            
            self._log_top_retrieve(top_nodes)
            
            # 合并推荐结果
            node_types = set()
            node_types.update(node['node_type'] for node in top_nodes)
            node_types.update(IntentAnalyzer.analyze(user_query))
            node_types.update(NodeSelectorConstants.DEFAULT_NODES)
            
            # 确保依赖关系完整
            self._ensure_node_dependencies(node_types)
        
            logger.info(f"最终推荐节点列表: {node_types}")
        
            return list(node_types)
        
        except Exception as e:
            logger.error(f"获取节点推荐结果时发生错误: {str(e)}")
            return []
    
    def _log_top_retrieve(self, top_nodes: List[Dict[str, Any]]) -> None:
        """记录检索日志"""
        if not top_nodes:
            logger.info("未检索到相关节点")
            return
            
        logger.info(f"找到 {len(top_nodes)} 个节点:")
        for i, node in enumerate(top_nodes, 1):
            score = node.get('relevance_score', 0)
            chunk_count = node.get('chunk_count', 1)
            logger.info(f"{i}. {node['node_type']} (得分: {score:.3f}, 片段: {chunk_count})")
            
            # 详细得分信息（调试模式）
            if 'individual_scores' in node:
                scores_str = ', '.join(f'{s:.3f}' for s in node['individual_scores'][:3])
                logger.info(f"   各片段得分: [{scores_str}...]")



