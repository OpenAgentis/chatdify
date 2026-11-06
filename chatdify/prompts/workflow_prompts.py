"""
工作流相关提示词模块
"""

# 系统提示词
SYSTEM_PROMPT = "你是一位专业的 Dify 无代码工具 DSL 创建专家。"

# 工作流引擎提示词
EXPAND_REQUEST_PROMPT = """
我们需要创建一个执行计划来完成用户的请求。请识别并扩展用户需求中不够具体的部分。
当用户需求包含'多个'、'详细'、'具体'、'更多'等模糊表述时，需要进行细化和扩展。

## 用户需求：{user_request}

## 输出要求
- 只输出扩展后的需求内容
- 无需问候语和结束语
- 无需解释思考过程
- 直接输出扩展后的具体内容
"""

TASKS_PLANNING_PROMPT_SYSTEM = """
作为专业的 DIFY 工作流规划专家，请基于用户需求和历史反馈（如有）进行全面深度分析。

# 核心任务
1. **需求挖掘**：深度解析用户需求中的核心业务逻辑、关键技术难点和潜在挑战
2. **任务分解**：识别并明确完成需求所需的具体任务步骤，梳理任务间的依赖关系和执行顺序
3. **流程可视化**：使用 Mermaid 流程图清晰表达整个任务执行流程

# 分析要求
- 确保业务逻辑的完整性和准确性
- 识别关键决策点和分支条件
- 明确输入输出和数据流转

# 输出规范
## 请使用 Mermaid 流程图表示任务流程，**严格遵循以下要求**：
- 使用 flowchart TD 格式（自上而下布局）
- **禁止包含任何样式定义**（如 classDef、style 等）
- 使用清晰的节点命名和描述
- 包含必要的决策节点和条件分支
- 添加适当的说明注释（使用 %% 或 -.-> 虚线）

## 输出格式：
### 严格遵循-只输出 Mermaid 流程图代码
### 输出格式的参考示例
```mermaid
flowchart TD
    A["开始"] --> B["用户输入原始内容"]
    B --> C["用户输入目标语言"]
    C --> D["翻译大模型：首次翻译"]
    D --> E["质检大模型：四维度评分"]
    E --> F{{"综合评分大于等于18分"}}
    F -->|是| G["输出最终结果"]
    F -->|否| H["翻译大模型：基于反馈重新翻译"]
    H --> E
    G --> I["结束"]
    
    %% 评分维度说明
    E -.-> J["准确性评分 1-5分"]
    E -.-> K["流畅性评分 1-5分"]
    E -.-> L["完整性评分 1-5分"]
    E -.-> M["风格与用词评分 1-5分"]
    
    %% 输出格式说明
    G -.-> N["JSON格式输出包含原文译文综合评分评分细则"]
```

"""

TASKS_PLANNING_PROMPT_USER = """
1. 用户需求：{user_request}
2. 反馈历史：{feedback_history}
"""


GENERATE_EDGES_MERMAID_PROMPT_SYSTEM = """
# 系统角色定义
你是一位专业的 Mermaid 流程图生成专家，擅长将工作流边信息转换为清晰、美观的 Mermaid 流程图。

# 任务目标
根据提供的工作流边信息，生成标准的 Mermaid 流程图代码。
## 要求
- 分析边的连接关系，构建完整的流程图
- 识别节点类型，使用合适的 Mermaid 节点形状
- 处理条件分支和循环结构
- 确保流程逻辑清晰易懂
- 添加必要的标签和注释

# 输出要求
1. 使用 flowchart TD 格式（自上而下布局）
2. **严格禁止包含任何样式定义**（如 classDef、style 等）
3. 节点命名要清晰易懂
4. 正确处理条件分支和循环结构
5. 添加必要的注释说明
6. 确保图形结构清晰，逻辑流向明确

# 节点类型处理规则
- start: 使用圆角矩形 [\"开始\"]
- end: 使用圆角矩形 [\"结束\"]
- if-else: 使用菱形 {{\"条件判断\"}}
- loop: 使用六边形 {{{{\"循环处理\"}}}}
- iteration: 使用梯形 [[\"迭代处理\"]]
- 其他节点: 使用矩形 [\"节点描述\"]

# 连接线处理
- 普通连接: -->
- 条件分支: -->|条件| 或 -->|是/否|
- 循环连接: 特殊标注循环路径
- 迭代连接: 标注迭代范围

## 输出格式：
### 严格遵循-只输出 Mermaid 流程图代码
### 输出格式的参考示例
```mermaid
flowchart TD
    A["开始"] --> B["翻译大模型：初次翻译"]
    B --> C["质检大模型：质量评估"]
    C --> D["代码节点：评分检查"]
    D --> E["循环节点：翻译优化"]
    
    %% 循环内部流程
    E --> F["翻译大模型：重新翻译"]
    F --> G["质检大模型：重新评估"]
    G --> H["代码节点：循环判断"]
    H -->|继续优化| E
    H -->|达标退出| I["答案节点：输出结果"]
    
    %% 直接退出路径（如果初次翻译就达标）
    E -->|初次达标| I
    
    %% 说明注释
    C -.-> J["四维度评分：准确性、流畅性、完整性、风格"]
    D -.-> K["判断综合评分是否≥18分"]
    I -.-> L["JSON格式输出：原文、译文、评分、细则"]
    
    %% 循环控制说明
    E -.-> M["循环控制：最多3次优化"]
    H -.-> N["退出条件：评分达标或达到最大循环次数"]
```
"""

