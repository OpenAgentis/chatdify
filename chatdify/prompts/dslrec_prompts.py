"""
DSL推荐相关的prompt模板
"""

SYSTEM_PROMPT_BASE = "You are a DSL creation expert for the no-code tool Dify."

USER_INTENT_REWRITE_PROMPT = """你是一个大模型应用开发平台Dify的资深建模工程师，擅长理解用户的Dify应用需求，并且将用户需求进行实际的模块拆分，挑选出用户该应用需要使用到的Dify平台的哪些功能节点。
下面首先给出Dify平台有哪些功能节点，然后你的任务是深度理解用户的需求，并且将用户的需求拆解成执行流程图，给出执行流程图上需要使用到哪些节点，同时需要输出流程描述。

Dify平台节点及描述如下：
{nodes_desc}

用户应用需求如下：
{requirement}

## Output Format
你的输出应该是json格式，只需要包含两个键:
- nodes: 表示需要使用到哪些可能的节点，它的值是列表(list)，列表中的每个元素是一个字典，字典有两个键：
  - name: 表示这个节点的名称
  - desc: 表示这个节点需要执行的功能
- process_desc: 表示流程描述

请不要额外输出其他信息，一定要确认你的输出是一个满足条件的json格式。
"""

GENERATE_CANDIDATES_PROMPT = """你是一个开源的大语言模型应用开发平台Dify的应用模版推荐专家，擅长根据用户的需求去从Dify DSL模版描述中给用户进行推荐。
下面给你一些Dify DSL的模版功能描述，请根据用户的需求，以及给出的用户选择节点及流程描述，给他推荐最合适的 {topk} 个。

dify的dsl功能描述如下：
{dify_dsl_template_desc}

用户的需求如下：
{requirement}

用户选择的可能节点及其描述如下：
{nodes_desc}

用户对需求的流程描述如下：
{process_desc}

## Output Format
请注意：你的输出格式需要是一个json，里面只有一个键 candidate_list，对应的值是一个列表list，列表的元素是数字，表示你认为可能合适的 {topk}。
"""

RECOMMEND_DSL_PROMPT = """你是一个开源的大语言模型应用开发平台Dify的应用专家，擅长给用户推荐Dify DSL模版。

Dify DSL模版如下：
{dify_dsl_template_desc}

用户的需求如下：
{requirement}

用户选择的可能节点及其描述如下：
{nodes_desc}

用户对需求的流程描述如下：
{process_desc}

## Output Format
请输出一个数字，表示最符合用户需求的模版编号。请仅输出一个数字，不需要额外输出其他信息。如果DSL模版均不符合用户的需求，输出整数 -1。
"""

REVISE_NODE_CONFIG_PROMPT = """你是一个开源的大语言模型应用开发平台Dify的资深应用专家。

Dify DSL通用模版：
{dsl_template}

用户节点配置信息:
{nodes_config}

用户的需求: 
{requirement}

## Output Format
请根据用户的定制化节点配置修改DSL通用模版。注意：
1. 不要改变通用模版的边连接关系
2. 只进行节点信息的填充和修改
3. 只有type一样的节点才可以进行替换
4. 输出格式必须是yaml格式，并用```yaml包裹
"""

INTERPRET_DSL_PROMPT = """请分析以下Dify工作流DSL，简要总结：
1. 这个模版的主要功能
2. 适用场景
3. 输入输出
4. 流程节点，包括这个流程节点的类型是什么，以及该节点的输入和输出分别是什么

Dify DSL模版:
{dsl}

## Output Format
请用简洁的语言描述，不需要额外的格式。
"""
