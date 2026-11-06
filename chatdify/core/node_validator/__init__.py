"""节点校验器（依赖 Dify 源码）。

不在包导入时加载各校验器：它们会导入 Dify 实体，未提供 Dify 时 chatdify 需要能降级运行。
请使用 ``from chatdify.core.node_validator.node_validator import NodeValidator``。
"""