GENERATE_EDGES_MERMAID_PROMPT_USER = """
1.边信息（YAML格式）: {edges_yaml}
"""


GENERATE_EDGES_PROMPT_SYSTEM = """
# 系统角色定义
你是一位专业的 Dify 工作流 DSL 设计专家，擅长分析需求并创建高效的工作流程。

# 任务目标
请根据以下输入, 创建或优化工作流 DSL的边信息, 输出是完整的DSL的边信息：
1. 可用节点清单：当前可用的所有节点类型及其功能说明，使用样例等。
2. 选中的可用节点类型列表: 选中的最优的可用节点类列表，用于构建工作流。注意，工作流构建中不能引入不在该列表中的节点类型。
3. 参考DSL配置模版（如有）：相关的DSL配置模板或最佳实践示例
4. 用户需求描述: 详细说明用户的具体需求和期望达成的目标
5. 任务拆解清单：将需求拆分为可执行的具体任务项
6. 现有工作流配置（如需修改）：当前工作流配置信息。当存在时，需要根据用户需求和优化建议进行修改。请尽量保持原内容不变，仅对需要修改的地方进行修改。
7. 优化建议（如需修改）：针对现有配置的改进意见和反馈。请根据意见和反馈修正边信息配置。

# 工作流程
1. 需求分析
   - 理解用户核心需求
   - 确定是生成新的工作流还是优化现有工作流
   - 确定关键任务步骤
   - 识别数据流动路径

2. 节点规划
   - 将任务步骤映射到合适的节点
   - 只能从可用节点列表中选择最优节点类型
   - 确保节点功能匹配任务需求
   - 验证前置节点输出类型，确保当前节点能正确处理输入
   - 注意：需要区分"批处理循环"与"多轮对话"两类重复需求：
     a) 批处理/收敛（一次运行内完成）：对数组逐项处理用 iteration；依赖上一轮结果重复计算直至收敛或达上限用 loop。
     b) 多轮对话（每轮需用户重新输入，如模拟面试、语言陪练、谈判教练）：必须用 advanced-chat 模式，禁止用 loop/iteration 在一次运行内跑满"计划轮数"。
        实现方式：用户每轮输入引用 sys.query；跨轮状态（轮次、历史、阶段）用 conversation 会话变量保存并由 assigner 读写；每个交互点以 answer 结束本轮等待用户下一条消息。
        是否需要"首轮分流"取决于由谁发起对话，不要一概而论：
          · 机器人主导/先提问型（如模拟面试、出题测验、引导式教练、分步问诊）：对话开始时用户先发的第一条 sys.query 只是"开场/启动"，此时机器人尚未提问，这条不是对任何问题的正式回答，禁止当作答案去评分或处理。应在 start 之后用 if-else 判断会话状态（如 conversation.history 是否为空、或轮次计数 current_round 是否为初值）分流：首轮分支只生成并回复"第一步内容"（如第一道题），不评分、不消费上一轮回答；后续轮分支先处理/评分上一轮回答，再推进并自增轮次。借此避免"把开场白当回答打分""第0轮/轮次错位""跑满计划轮后不触发收尾"。
          · 用户主导/用户先提问型（如问答助手、客服、咨询、持续陪聊）：每一条 sys.query 都是用户的真实输入/问题，首条本身就有意义，无需区分首轮，对每轮输入按统一逻辑处理即可。

3. 边关系设计
   - 基于数据流动设计节点连接
   - 优先复用历史工作流中的有效边
   - 仅对需要优化的部分进行边的调整

# 设计原则
1. 按照最小化节点原则，保持工作流结构清晰简洁
2. 确保数据流转逻辑合理
3. 最小化对现有工作流的改动
4. 优先考虑可重用的模式
5. 节点可引用其所有祖先节点的有效输出，不能与路径长度超过一的祖先同时连边。请利用这个规则最小化边连接

# 工作说明
请严格遵守规则，需要检查并确保所有输出内容准确无误，避免产生任何虚假信息。

## 参考DSL模版工作说明
1. 如果提供了参考DSL模板，可以从中获取整体结构和配置的灵感, 学习其模式，但要根据当前需求生成边。
2. 如果没有提供参考模板，请根据标准格式和最佳实践创建。

## DSL模式（mode）说明
1. **workflow模式**：面向自动化和批处理情景，适合高质量翻译、数据分析、内容生成、电子邮件自动化等应用程序。
2. **advanced-chat模式**：面向对话类情景，包括客户服务、语义搜索、以及其他需要在构建响应时进行多步逻辑的对话式应用程序。凡是"多轮对话""每轮用户回答""计划N轮提问/陪练"等需要用户反复输入的需求，必须使用 advanced-chat 模式，并用 conversation 会话变量保存跨轮状态。

### 多轮对话会话变量规则（advanced-chat 多轮场景）
1. 多轮对话需要跨轮保存的状态（轮次计数、对话历史、当前阶段等）使用会话变量 conversation.*，由 assigner 节点读写。
2. assigner 写入会话变量时，items 的 variable_selector 形如 ["conversation", "变量名"]；over-write 覆盖、append 追加数组、+= 累加数字。
3. 其他节点读取会话变量用 {{ '{{' }}{{#conversation.变量名#}}{{ '}}' }}（llm 提示词、answer 文本、code 输入等均可引用）。
4. 同一会话变量名在写入(assigner)与读取(llm/answer/code)处必须保持完全一致，否则跨轮状态无法生效。
5. 对话历史可用 array[string] 会话变量以 append 逐轮累加，或用 string 会话变量存 JSON 字符串；无论哪种，assigner over-write/set 写入会话变量时，源值类型必须与目标会话变量声明的 value_type 一致（数组源不能写入 string 变量，否则运行期报 "Invalid input value"）。
6. 是否区分首轮取决于谁发起对话：
   - "用户主导/用户先提问型"（问答助手、客服等）：每条 sys.query 都是真实用户输入，无需区分首轮。
   - "机器人主导/先提问型"（模拟面试、出题测验、引导式教练等）：首条 sys.query 多为开场或启动语（如「开始面试」），不是对机器人提问的作答；if-else 与轮次计数应忽略或单独分支处理该消息，勿将其当作有效回答参与评分或累加轮次。
   一轮对话的定义：一轮 = 一次完整的交互配对——"一方发起 + 另一方回应"闭合才算一轮；发起方既可能是用户（用户问、机器人答），也可能是机器人（机器人问、用户答），单独一条消息（只发起、还没有对应回应）不构成完整一轮。因此轮次计数（如 current_round）应在该配对闭合后才 +1；当发起与回应跨越两次请求时（如机器人在上一轮先抛出、用户本次才回应），在"收到并处理完该回应、配对闭合"的那一次执行里再 +1，不要在刚发起、尚无对应回应时就 +1。
   需要跨轮计数时用 number 会话变量（如 current_round）累加，并保证其初值与各分支条件相互一致；禁止用 sys.dialogue_count 充当轮次计数。
   （可选）当"本次 sys.query 是开场/提问还是对上一步的回答"难以仅凭轮次计数判断时，可额外用一个会话变量显式标记当前阶段（如 awaiting_answer:boolean，或 stage:string 取 asking/answering/done），节点据此分流会更稳健；流程简单、计数已足够时则无需引入该冗余状态。

## 边生成规则
### 基本规则
1. 边的基本属性：
   - source: 源节点ID。 纯数字表示。
   - target: 目标节点ID。纯数字表示。
   - sourceType: 源节点类型（只能从选中的可用节点类型列表中选择）
   - targetType: 目标节点类型（只能从选中的可用节点类型列表中选择）
   - sourceHandle：默认为"source"
   - targetHandle：固定为"target"
   - 边ID格式: {{源节点ID}}-source-{{目标节点ID}}-target

2. sourceHandle特殊情况：
   - 如果sourceType是if-else：sourceHandle不能使用source"，sourceHandle是具体的分支id表示，建议使用"true"或者"false"
   - 如果sourceType是question-classifier：sourceHandle不能使用source", sourceHandle是具体的分支id表示。

3. 禁止的目标节点类型(targetType):
   - 不允许: "start"
   - 不允许: "iteration-start"
   - 不允许: "loop-start"
   违反示例: "targetType": "loop-start" 
 
4. 连通性属性：
   - 每个节点必须有一个入边，但是除了节点类型是start, iteration-start 和 loop-start 的节点
   - 连通图不能出现环
   - 不能出现孤立节点

5. source和target规则：
   - source: 源节点ID。 纯数字表示。
   - target: 目标节点ID。纯数字表示。
   - source 和 target一定不能相同。
   - 边中同一个source或者target ID的对应的具体功能应该是唯一的。不能出现一个节点ID对应不同的具体功能。

### 开始节点规则
   1. 必须包含且仅包含一个开始节点
   2. 开始节点的节点类型必须是start
   3. sourceType: start

### 结束节点规则
   1. **workflow模式**必须包含结束节点
   2. 结束节点的节点类型必须是end
   3. targetType: end

### answer节点规则
   1. **advanced-chat模式**必须包含answer节点
   2. answer节点的节点类型必须是answer
   3. targetType: answer

### 特殊节点类型(sourceType)规则
1. start节点：
   - 不能有入边
   - 至少有一个出边

2. iteration-start节点：
   - 不能有入边
   - 至少有一个出边

3. loop-start节点：
   - 不能有入边
   - 至少有一个出边

### 迭代节点(iteration)类型规则
1. 节点配对：
   - iteration和iteration-start类型节点必须同时存在
   - 迭代内节点不能与迭代外节点连接
   - 迭代内的节点定义：出现在isInIteration: true边中的节点。
   - 迭代外节点：不包含在迭代内的节点。
   - iteration类型节点的直接前置节点的输出类型必须是数组Array。
   - iteration类型节点的直接前置节点可以考虑是code类型或者parameter-extractor类型。
   - workflow 批处理型 iteration 默认通过 output_selector 收集每轮输出，不要为了汇总结果默认增加 assigner。
   - 只有明确需要写入 conversation.* 会话变量、跨轮保存状态、或更新 loop/会话级可写变量时，才在 iteration 内连接 assigner；若只是收集每轮处理结果，应使用 iteration.output_selector。

2. 迭代内边属性：
   - isInIteration: true
   - iteration_id: 迭代节点ID
   - iteration_id 不能等于 target
   - iteration_id 不能等于 source
   - zIndex: 1002
   违反示例: {{"iteration_id": "10000005", "target": "10000005"}} 
  
### 循环节点(loop)类型规则
1. 节点配对：
   - loop-start和loop类型节点必须同时存在
   - 循环内节点不能与循环外节点连接
   - 循环内的节点定义：出现在isInLoop: true边中的节点。
   - 循环外节点：不包含在迭代内的节点。

2. 循环内边属性：
   - isInLoop: true
   - loop_id: 循环节点ID
   - loop_id 不能等于 target
   - loop_id 不能等于 source
   - zIndex: 1002
   违反示例: {{"loop_id": "10000004", "target": "10000004"}} 

### template-transform节点规则
1. 如无必要，尽量不要用template-transform节点

### document-extractor节点规则
1. 重点注意：不支持图像数据处理
2. CSV/Excel/Word 表格提取后，text 输出为 Markdown 表格（含 | 列分隔与 --- 分隔行），不是标准 CSV 字节流；下游 code 须按 Markdown 表格解析，禁止 pd.read_csv(StringIO(text))

### 工具节点规则
1. 工具节点的节点类型（sourceType和targetType）必须是在选中的可用节点类型列表中选择的节点类型, 不能自定义。
2. 工具节点的节点类型命名规范是"tool_xxx", "xxx"是工具的名称。不能只用"tool"。

### question-classifier节点规则
1. question-classifier节点所有输出分支必须有下游节点。


# 输出要求
## 正确的输出格式
请输出一个边的 JSON 数组。除了JSON数组，不要输出其他任何内容。
生成的 JSON 数组必须遵循以下格式：
```json
[
    {{
        "data": {{
            "isInIteration": false,
            "sourceType": "start",
            "targetType": "llm"
        }},
        "id": "10000001-source-10000002-target",
        "source": "10000001",
        "sourceHandle": "source",
        "target": "10000002",
        "targetHandle": "target",
        "zIndex": 0,
    }}
]
```

## 错误输出样例：
```json
[
    {{
        "data": {{
            "isInIteration": false,
            "sourceType": "llm",
            "targetType": "loop-start"
        }},
        "id": "10000002-source-10000003-target",
        "source": "10000002",
        "sourceHandle": "source",
        "target": "10000003",
        "targetHandle": "target",
        "zIndex": 0,
    }},

    {{
        "data": {{
            "isInLoop": true,
            "loop_id": "10000004",
            "sourceType": "code",
            "targetType": "loop"
        }},
        "id": "10000007-source-10000004-target",
        "source": "10000007",
        "sourceHandle": "source",
        "target": "10000004",
        "targetHandle": "target",
        "zIndex": 1002
    }}
]
```
### 错误输出样例说明
1. 错误原因: targetType不能是loop-start
2. 错误原因: target值不能等于loop_id值

"""

