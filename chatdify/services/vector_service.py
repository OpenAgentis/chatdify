from typing import List, Dict, Any, Optional, Tuple
import os
from dataclasses import dataclass
from enum import Enum
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from chatdify.settings import get_settings
from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import EmbeddingInitializationError, VectorStoreError
from .token_stats import get_tokenizer, count_tokens

logger = get_logger(__name__)


class ScoreAggregationStrategy(Enum):
    """得分聚合策略"""
    MIN = "min"  # 取最小值
    MEAN = "mean"  # 取平均值
    TOP_K_MEAN = "top_k_mean"  # 取前K个的平均值


@dataclass
class VectorConfig:
    """向量服务配置"""
    embedding_model: Optional[str] = None
    embedding_provider: str = "siliconflow"  # siliconflow 或 huggingface
    top_k: int = 20
    chunk_size: int = 4000
    chunk_overlap: int = 100
    similarity_threshold: float = 0
    score_aggregation_strategy: ScoreAggregationStrategy = ScoreAggregationStrategy.MIN
    top_k_for_aggregation: int = 3  # 用于TOP_K_MEAN策略
    retrieval_multiplier: int = 3  # 检索候选数量倍数
    batch_size: int = 16  # 批处理大小
    max_tokens_per_chunk: int = 6000  # 每个chunk的最大token数
    max_query_tokens: int = 6000  # 查询的最大token数
    default_separators: List[str] = None
    min_batch_size: int = 1
    
    def __post_init__(self) -> None:
        """配置验证"""
        if self.default_separators is None:
            self.default_separators = ["\n\n", "\n", "。", "；", "，", " ", ""]
        if self.embedding_model is None:
            self.embedding_model = get_settings().embedding_model
        self.validate()
    
    def validate(self) -> None:
        """验证配置参数"""
        validations = [
            (self.top_k > 0, "top_k必须大于0"),
            (self.chunk_size > 0, "chunk_size必须大于0"),
            (self.batch_size > 0, "batch_size必须大于0"),
            (self.max_tokens_per_chunk > 0, "max_tokens_per_chunk必须大于0"),
            (self.max_query_tokens > 0, "max_query_tokens必须大于0"),
        ]
        
        for condition, message in validations:
            if not condition:
                raise ValueError(message)


