"""内置默认配置"""
from typing import Dict, Any


class BuiltInConfigs:
    """内置默认配置"""
    
    @staticmethod
    def get_base_defaults() -> Dict[str, Any]:
        """获取基础默认配置"""
        return {
            'title': '',
            'version': '1',
            'retry_config': {
                'max_retries': 0,
                'retry_interval': 0,
                'retry_enabled': False
            }
        }

    @staticmethod
    def get_built_in_defaults(node_type: str) -> Dict[str, Any]:
        """获取节点内置默认配置"""
        # 聊天相关节点
        chat_nodes = {
            'llm': {
                'model': {
                    'provider': '',
                    'name': '',
                    'mode': 'chat',
                    'completion_params': {}
                },
                'prompt_template': [],
                'context': {
                    'enabled': False,
                    'variable_selector': []
                },
                'vision': {'enabled': False}
            },
            'agent': {
                'tools': [],
                'max_iterations': 5
            },
            'answer': {
                'template': '',
                'format': 'text'
            }
        }
        
        # 数据处理节点
        data_nodes = {
            'code': {
                'code': '',
                'code_language': 'python3',
                'timeout': 60
            },
            'list_operator': {
                'operation': 'map',
                'input_list': [],
                'output_type': 'array'
            },
            'template_transform': {
                'template': '',
                'variables': []
            },
            'variable_aggregator': {
                'variables': [],
                'output_type': 'string',
                'advanced_settings': {
                    'group_enabled': False,
                    'groups': [],
                },
            },
            'variable_assigner': {
                'variables': [],
                'output_type': 'string'
            }
        }
        
        # 流程控制节点
        flow_nodes = {
            'if_else': {
                'condition': {'type': 'javascript', 'value': ''},
                'error_handle_mode': 'terminated'
            },
            'iteration': {
                'iterator_selector': [],
                'output_selector': [],
                'is_parallel': False,
                'parallel_nums': 1,
                'error_handle_mode': 'terminated',
            },
            'start': {
                'variables': []
            },
            'end': {
                'output_type': 'object'
            }
        }
        
        # 集成节点
        integration_nodes = {
            'http': {
                'method': 'GET',
                'url': '',
                'headers': {},
                'params': {},
                'body': {},
                'timeout': 30,
                'retry_config': {
                    'max_retries': 3,
                    'retry_interval': 1
                }
            },
            'tool': {
                'tool_name': '',
                'parameters': {},
                'timeout': 30
            }
        }
        
        # 知识库节点
        knowledge_nodes = {
            'knowledge_retrieval': {
                'knowledge_base': '',
                'top_k': 3,
                'score_threshold': 0.7,
                'rerank_enabled': False
            },
            'document_extractor': {
                'file_type': 'text',
                'extraction_mode': 'full',
                'chunk_size': 1000
            }
        }
        
        # 其他工具节点
        misc_nodes = {
            'custom_note': {
                'content': '',
                'note_type': 'info'
            },
            'parameter_extractor': {
                'parameters': [],
                'extraction_rules': {}
            },
            'question_classifier': {
                'categories': [],
                'default_category': 'other'
            }
        }
        
        # 合并所有节点配置
        all_node_defaults = {
            **chat_nodes,
            **data_nodes,
            **flow_nodes,
            **integration_nodes,
            **knowledge_nodes,
            **misc_nodes
        }
        
        if node_type in all_node_defaults:
            return all_node_defaults[node_type]
        normalized = node_type.replace('-', '_')
        return all_node_defaults.get(normalized, {})