# "sourceDescription": "{{根据用户需求描述和源节点的具体类型（sourceType），详细描述该节点作为数据来源的功能。请以自然语言段落形式描述，包含以下要点：节点功能定位（明确说明该节点在整个工作流中的作用和价值）、输出数据规格（描述输出的数据类型、数据结构、字段含义和数据格式）、数据处理逻辑（说明节点内部的数据处理、转换、计算或生成逻辑）。要求保留用户输入的所有相关信息，并结合节点类型特性提供针对性描述。}}",
# "targetDescription": "{{根据用户需求描述和接受节点的具体类型（targetType），详细描述该节点作为数据接受方的功能。请以自然语言段落形式描述，包含以下要点：节点功能定位（明确说明该节点在整个工作流中的作用和价值）、输出数据规格（描述输出的数据类型、数据结构、字段含义和数据格式）、数据处理逻辑（说明节点内部的数据处理、转换、计算或生成逻辑）。要求保留用户输入的所有相关信息，并结合节点类型特性提供针对性描述。}}",


GENERATE_EDGES_PROMPT_USER = """
# 输入信息
1. 可用节点清单: {node_list}
2. 选中的可用节点类型列表: {select_node_types}
3. 参考DSL配置模版：{reference_workflow}
4. 用户需求描述:{user_request}
5. 任务拆解清单:{tasks}
6. 现有工作流配置: {previous_workflow}
7. 必须修复的上一轮失败原因（高优，若为空说明是首次生成，可忽略本段)，修复建议: {feedback_history}
"""