class VectorService:
    """向量服务，封装向量存储的创建、管理和检索功能"""
    
    def __init__(self, 
                 config: Optional[VectorConfig] = None
                 ):
        """
        初始化向量服务
        
        Args:
            config: 向量服务配置
            llm_service: LLM服务实例，用于token计算
        """
        self.config = config or VectorConfig()
    
        # 初始化嵌入模型
        self.embeddings = self._initialize_embeddings()

        # # 初始化tokenizer用于token计数
        self.tokenizer = get_tokenizer(self.config.embedding_model)
        
        logger.info(f"VectorService初始化完成，配置: {self.config}")
    
    def _initialize_embeddings(self) -> Embeddings:
        """初始化嵌入模型"""
        try:
            settings = get_settings()
            if not (settings.embedding_api_key and settings.embedding_base_url and self.config.embedding_model):
                raise EmbeddingInitializationError(
                    "未配置嵌入模型，请设置 embedding_model / embedding_base_url / embedding_api_key"
                )

            return OpenAIEmbeddings(
                model=self.config.embedding_model,
                api_key=SecretStr(settings.embedding_api_key),
                base_url=settings.embedding_base_url,
            )

        except Exception as e:
            logger.error(f"嵌入模型初始化失败: {e}")
            raise EmbeddingInitializationError(f"嵌入模型初始化失败: {e}")
    
    def estimate_tokens(self, text: str) -> int:
        """估算文本的token数量"""
        return count_tokens(text, self.tokenizer)
    
    def validate_and_split_text(self, text: str, max_tokens: Optional[int] = None) -> List[str]:
        """验证并分割文本以确保不超过token限制"""
        if max_tokens is None:
            max_tokens = self.config.max_tokens_per_chunk
        
        token_count = self.estimate_tokens(text)
        
        if token_count <= max_tokens:
            return [text]
        
        # 如果超过限制，按句子分割
        sentences = []
        for separator in ["。", "！", "？", "\n\n", "\n"]:
            if separator in text:
                sentences = text.split(separator)
                break
        
        if not sentences:
            # 如果没有合适的分隔符，按字符强制分割
            char_limit = max_tokens * 3  # 粗略估算字符限制
            sentences = [text[i:i+char_limit] for i in range(0, len(text), char_limit)]
        
        # 重新组合句子，确保每个片段不超过token限制
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if not sentence.strip():
                continue
                
            test_chunk = current_chunk + sentence + ("。" if not sentence.endswith(("。", "！", "？")) else "")
            
            if self.estimate_tokens(test_chunk) <= max_tokens:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    # 单个句子就超过限制，强制截断
                    char_limit = max_tokens * 3
                    chunks.append(sentence[:char_limit])
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return [chunk for chunk in chunks if chunk.strip()]
    
    def preprocess_query(self, user_query: str) -> str:
        """预处理查询以确保不超过token限制"""
        token_count = self.estimate_tokens(user_query)
        max_tokens = self.config.max_query_tokens
        
        if token_count <= max_tokens:
            return user_query
        
        logger.warning(f"查询token数量({token_count})超过限制({max_tokens})，进行截断")
        
        # 智能截断：优先保留句子完整性
        sentences = []
        for separator in ["。", "！", "？", "\n", "，", "；"]:
            if separator in user_query:
                sentences = user_query.split(separator)
                break
        
        if not sentences:
            # 没有合适分隔符，按字符截断
            char_limit = max_tokens * 3  # 粗略估算
            return user_query[:char_limit]
        
        # 逐句添加，直到接近token限制
        truncated_query = ""
        for sentence in sentences:
            if not sentence.strip():
                continue
                
            test_query = truncated_query + sentence + "。"
            if self.estimate_tokens(test_query) <= max_tokens:
                truncated_query = test_query
            else:
                break
        
        if not truncated_query:
            # 如果第一句就超过限制，强制截断
            char_limit = max_tokens * 3
            truncated_query = user_query[:char_limit]
        
        logger.info(f"查询已截断为: {truncated_query[:100]}...")
        return truncated_query.strip()
    
    def create_vector_store(self, documents: List[Document], save_path: Optional[str] = None) -> FAISS:
        """创建向量存储"""
        if not documents:
            raise VectorStoreError("没有文档可以创建向量存储")
        
        if self.embeddings is None:
            raise EmbeddingInitializationError("嵌入模型未初始化")
        
        # 文本分割，考虑token限制
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=self.config.default_separators
        )
        
        split_docs = text_splitter.split_documents(documents)
        logger.info(f"文档分割完成，共 {len(split_docs)} 个片段")
        
        # 验证和进一步分割文档以确保token限制
        validated_docs = []
        for doc in split_docs:
            text_chunks = self.validate_and_split_text(doc.page_content)
            for chunk in text_chunks:
                validated_doc = Document(
                    page_content=chunk,
                    metadata=doc.metadata
                )
                validated_docs.append(validated_doc)
        
        logger.info(f"Token验证完成，最终文档片段数: {len(validated_docs)}")
        
        # 创建向量存储
        vector_store = self._create_vector_store_with_batching(validated_docs)
        logger.info("向量存储创建完成")
        
        # 保存向量存储
        if save_path:
            # 确保目录存在
            os.makedirs(save_path, exist_ok=True)
            vector_store.save_local(save_path)
            logger.info(f"向量存储保存到: {save_path}")
        
        return vector_store
    
    def load_vector_store(self, load_path: str) -> FAISS:
        """加载向量存储"""
        try:
            vector_store = FAISS.load_local(load_path, self.embeddings, allow_dangerous_deserialization=True)
            logger.info(f"向量存储加载完成: {load_path}")
            return vector_store
        except Exception as e:
            logger.error(f"加载向量存储失败: {e}")
            raise VectorStoreError(f"加载向量存储失败: {e}")
    
    def _create_vector_store_with_batching(self, split_docs: List[Document]) -> FAISS:
        """分批创建向量存储以避免API限制"""
        if not split_docs:
            raise VectorStoreError("没有文档可以创建向量存储")
        
        if self.embeddings is None:
            raise EmbeddingInitializationError("嵌入模型未初始化")
        
        batch_size = self.config.batch_size
        logger.info(f"开始分批创建向量存储，总文档数: {len(split_docs)}, 批次大小: {batch_size}")
        
        # 创建第一个批次的向量存储
        first_batch = split_docs[:batch_size]
        
        # 验证第一批次的token数量
        first_batch = self._validate_batch_tokens(first_batch)
        
        vector_store = FAISS.from_documents(first_batch, self.embeddings)
        logger.info(f"第一批次完成，处理了 {len(first_batch)} 个文档")
        
        # 处理剩余批次
        for i in range(batch_size, len(split_docs), batch_size):
            batch = split_docs[i:i + batch_size]
            
            # 验证批次token数量
            batch = self._validate_batch_tokens(batch)
            
            if not batch:  # 如果批次为空，跳过
                continue
                
            batch_texts = [doc.page_content for doc in batch]
            batch_metadatas = [doc.metadata for doc in batch]
            
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    # 为当前批次生成嵌入
                    batch_embeddings = self.embeddings.embed_documents(batch_texts)
                    
                    # 添加到现有向量存储
                    vector_store.add_texts(
                        texts=batch_texts,
                        metadatas=batch_metadatas,
                        embeddings=batch_embeddings
                    )
                    
                    logger.info(f"批次 {i//batch_size + 1} 完成，处理了 {len(batch)} 个文档")
                    break
                    
                except Exception as e:
                    error_msg = str(e).lower()
                    if "512 tokens" in error_msg or "token" in error_msg:
                        logger.warning(f"批次 {i//batch_size + 1} token限制错误: {e}")
                        
                        # 进一步减小批次或跳过问题文档
                        if batch_size > self.config.min_batch_size:
                            batch_size = max(self.config.min_batch_size, batch_size // 2)
                            logger.info(f"减小批次大小到: {batch_size}")
                            # 重新处理当前批次
                            batch = split_docs[i:i + batch_size]
                            batch = self._validate_batch_tokens(batch)
                            batch_texts = [doc.page_content for doc in batch]
                            batch_metadatas = [doc.metadata for doc in batch]
                        else:
                            # 跳过有问题的文档
                            logger.warning(f"跳过有问题的批次: {i//batch_size + 1}")
                            break
                    else:
                        logger.error(f"处理批次 {i//batch_size + 1} 时出错: {e}")
                        if retry_count == max_retries - 1:
                            raise VectorStoreError(f"批次处理失败: {e}")
                    
                    retry_count += 1
        
        logger.info(f"向量存储创建完成，总共处理了 {len(split_docs)} 个文档")
        return vector_store
    
    def _validate_batch_tokens(self, batch: List[Document]) -> List[Document]:
        """验证批次中每个文档的token数量"""
        validated_batch = []
        
        for doc in batch:
            token_count = self.estimate_tokens(doc.page_content)
            
            if token_count <= self.config.max_tokens_per_chunk:
                validated_batch.append(doc)
            else:
                logger.warning(f"文档token数量({token_count})超过限制，进行分割")
                # 分割文档
                text_chunks = self.validate_and_split_text(doc.page_content)
                for chunk in text_chunks:
                    validated_doc = Document(
                        page_content=chunk,
                        metadata=doc.metadata
                    )
                    validated_batch.append(validated_doc)
        
        return validated_batch
    
    def search_similar_documents(self, 
                               vector_store: FAISS, 
                               query: str, 
                               k: Optional[int] = None) -> List[Tuple[Document, float]]:
        """在向量存储中搜索相似文档"""
        if vector_store is None:
            raise VectorStoreError("向量存储未初始化")
        
        # 预处理查询
        processed_query = self.preprocess_query(query)
        
        # 使用配置的k值或默认值
        search_k = k or (self.config.top_k * self.config.retrieval_multiplier)
        
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                retrieved_docs = vector_store.similarity_search_with_score(processed_query, k=search_k)
                return retrieved_docs
            except Exception as e:
                error_msg = str(e).lower()
                if "token" in error_msg:
                    logger.warning(f"检索时token限制错误: {e}")
                    # 进一步缩短查询
                    current_tokens = self.estimate_tokens(processed_query)
                    new_max_tokens = max(100, current_tokens // 2)
                    processed_query = self.preprocess_query(processed_query)[:new_max_tokens * 3]
                    logger.info(f"进一步缩短查询，新长度: {len(processed_query)}")
                else:
                    logger.error(f"检索失败: {e}")
                    if retry_count == max_retries - 1:
                        raise VectorStoreError(f"检索失败: {e}")
                
                retry_count += 1
        
        return []
    
    def aggregate_scores(self, 
                       docs_scores: List[Tuple[Document, float]], 
                       strategy: Optional[ScoreAggregationStrategy] = None) -> Dict[str, Any]:
        """聚合文档得分"""
        if not docs_scores:
            return {}
        
        # 距离越小，相似度越高
        similarity_scores = [score for doc, score in docs_scores]
        
        # 根据策略计算综合得分
        strategy = strategy or self.config.score_aggregation_strategy
        if strategy == ScoreAggregationStrategy.MIN:
            aggregated_score = min(similarity_scores)
        elif strategy == ScoreAggregationStrategy.MEAN:
            aggregated_score = sum(similarity_scores) / len(similarity_scores)
        elif strategy == ScoreAggregationStrategy.TOP_K_MEAN:
            # 取前K个最低得分的平均值
            top_k = min(self.config.top_k_for_aggregation, len(similarity_scores))
            top_scores = sorted(similarity_scores, reverse=False)[:top_k]
            aggregated_score = sum(top_scores) / len(top_scores)
        else:
            aggregated_score = min(similarity_scores)  # 默认使用最小值
        
        return {
            'aggregated_score': aggregated_score,
            'chunk_count': len(docs_scores),  # 记录文档片段数量
            'individual_scores': similarity_scores,  # 保留各个片段的得分
        }