"""
DSL推荐模块
"""
from typing import List, Dict, Any, Optional
import re
import yaml
import pickle
import numpy as np
from openai import OpenAI
import os
import time
from chatdify.services.llm_service import LLMService
from chatdify.services.file_service import FileService
from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import DslRecommendError
from chatdify.settings import get_settings

logger = get_logger(__name__)

# ================================
# Embeddings
# ================================

def get_detailed_instruct(task_description: str, query: str) -> str:
    return f'Instruct: {task_description}\nQuery:{query}'

def get_text_embeddings(texts: List[str], url: str, api_key: str, model_name=None, proxy=None,
                        cache_path: Optional[str] = None, instruction: str = None, is_query: bool = False, 
                        batch_size: int = 64, additional_data: Optional[List[Dict]] = None) -> tuple:
    """
    获取模型的嵌入向量
    
    Args:
        texts: 输入文本列表（每个文本≤8192 tokens）
        url: API基础URL  
        api_key: API密钥
        proxy: 代理地址
        cache_path: 缓存路径，如果提供则会尝试加载/保存缓存
        instruction: 指令文本
        is_query: 是否为查询模式
        batch_size: 批处理大小，默认64
        additional_data: 额外数据列表，包含desc、dsl、dsl_path等信息
        
    Returns:
        如果additional_data为None: np.ndarray: 形状为(len(texts), 1024)的嵌入向量数组
        如果additional_data不为None: tuple: (embeddings, descs, dsls, dsl_paths)
    """
    # 如果提供了cache_path，尝试从缓存加载
    if cache_path is not None:
        cache_file = os.path.join(cache_path, "index.pkl")
        
        # 尝试加载缓存
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)
                    if additional_data is not None:
                        # 返回包含完整信息的缓存数据
                        return cached_data
                    else:
                        if isinstance(cached_data, tuple):
                            return cached_data[0]  # 返回embeddings部分
                        else:
                            raise ValueError("缓存格式不匹配")
            except Exception as e:
                logger.error(f"加载缓存文件失败: {e}")
    
    # 预处理文本（添加instruction）
    processed_texts = texts.copy()
    if instruction is not None:
        if is_query:
            processed_texts = [get_detailed_instruct(instruction, text) for text in texts]
        else:
            processed_texts = [instruction + text for text in texts]

    # 计算embedding（分批处理）
    if proxy:
        import httpx
        http_client = httpx.Client(proxy=proxy) 
        logger.info(f"使用代理: {proxy}")
        client = OpenAI(
            api_key=api_key,
            base_url=url,
            http_client=http_client
        )
    else:
        client = OpenAI(
            api_key=api_key,
            base_url=url
        )

    all_embeddings = []
    
    for i in range(0, len(processed_texts), batch_size):
        batch_texts = processed_texts[i:i + batch_size]        
        resp = client.embeddings.create(
            model=model_name,
            input=batch_texts,
        )
        
        # 提取当前批次的embeddings
        batch_embeddings = [item.embedding for item in resp.data]
        all_embeddings.extend(batch_embeddings)
    
    # 将list[list[float]]转换为np.ndarray用于后续数值操作
    embeddings = np.asarray(all_embeddings, dtype=np.float32)

    if "doubao" in model_name.lower():
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

    logger.info('使用{}获取embedding: {}'.format(model_name, embeddings.shape))
    
    # 准备要保存的数据
    if additional_data is not None:
        # 提取additional_data中的信息
        descs = [item.get("desc", "") for item in additional_data]
        dsls = [item.get("dsl", "") for item in additional_data]
        dsl_paths = [item.get("dsl_path", "") for item in additional_data]
        
        cache_data = (embeddings, descs, dsls, dsl_paths)
    else:
        cache_data = None
    
    # only save cache when cache_data is not None
    if cache_path is not None and cache_data is not None:
        os.makedirs(cache_path, exist_ok=True)  # 确保目录存在
        cache_file = os.path.join(cache_path, "index.pkl")
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
        except Exception as e:
            logger.error(f"保存缓存文件失败: {e}")
    
    if additional_data is not None:
        return cache_data
    else:
        return embeddings


# ================================
# PROMPT IMPORTS
# ================================
from chatdify.prompts.dslrec_prompts import (
    SYSTEM_PROMPT_BASE,
    USER_INTENT_REWRITE_PROMPT,
    GENERATE_CANDIDATES_PROMPT,
    RECOMMEND_DSL_PROMPT,
    REVISE_NODE_CONFIG_PROMPT,
    INTERPRET_DSL_PROMPT,
)