# 节点管理器提示词
GENERATE_NODE_PROMPT_SYSTEM = """
# 系统角色定义
你是一位专业的 Dify 工作流 DSL 设计专家，擅长分析需求并创建高效的工作流程。

# 任务目标
## 需要生成节点信息
- 节点ID
- 节点类型
- 节点功能需求描述

## 输入要求
请根据以下输入创建或优化工作流 DSL 中节点信息：
1. 节点规范：节点配置需遵循的技术规范和业务规则
2. 参考节点配置模板（如有）：相关的DSL配置模板或最佳实践示例
3. 用户需求描述: 详细说明用户的具体需求和期望达成的目标
4. 现有节点配置（如需修改）：当前工作流中的节点配置信息。当存在时，需要根据用户需求和优化建议进行修改。请尽量保持原内容不变，仅对需要修改的地方进行修改。
5. 节点ID： 需要生成的节点ID，节点ID必须是唯一的，不能与已有的节点ID重复。
6. 节点类型：需要生成的节点类型，节点类型必须是Dify支持的节点类型。
7. 节点功能需求描述: 详细说明节点的具体功能需求和期望达成的目标
8. 节点相关边信息
9. 已创建的节点信息
10. 上一轮的节点信息
11. 上一轮的会话变量信息
11. 优化建议（如需修改）：针对现有配置的改进意见和反馈。请根据意见和反馈修正当前节点配置。

# 工作流程
1. 需求分析
   - 理解用户核心需求
   - 确定是生成新的工作流还是优化现有工作流
   - 确定节点功能定位
   - 识别数据流动需求

2. 节点设计
   - 根据节点类型选择合适的配置
   - 确保节点功能匹配任务需求
   - 必须遵守节点规范
   - 验证前置节点输出类型，确保当前节点能正确处理输入
   - 正确处理节点的输入和输出变量

3. 配置优化
   - 基于历史工作流优化节点配置
   - 复用有效的节点配置模式
   - 仅对需要优化的部分进行调整

# 设计原则
1. 保持节点配置清晰简洁
2. 确保数据流转逻辑合理
3. 最小化对现有配置的改动
4. 优先考虑可重用的模式

# 工作说明
请严格遵守规则，需要检查并确保所有输出内容准确无误，避免产生任何虚假信息。

## 前置节点输出使用说明
前置节点的输出变量是该节点的重要输入来源。如果前置节点的输出变量处理不正确，将导致节点行为异常。
在创建节点时需要正确引用前置节点的输出变量。

## 参考DSL模版工作说明
1. 如果提供了参考DSL模板，可以从中获取整体结构和配置的灵感，学习其模式，但要根据当前需求生成节点。
2. 如果没有提供参考模板，请根据标准格式和最佳实践创建。

## 节点生成规则
### 通用规则
1. 变量引用格式: {{ '{{' }}{{#节点ID.输出变量名#}}{{ '}}' }}
2. 前置节点输出变量是重要输入来源，必须正确处理

### 多轮对话会话变量规则（advanced-chat 多轮场景）
1. 多轮对话需要跨轮保存的状态（轮次计数、对话历史、当前阶段等）使用会话变量 conversation.*，由 assigner 节点读写。
2. assigner 写入会话变量时，items 的 variable_selector 形如 ["conversation", "变量名"]；over-write 覆盖、append 追加数组、+= 累加数字。
3. 其他节点读取会话变量用 {{ '{{' }}{{#conversation.变量名#}}{{ '}}' }}（llm 提示词、answer 文本、code 输入等均可引用）。
4. 同一会话变量名在写入(assigner)与读取(llm/answer/code)处必须保持完全一致，否则跨轮状态无法生效。
5. 对话历史可用 array[string] 会话变量以 append 逐轮累加，或用 string 会话变量存 JSON 字符串；无论哪种，assigner over-write/set 写入会话变量时，源值类型必须与目标会话变量声明的 value_type 一致（数组源不能写入 string 变量，否则运行期报 "Invalid input value"）。
6. 是否区分首轮取决于谁发起对话：
   - "用户主导/用户先提问型"（问答助手、客服等）：每条 sys.query 都是真实用户输入，无需区分首轮。
   - "机器人主导/先提问型"（模拟面试、出题测验、引导式教练等）：首条 sys.query 多为开场或启动语（如「开始面试」），不是对机器人提问的作答；if-else 与轮次计数应忽略或单独分支处理该消息，勿将其当作有效回答参与评分或累加轮次。
   一轮对话的定义：一轮 = 一次完整的交互配对——"一方发起 + 另一方回应"闭合才算一轮；发起方既可能是用户（用户问、机器人答），也可能是机器人（机器人问、用户答），单独一条消息（只发起、还没有对应回应）不构成完整一轮。因此轮次计数（如 current_round）应在该配对闭合后才 +1；当发起与回应跨越两次请求时（如机器人在上一轮先抛出、用户本次才回应），在"收到并处理完该回应、配对闭合"的那一次执行里再 +1，不要在刚发起、尚无对应回应时就 +1。
   需要跨轮计数时用 number 会话变量（如 current_round）累加，并保证其初值与各分支条件相互一致；禁止用 sys.dialogue_count 充当轮次计数。
   （可选）当"本次 sys.query 是开场/提问还是对上一步的回答"难以仅凭轮次计数判断时，可额外用一个会话变量显式标记当前阶段（如 awaiting_answer:boolean，或 stage:string 取 asking/answering/done），节点据此分流会更稳健；流程简单、计数已足够时则无需引入该冗余状态。

### llm节点规则
1. prompt_template:
    - role: system
      text: {{根据用户需求描述和节点功能需求描述，生成正确的系统提示词，用中文描述。 注意如果输出是markdownjson等非标准格式，先进行预处理
       , 移除markdown代码块标记(```json和```)。}}
    - role: user    
      text: {{根据用户需求描述和节点功能需求描述，和前置节点输出信息，填写正确的输入}}   
2. 如果是图像视觉场景需要按照如下示例设置字段：
   vision:
      configs:
         detail: high
         variable_selector:
         - '100001'
         - image
      enabled: true

### code节点规则
    code: {{
    根据用户需求描述和节点功能需求描述，生成可执行的Python代码，确保语法正确并符合以下规范：
    
    1. 代码入口：
       - 必须有一个名为main的函数作为入口
       - 所有子函数定义必须写在main函数里面
       - main 函数参数类型注解必须使用 Python 合法类型

    2. 输出规范:
       - 输出变量类型必须是以下之一:
         * string (字符串)
         * number (数字)
         * boolean (布尔值)
         * object (字典)
         * array[string] (字符串数组)
         * array[number] (数字数组)
         * array[boolean] (布尔值数组)
         * array[object] (对象数组)
       - 重点注意：main函数正常返回和异常返回的分支，必须有返回值。main函数各个返回分支的返回变量名集合必须一样。
       - 重点注意: 输出变量名中不能包含'error'命名字段。请用其他名字替代，比如'err'。
       - 【类型对齐】outputs 各字段 type 必须与 main() return 中对应值的 Python 类型严格一致
    
    2. JSON输入处理:
       - 自动检测并处理markdown包裹的JSON(```json和```)
       - 实现健壮的JSON解析逻辑:
        def extract_json_from_markdown(self, markdown_text: str) -> str:
            if not markdown_text:
                return ""
            start = markdown_text.find('```json')
            if start == -1:
                start = markdown_text.find('```')
                if start == -1:
                    return markdown_text.strip()
            content_start = markdown_text.find('\n', start)
            if content_start == -1:
                # 没有换行符，内容紧跟在```json之后
                start_offset = len('```json')
                content_start = start + start_offset
            else:
                # 内容在换行符之后
                content_start += 1
            end = markdown_text.rfind('```')
            if end == -1:
                return markdown_text[content_start:].strip()
            if content_start >= end:
                return markdown_text.strip()
            return markdown_text[content_start:end].strip()
    
      示例模板:
        # 预处理输入
        json_text = extract_json_from_markdown(llm_text) # 仅当llm节点输出包含```json和```的json字符串时候需要处理
        data = json.loads(json_text)
        
        # 业务逻辑处理
        processed_data = process_data(data)
        ....
        # 返回规范结果
        return xxx

    3. 代码质量:
       - 添加必要的类型注解
       - 包含清晰的函数文档字符串
       - 处理边界条件和特殊字符
       - 避免硬编码值  
    }}

### if-else节点规则
   1. cases条件分支列表，每个分支的case_id注意事项：分支唯一标识符, 必须和边信息中对应的sourceHandle值保持一致。

###  question-classifier节点规则
   1. classes分类列表，每个分类的id注意事项：分类唯一标识符, 必须和边信息中对应的sourceHandle值保持一致。

### template-transform节点规则
 template: {{
    1. 根据用户需求描述和节点功能需求描述和前置节点输出，生成正确的模板内容。
    2. 模板内容必须符合Jinja2语法规范。
 }}

### 迭代节点规则
1. iteration-start节点:
   - 设置data/isInIteration为true
   - 设置parentId为迭代节点ID
  
2. 迭代内节点:
   - 设置data/isInIteration为true
   - 设置data/iteration_id为迭代节点ID
   - 设置parentId为迭代节点ID
   - 设置zIndex为1002
   - 普通 workflow 批处理的迭代内节点不需要默认引入 assigner；每轮结果由 iteration.output_selector 指向内部最终节点输出并自动汇总。
   - 仅当节点职责明确要求写入 conversation.*、跨轮保存状态或更新可写变量时，才生成 assigner 节点；不要用 assigner 替代 output_selector 做普通结果收集。

### 循环节点规则
1. loop-start节点:
   - 设置data/isInLoop为true
   - 设置parentId为循环节点ID

2. 循环内节点:
   - 设置data/isInLoop为true
   - 设置data/loop_id为循环节点ID
   - 设置parentId为循环节点ID
   - 设置zIndex为1002

### 输出变量引用规则
  1. http-request类型节点可用输出为status_code、body、headers、files，禁止使用http_response等不存在的字段名：
    - body：HTTP响应正文（文本或JSON字符串），用于解析API返回、模板拼接等
    - files：响应中的文件列表（如GET下载得到的图片/文档），供LLM vision或需要file类型的下游节点引用
    - status_code、headers：仅在需要判断请求成败或读取响应头时引用
  2. LLM类型节点输出使用text
  3. document-extractor类型节点输出使用text
  4. list-operator类型节点输出使用result（过滤后的数组）、first_record或last_record，禁止使用item（item仅属于iteration节点）
  5. agent类型节点输出使用text
  6. variable-aggregator类型节点输出使用output
  7. template-transform类型节点输出使用output
  8. question-classifier类型节点输出使用class_name
  9. knowledge-retrieval类型节点输出使用result
  10. iteration类型的节点在迭代外部输出使用output
  11. iteration类型的节点在迭代内部输出使用item，禁止使用item.xx语法，不能引用item内部子变量
  12. iteration-start类型的节点输出变量不能被引用
  13. loop-start类型的节点输出变量不能被引用
  14. if-else类型的节点输出变量不能被引用
  15. assigner类型的节点输出变量不能被引用
  16. Tool中md_to_xx类型（如md_to_docx, md_to_pdf等）的节点输出使用files
  17. Tool中tool_jina_reader类型节点输出使用text
  18. Tool中tool_text2image类型节点输出规则：
    - text：生成图片的 HTTP 链接文本；展示图片时引用该字段
    - images：图片对象数组，元素含 url、size；供 code 节点提取 url字段
    - files：工具文件列表；ImageGenerations 场景常为空，不可作为 LLM vision 输入
  19. Tool中tavily_search类型节点输出纯文本展示请优先使用text字段（纯文本）。如果需要结构化检索结果，请使用json字段。json字段是一个数组格式（Array[Object],注意不是json字符串格式），数组中每个元素是一次搜索的完整结果对象，其结构如下：
    - query：本次搜索使用的查询语句（string）
    - results：检索结果数组（Array[Object]），是核心内容，每个结果元素包含：
      - content：网页正文摘要内容（string）
      - domain：来源网站域名（string，如"ithome.com"）
      - main_topic：主题分类（string，如"product"）
      - popularity_score：热度评分（number）
      - raw_content：原始完整内容，仅当include_raw_content为true时有值，否则为null
      - score：与查询的相关性得分（number，0~1之间）
      - title：网页标题（string）
      - url：网页链接（string）
    引用结构化结果时需注意：取检索条目正文用{{#节点ID.json#}}后在下游（如代码/模板节点）遍历results数组并取content/title/url等字段，json字段不是json字符串格式，不能直接拼接为纯文本展示，纯文本展示请优先使用text字段

## 输出格式
请输出该节点信息的 JSON 串, 注意这个json串只有这个节点信息，不能包含其他节点。确保JSON语法正确.
生成的 JSON 内容遵循以下格式：
```json
   {{
   'data': 
      {{
      'type': 'start', 
      'title': 'Start', 
      'desc': '接收用户输入的研究主题', 
      'variables': 
      {{
         {{
         'type': 'paragraph', 
         'variable': 'topic', 
         'label': 'xx', 
         'required': True, 
         'max_length': 99999
         }},
         {{
         'type': 'select'
         'variable': 'target_language'
         'label': '目标语言',
         'required': True, 
         'options':['英文', '中文']
         }}
      }}
      }}, 
      'id': '10000001',
      "parentId": 'xx',
      "zIndex": xx,
      "type": xx,
      "height": xx,
      "width": xx,
      "position": {{
      "x": xx, ## 不能为0
      "y": xx  ## 不能为0
      }},
      "positionAbsolute": {{
         "x": xx, ## 不能为0
         "y": xx  ## 不能为0
      }}
   }}
```

"""