class DslRecommender:
    """DSL推荐器，用于根据用户需求推荐和生成合适的DSL模板"""
    
    def __init__(self, llm_service: LLMService, file_service: FileService):
        """
        初始化DSL推荐器
        
        Args:
            llm_service: LLM服务
            file_service: 文件服务  
            dsl_version: DSL模板版本，支持 "v1" 或 "v2"，默认v1
        """
        self.llm_service = llm_service
        self.file_service = file_service
        self._nodes_desc: str = ""
        self._dsl_templates: List[str] = []
        logger.info("DSL推荐器初始化完成")

    def rewrite_user_intent(self, user_intent: str) -> Dict[str, Any]:
        """用户意图重写，将用户需求转换为节点和流程描述"""
        if not self._nodes_desc:
            nodes_list, _ = self.file_service.read_node_list()
            
            self._nodes_desc = "\n".join(nodes_list)
        try:
            ret = self.llm_service.generate(
                system_prompt=SYSTEM_PROMPT_BASE,
                user_prompt=USER_INTENT_REWRITE_PROMPT,
                variables={
                    "nodes_desc": self._nodes_desc,
                    "requirement": user_intent
                }
            )

            return load_json_from_text(ret)

        except Exception as e:
            logger.error(f"重写用户意图失败: {str(e)}")
            raise DslRecommendError(f"重写用户意图失败: {str(e)}")

    def generate_candidates(
        self, 
        dsl_desc: List[str], 
        user_request: str,
        nodes_desc: str,
        process_desc: str,
        topk: int = 3
    ) -> List[int]:
        """生成候选DSL模板"""
        try:
            desc = "\n".join([f"第 {idx} 个Dify Dsl功能描述如下:\n{dsl}\n" for idx, dsl in enumerate(dsl_desc)])
            
            result = self.llm_service.generate(
                system_prompt=SYSTEM_PROMPT_BASE,
                user_prompt=GENERATE_CANDIDATES_PROMPT,
                variables={
                    "dify_dsl_template_desc": desc,
                    "nodes_desc": nodes_desc,
                    "process_desc": process_desc,
                    "topk": topk,
                    "requirement": user_request
                }
            )

            result = load_json_from_text(result)
            return result["candidate_list"]
        except Exception as e:
            logger.error(f"生成高级候选DSL模板失败: {str(e)}")
            raise DslRecommendError(f"生成高级候选DSL模板失败: {str(e)}")

    def recommend_dsl(
        self,
        dsl_templates: List[str],
        user_request: str,
        nodes_desc: str,
        process_desc: str
    ) -> int:
        """推荐DSL模板"""
        try:
            desc = "\n".join([f"第 {idx} 个Dify Dsl候选模版内容如下：\n{dsl}\n" for idx, dsl in enumerate(dsl_templates)])
            
            result = self.llm_service.generate(
                system_prompt=SYSTEM_PROMPT_BASE,
                user_prompt=RECOMMEND_DSL_PROMPT,
                variables={
                    "dify_dsl_template_desc": desc,
                    "nodes_desc": nodes_desc,
                    "process_desc": process_desc,
                    "requirement": user_request
                }
            )
            return int(result)
        except Exception as e:
            logger.error(f"推荐高级DSL模板失败: {str(e)}")
            raise DslRecommendError(f"推荐高级DSL模板失败: {str(e)}")

    def revise_node_config(self, dsl_template: str, requirement: str, nodes_config: str) -> Dict:
        """修改节点配置"""
        try:
            result = self.llm_service.generate(
                system_prompt=SYSTEM_PROMPT_BASE,
                user_prompt=REVISE_NODE_CONFIG_PROMPT,
                variables={
                    "dsl_template": dsl_template,
                    "nodes_config": nodes_config,
                    "requirement": requirement
                }
            )
            
            # 解析YAML内容
            pattern = re.compile(r'^```yaml\s*\n(.*?)\n```\s*$', re.DOTALL)
            match = pattern.search(result.strip())
            if not match:
                raise DslRecommendError("字符串格式无效，未找到YAML代码块")
                
            try:
                return yaml.safe_load(match.group(1))
            except yaml.YAMLError as e:
                raise DslRecommendError(f"YAML解析失败: {str(e)}")
                
        except Exception as e:
            logger.error(f"修改节点配置失败: {str(e)}")
            raise DslRecommendError(f"修改节点配置失败: {str(e)}")

    def interpret_dsl(self, dsl: str) -> str:
        """解释DSL工作流"""
        try:
            return self.llm_service.generate(
                system_prompt=SYSTEM_PROMPT_BASE,
                user_prompt=INTERPRET_DSL_PROMPT,
                variables={"dsl": dsl}
            )
        except Exception as e:
            logger.error(f"解释DSL工作流失败: {str(e)}")
            raise DslRecommendError(f"解释DSL工作流失败: {str(e)}")

    def _compute_similarity(self, embeddings: np.ndarray, query_embedding: np.ndarray) -> np.ndarray:
        """
        计算查询向量与文档向量的相似度
        
        Args:
            embeddings: 文档嵌入矩阵，形状为 (n_docs, embedding_dim)
            query_embedding: 查询嵌入向量，形状为 (embedding_dim,)
            
        Returns:
            np.ndarray: 相似度分数数组
        """
        return np.dot(embeddings, query_embedding)

    def recommend_dsl_with_embeddings(
        self, 
        user_request: str, 
        url: str, 
        api_key: str, 
        k_retrieve: int = 10,
        k_final: int = 1
    ) -> List[str]:
        """两阶段检索：BGE-M3 recall → DSLRec rerank"""
        settings = get_settings()
        cache_dir = str(settings.dsl_embedding_cache_dir)

        # 步骤1: 加载数据
        step_start = time.perf_counter()
        cache_file = os.path.join(cache_dir, "index.pkl")
        use_cache = False
        cached_embeddings = None
        cached_descs = None
        cached_dsls = None
        cached_dsl_paths = None
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)
                    if isinstance(cached_data, tuple) and len(cached_data) == 4:
                        cached_embeddings, cached_descs, cached_dsls, cached_dsl_paths = cached_data
                        use_cache = True
                    else:
                        logger.info("缓存格式不匹配，将重新生成")
            except Exception as e:
                logger.error(f"加载缓存失败: {e}")
        
        if use_cache:
            # 使用缓存数据
            embeddings = cached_embeddings
            dsl_desc = cached_descs
            dsl_templates = [{"desc": desc, "dsl": dsl, "dsl_path": path} 
                           for desc, dsl, path in zip(cached_descs, cached_dsls, cached_dsl_paths)]
        else:
            # 加载DSL模板并生成缓存
            if not self._dsl_templates:
                self._dsl_templates = self.file_service.get_dsl_templates_with_desc()

            dsl_desc = [dsl["desc"] for dsl in self._dsl_templates]
            dsl_templates = self._dsl_templates
            
            # 生成embedding并保存缓存
            try:
                cache_result = get_text_embeddings(
                    dsl_desc, 
                    url, 
                    api_key, 
                    cache_path=cache_dir,
                    model_name=settings.embedding_model,
                    proxy=settings.embedding_proxy,
                    additional_data=self._dsl_templates  # 传递完整数据用于缓存
                )
                embeddings, _, _, _ = cache_result
            except Exception as e:
                logger.error(f"Embedding生成失败: {str(e)}")
                return []
        
        logger.info(f"数据加载: {time.perf_counter() - step_start:.3f}s ({'缓存' if use_cache else '重建'})")
        
        # 步骤2: BGE-M3召回
        step_start = time.perf_counter()
        try:
            user_query_embedding = get_text_embeddings(
                [user_request], url, api_key,
                model_name=settings.embedding_model, proxy=settings.embedding_proxy,
            )
            similarities = self._compute_similarity(embeddings, user_query_embedding[0])
            # 获取top-k_retrieve候选
            cand_indices = np.argsort(similarities)[::-1][:k_retrieve]
            candidate_dsl_descs = [dsl_desc[idx] for idx in cand_indices if idx < len(dsl_desc)]
            candidate_dsl_paths = [dsl_templates[idx]["dsl_path"] for idx in cand_indices if idx < len(dsl_templates)]

        except Exception as e:
            logger.error(f"Embedding recall 失败: {str(e)}")
            return []
        
        if not candidate_dsl_descs:
            return []
        
        logger.info(f"BGE召回: {time.perf_counter() - step_start:.3f}s (top{k_retrieve})")
        
        # 步骤3: DSLRec重排序
        step_start = time.perf_counter()
        try:
            intent = self.rewrite_user_intent(user_request)
            nodes_desc_str = str(intent["nodes"])
            process_desc = intent["process_desc"]
            
            # 使用generate_candidates进行重排序
            reranked_local_indices = self.generate_candidates(
                dsl_desc=candidate_dsl_descs,
                user_request=user_request,
                nodes_desc=nodes_desc_str,
                process_desc=process_desc,
                topk=min(k_final, len(candidate_dsl_descs))
            )
            
            # 映射回全局索引并返回DSL
            final_dsls = []
            final_dsl_paths = []
            for local_idx in reranked_local_indices:
                if local_idx < len(cand_indices):
                    global_idx = cand_indices[local_idx]
                    if global_idx < len(dsl_templates):
                        final_dsls.append(dsl_templates[global_idx]["dsl"])
                        final_dsl_paths.append(dsl_templates[global_idx]["dsl_path"])

            logger.info(f"重排序: {time.perf_counter() - step_start:.3f}s (top{k_final})")
            logger.info(f"召回路径: {[i.split('/')[-1] for i in candidate_dsl_paths[:3]]}, 最终: {[i.split('/')[-1] for i in final_dsl_paths]}")
            
            return final_dsls[:k_final]
            
        except Exception as e:
            logger.warning(f"重排序失败，使用原始排序: {str(e)}")
            # 降级到原始排序
            return [dsl_templates[idx]["dsl"] for idx in cand_indices[:k_final] if idx < len(dsl_templates)]

    def generate_dsl(self, user_request, dsl_version: str = "v1", recall_num: int = 10):
        start_time = time.perf_counter()
        logger.info(f"开始生成DSL，版本: {dsl_version}")

        if dsl_version == "v1":
            # 重写用户意图
            intent_result = self.rewrite_user_intent(user_request)

            # 加载DSL模板
            if not self._dsl_templates:
                self._dsl_templates = self.file_service.get_dsl_templates_with_desc()

            dsl_desc = [dsl["desc"] for dsl in self._dsl_templates]

            # 生成候选模板
            candidates = self.generate_candidates(
                dsl_desc=dsl_desc,
                user_request=user_request,
                nodes_desc=intent_result["nodes"],
                process_desc=intent_result["process_desc"],
                topk=recall_num
            )

            # 获取候选DSL模板
            candidate_dsls = [self._dsl_templates[idx]["dsl"] for idx in candidates if idx < len(self._dsl_templates)]
            if not candidate_dsls:
                elapsed_time = time.perf_counter() - start_time
                logger.info(f"DSL生成完成(无候选)，耗时: {elapsed_time:.3f}秒")
                return ""

            # 推荐最佳模板
            rec_idx = self.recommend_dsl(
                dsl_templates=candidate_dsls,
                user_request=user_request,
                nodes_desc=intent_result["nodes"],
                process_desc=intent_result["process_desc"]
            )

            if rec_idx < 0 or rec_idx >= len(candidate_dsls):
                elapsed_time = time.perf_counter() - start_time
                logger.info(f"DSL生成完成(推荐索引无效)，耗时: {elapsed_time:.3f}秒")
                return ""
            # 获取推荐的模板
            dsl_template = candidate_dsls[rec_idx]

            elapsed_time = time.perf_counter() - start_time
            logger.info(f"DSL生成完成(v1成功)，耗时: {elapsed_time:.3f}秒")
            return dsl_template
        else:
            settings = get_settings()
            if not (settings.embedding_model and settings.embedding_base_url and settings.embedding_api_key):
                raise DslRecommendError(
                    "模版检索模式需要嵌入模型，请配置 embedding_model / embedding_base_url / embedding_api_key"
                )
            # 使用BGE-M3 embeddings推荐DSL
            recommended_dsls = self.recommend_dsl_with_embeddings(
                user_request=user_request,
                url=settings.embedding_base_url,
                api_key=settings.embedding_api_key,
                k_retrieve=recall_num,
                k_final=1
            )
            result = recommended_dsls[0] if recommended_dsls else ""
            elapsed_time = time.perf_counter() - start_time
            status = f"{dsl_version}成功" if result else f"{dsl_version}无结果"
            logger.info(f"DSL生成完成({status})，耗时: {elapsed_time:.3f}秒")
            return result

        

def load_json_from_text(text):
    import json
    lpos = text.find("{")
    rpos = text.rfind("}")

    return json.loads(text[lpos: rpos + 1])