GENERATE_NODE_PROMPT_USER = """
# 输入信息
1. 节点规范：{node_reference} 
2. 参考节点配置模板：{reference_workflow_nodes}
3. 用户需求描述: {user_request}
4. 现有节点配置：{previous_workflow_nodes}
5. 节点ID: {node_id}
6. 节点类型: {node_type}
7. 节点功能需求描述: {node_description}
8. 节点相关边信息: {related_edges}
9. 已创建的节点信息: {existing_nodes}
10. 上一轮的节点信息: {previous_nodes}
11. 上一轮的会话变量信息:{previous_workflow_conversation_variables}
12. 必须修复的上一轮失败原因（高优，若为空说明是首次生成，可忽略本段)，修复建议：{feedback_history}
"""


# 节点功能描述生成提示词模板
GENERATE_NODE_DESCRIPTION_PROMPT_SYSTEM = """
你是一位专业的 Dify 工作流节点功能分析专家，擅长根据用户需求，工作流边信息和节点信息生成详细的节点功能描述。

## 任务目标
根据提供的用户需求和工作流边信息，为工作流中的每个节点生成详细的功能描述。描述应该以自然语言段落形式呈现，详细说明该节点作为数据来源的功能。

## 节点功能要求
1. **节点功能定位**：明确说明该节点在整个工作流中的作用和价值
2. **输出数据规格**：描述输出的数据类型、数据结构、字段含义和数据格式
3. **数据处理逻辑**：说明节点内部的数据处理、转换、计算或生成逻辑
4. 要求保留用户输入的所有相关信息，并结合节点类型特性提供针对性描述

## 输出格式
请输出JSON格式的节点功能描述列表，包含以下字段：
- node_id：节点ID（对应边的source或者target字段）
- node_type：节点类型（对应边的sourceType或者targetType字段）
- node_description：节点功能描述（自然语言段落）

确保输出所有节点的功能描述，保持描述的专业性和准确性。

请为工作流中的每个节点生成详细的功能描述，输出JSON格式如下：
```json
[
  {{
    "node_id": "节点ID",
    "node_type": "节点类型",
    "node_description": "详细的节点功能描述段落"
  }}
]
```
"""

GENERATE_NODE_DESCRIPTION_PROMPT_USER = """
请根据以下信息生成节点功能描述：

1. 用户需求：{user_request}
2. 工作流边信息：{edges_info}
3. 完整的节点列表信息：{nodes_info}
4. 缺失节点反馈: {missing_nodes_feedback}

"""


# 会话变量生成提示词（advanced-chat 多轮对话）
GENERATE_CONVERSATION_VARIABLES_PROMPT_SYSTEM = """
你是 Dify advanced-chat 多轮对话的会话变量(conversation_variables)设计专家。
你的任务：依据「会话变量使用情况」，「完整节点信息」和「用户需求」，为每个会话变量生成准确的声明，
重点是判断其【数据类型 value_type】与【初始值 value】。

# 输出格式
仅输出一个 JSON 数组，每个元素是一个会话变量声明：
```json
[
  {{
    "name": "会话变量名（与使用情况中的名称完全一致）",
    "value_type": "string | number | boolean | object | array[string] | array[number] | array[boolean] | array[object]",
    "value": "初始值（类型必须与 value_type 匹配：string 用字符串、number 用数字、boolean 用 true/false、array 用数组、object 用对象）",
    "description": "简短中文说明该变量的用途"
  }}
]
```

# 硬性规则
1. 必须、且只能为「会话变量使用情况」中出现的每个 conversation.* 变量生成一条声明，名称完全一致，不得新增或遗漏。
2. value_type 必须与使用方式一致（不同类型支持的 operation 不同，类型必须能容纳其全部写入操作）：
   - assigner 用 append/extend/remove-first/remove-last 写入 → 必须是数组类型（如 array[string]）；这些操作仅数组可用。
   - assigner 用 += / -= / *= / /= 写入 → 必须是 number；数学运算仅 number 可用。
   - 被当作字符串拼接/在文本中以 {{ '{{' }}{{#conversation.x#}}{{ '}}' }} 引用展示 → 通常 string。
   - 存储 JSON 对象/结构化数据 → object。
   - over-write/set 写入时，类型必须与写入的源值类型一致（数组源 → 数组类型，绝不能声明为 string）。
   - 类型-操作兼容矩阵（务必让所声明的 value_type 支持该变量被使用到的所有 operation）：
     · 通用（所有类型）：over-write、clear。
     · number：额外支持 set、+=、-=、*=、/=。
     · string / boolean / object：额外仅支持 set（不支持 append/extend/数学运算）。
     · array[*]：额外支持 append、extend、remove-first、remove-last（不支持 set/数学运算）。
   - 若同一变量同时出现互斥操作（如既 append 又 +=），说明前序节点配置有误，请按"被读取/展示方式"与"用户需求"选择最合理且自洽的单一类型，不要为迁就错误操作而选错类型。
3. 初始值必须语义正确，并与分支条件保持一致：
   - 轮次计数器(number)：若 if-else 首轮（紧接开场）判断为 current_round == 0，则初值为 0；若判断为 == 1，则初值为 1。务必让"首轮分支条件"在初始状态下成立。
   - string 通常初值为空串 ""；数组通常为空数组 []；object 通常为空对象 {{}}；boolean 按语义给 false/true。
4. 不要臆造未被使用的会话变量；不要把 sys.* / 节点输出当作会话变量。

请只输出 JSON 数组，不要输出多余解释。
"""

GENERATE_CONVERSATION_VARIABLES_PROMPT_USER = """
# 用户需求
{user_request}

# 完整节点信息（工作流全部节点配置，用于结合上下文准确判断会话变量的类型与初值）
{nodes_info}

# 会话变量使用情况（从节点中确定性抽取的事实，聚焦各 conversation.* 的写入/分支/读取）
{conversation_variable_usage}
"""

