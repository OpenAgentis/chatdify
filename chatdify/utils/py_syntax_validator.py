import ast
from typing import Dict, Set, List, Tuple, Optional



class MainFunctionValidator:
    """Main函数验证器，检查main函数的返回值一致性"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate_code(self, code: str) -> Dict[str, any]:
        """
        验证代码中的main函数
        
        Args:
            code: 要验证的Python代码字符串
            
        Returns:
            包含验证结果的字典
        """
        self.errors = []
        self.warnings = []
        
        try:
            # 解析代码为AST
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "valid": False,
                "has_main": False,
                "errors": [self._format_syntax_error(code, e)],
                "warnings": []
            }
        
        # 查找main函数
        main_function = self._find_main_function(tree)
        
        if not main_function:
            return {
                "valid": False,
                "has_main": False,
                "errors": ["未找到main函数"],
                "warnings": []
            }
        
        # 验证main函数的返回值
        validation_result = self._validate_main_function(main_function)
        
        return {
            "valid": len(self.errors) == 0,
            "has_main": True,
            "errors": self.errors,
            "warnings": self.warnings,
            **validation_result
        }
    
    @staticmethod
    def _format_syntax_error(code: str, exc: SyntaxError) -> str:
        """
        将 Python SyntaxError 格式化成更具可操作性的错误信息。

        把出错行（含行号）以及最贴合的修复建议一起返回，避免重试时大模型
        仅看到 "unterminated string literal (detected at line 16)" 这类
        没有源码上下文的信息而难以定位修复点。
        """
        lines = code.splitlines()
        lineno = exc.lineno if isinstance(exc.lineno, int) else None
        col = exc.offset if isinstance(exc.offset, int) else None
        raw_msg = exc.msg or str(exc)

        source_line = ""
        if lineno and 1 <= lineno <= len(lines):
            source_line = lines[lineno - 1]

        # 针对常见的字符串未闭合等错误，给出修复方向，
        # 让模型在重试时能直接修正而不是反复同样的问题。
        hint = ""
        lowered = raw_msg.lower()
        if "unterminated" in lowered and "string" in lowered:
            hint = (
                "请检查该行字符串是否正确闭合：1) 引号是否成对（'' 或 \"\"）；"
                "2) 多行字符串请改用三引号 \"\"\"...\"\"\" 或 '''...'''；"
                "3) 字符串内若包含反斜杠（如正则、Windows 路径），建议改用 r\"...\" 原始字符串；"
                "4) 字符串内若包含与外层相同的引号，请改用另一种引号或使用反斜杠转义。"
            )
        elif "eol while scanning" in lowered:
            hint = "字符串在行尾未闭合，请补齐结束引号或改用三引号。"
        elif "unexpected eof" in lowered or "was never closed" in lowered:
            hint = "存在未闭合的括号/引号，请检查 ()、[]、{}、'/\" 是否成对。"
        elif "invalid syntax" in lowered:
            hint = "请检查该行的缩进、冒号、运算符、关键字拼写以及是否缺少括号。"
        elif "f-string" in lowered:
            hint = "f-string 内的表达式不能再使用与外层相同的引号，建议拆分表达式或更换引号。"
        elif "unicodeescape" in lowered or "truncated \\u" in lowered:
            hint = (
                "字符串中的反斜杠被解释为 \\u 转义序列。请使用原始字符串 r\"...\"，"
                "或将每个反斜杠双写为 \\\\（适用于 Windows 路径、正则表达式等场景）。"
            )

        parts = [f"语法错误: {raw_msg}"]
        if lineno:
            location = f"第 {lineno} 行"
            if col:
                location += f" 第 {col} 列"
            parts.append(location)
        if source_line:
            parts.append(f"出错代码: {source_line.rstrip()}")
        if hint:
            parts.append(f"修复建议: {hint}")
        return " | ".join(parts)

    def _find_main_function(self, tree: ast.AST) -> Optional[ast.FunctionDef]:
        """查找main函数定义"""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                return node
        return None
    
    def _validate_main_function(self, main_func: ast.FunctionDef) -> Dict[str, any]:
        """验证main函数的返回值一致性"""
        # 收集所有返回语句
        return_statements = self._collect_return_statements(main_func)
        
        if not return_statements:
            self.errors.append("main函数必须有返回值")
            return {"return_analysis": {}}
        
        # 分析返回分支
        normal_returns, exception_returns = self._analyze_return_branches(main_func)
        
        # 验证返回值一致性
        consistency_result = self._check_return_consistency(normal_returns, exception_returns)
        
        return {
            "return_analysis": {
                "normal_returns": normal_returns,
                "exception_returns": exception_returns,
                "consistency": consistency_result,
                "return_entry_types": self._aggregate_return_entry_types(main_func),
            }
        }
    
    def _collect_return_statements(self, func_node: ast.FunctionDef) -> List[ast.Return]:
        """收集函数中的所有return语句"""
        returns = []
        for node in ast.walk(func_node):
            if isinstance(node, ast.Return):
                returns.append(node)
        return returns
    
    def _analyze_return_branches(self, func_node: ast.FunctionDef) -> Tuple[List[Set[str]], List[Set[str]]]:
        """分析正常返回和异常返回分支"""
        normal_returns = []
        exception_returns = []
        
        # 遍历函数体
        for stmt in func_node.body:
            if isinstance(stmt, ast.Try):
                # 处理try-except块
                try_returns = self._extract_returns_from_block(stmt.body)
                normal_returns.extend(try_returns)
                
                # 处理except块
                for handler in stmt.handlers:
                    except_returns = self._extract_returns_from_block(handler.body)
                    exception_returns.extend(except_returns)
                
                # 处理else块
                if stmt.orelse:
                    else_returns = self._extract_returns_from_block(stmt.orelse)
                    normal_returns.extend(else_returns)
                
                # 处理finally块
                if stmt.finalbody:
                    finally_returns = self._extract_returns_from_block(stmt.finalbody)
                    # finally块的返回可能覆盖其他返回
                    if finally_returns:
                        self.warnings.append("finally块中的返回语句可能会覆盖其他返回值")
            
            elif isinstance(stmt, ast.Return):
                # 直接的return语句
                return_vars = self._extract_return_variables(stmt)
                normal_returns.append(return_vars)
        
        return normal_returns, exception_returns
    
    def _extract_returns_from_block(self, block: List[ast.stmt]) -> List[Set[str]]:
        """从代码块中提取返回语句的变量"""
        returns = []
        for stmt in block:
            if isinstance(stmt, ast.Return):
                return_vars = self._extract_return_variables(stmt)
                returns.append(return_vars)
            elif isinstance(stmt, (ast.If, ast.For, ast.While)):
                # 递归处理嵌套结构
                nested_returns = self._extract_returns_from_nested(stmt)
                returns.extend(nested_returns)
        return returns
    
    def _extract_returns_from_nested(self, stmt: ast.stmt) -> List[Set[str]]:
        """从嵌套语句中提取返回值"""
        returns = []
        for node in ast.walk(stmt):
            if isinstance(node, ast.Return) and node != stmt:
                return_vars = self._extract_return_variables(node)
                returns.append(return_vars)
        return returns
    
    def _extract_return_variables(self, return_stmt: ast.Return) -> Set[str]:
        """提取return语句中的变量名"""
        if not return_stmt.value:
            return set()
        
        variables = set()
        
        if isinstance(return_stmt.value, ast.Dict):
            # 处理字典返回值 {"key1": value1, "key2": value2}
            for key in return_stmt.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    variables.add(key.value)
                elif isinstance(key, ast.Str):  # Python < 3.8兼容性
                    variables.add(key.s)
        
        elif isinstance(return_stmt.value, ast.Tuple):
            # 处理元组返回值
            for i, elt in enumerate(return_stmt.value.elts):
                variables.add(f"tuple_element_{i}")
        
        elif isinstance(return_stmt.value, ast.Name):
            # 处理单个变量返回
            variables.add(return_stmt.value.id)
        
        return variables
    
    def _extract_dict_key(self, key_node: ast.AST) -> Optional[str]:
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            return key_node.value
        if isinstance(key_node, ast.Str):  # Python < 3.8
            return key_node.s
        return None

    def _infer_expr_type(self, expr: ast.AST, local_types: Optional[Dict[str, str]] = None) -> Optional[str]:
        """从 AST 表达式推断 Python 值类型（用于 outputs 静态对齐，推断不出返回 None）。"""
        if isinstance(expr, ast.Name):
            if local_types and expr.id in local_types:
                return local_types[expr.id]
            return None
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, bool):
                return "bool"
            if isinstance(expr.value, str):
                return "str"
            if isinstance(expr.value, int):
                return "int"
            if isinstance(expr.value, float):
                return "float"
            return None
        if isinstance(expr, ast.Compare):
            return "bool"
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            return "bool"
        if isinstance(expr, ast.BoolOp):
            # 注意：Python 的 and/or 返回的是某个操作数本身，而非 bool。
            # 仅当所有操作数推断为同一类型时才取该类型，否则无法确定。
            operand_types = {self._infer_expr_type(v, local_types) for v in expr.values}
            if len(operand_types) == 1:
                only = next(iter(operand_types))
                return only  # 可能为 None（推断不出）
            return None
        if isinstance(expr, ast.IfExp):
            body_t = self._infer_expr_type(expr.body, local_types)
            orelse_t = self._infer_expr_type(expr.orelse, local_types)
            if body_t and body_t == orelse_t:
                return body_t
            return None
        if isinstance(expr, ast.List):
            return "list"
        if isinstance(expr, ast.Dict):
            return "dict"
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
            fname = expr.func.id
            if fname == "bool":
                return "bool"
            if fname == "str":
                return "str"
            if fname == "int":
                return "int"
            if fname == "float":
                return "float"
        return None

    def _collect_local_types(self, func_node: ast.FunctionDef) -> Dict[str, str]:
        """收集 main 内简单赋值语句的局部变量类型（如 is_last = current_round >= rounds）。"""
        local_types: Dict[str, str] = {}
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    inferred = self._infer_expr_type(node.value, local_types)
                    if inferred:
                        local_types[target.id] = inferred
        return local_types

    def _extract_return_entry_types(
        self, return_stmt: ast.Return, local_types: Optional[Dict[str, str]] = None
    ) -> Dict[str, Set[str]]:
        """提取 return {{ key: value }} 中各 key 对应 value 的推断类型。"""
        entry_types: Dict[str, Set[str]] = {}
        if not isinstance(return_stmt.value, ast.Dict):
            return entry_types
        for key_node, value_node in zip(return_stmt.value.keys, return_stmt.value.values):
            key = self._extract_dict_key(key_node)
            if not key:
                continue
            inferred = self._infer_expr_type(value_node, local_types)
            if inferred:
                entry_types.setdefault(key, set()).add(inferred)
        return entry_types

    def _aggregate_return_entry_types(self, func_node: ast.FunctionDef) -> Dict[str, Set[str]]:
        """汇总 main 内所有 return 语句里各输出字段的推断类型。"""
        local_types = self._collect_local_types(func_node)
        aggregated: Dict[str, Set[str]] = {}
        for node in ast.walk(func_node):
            if isinstance(node, ast.Return):
                for key, types in self._extract_return_entry_types(node, local_types).items():
                    aggregated.setdefault(key, set()).update(types)
        return aggregated

    def _check_return_consistency(self, normal_returns: List[Set[str]], 
                                exception_returns: List[Set[str]]) -> Dict[str, any]:
        """检查返回值一致性"""
        if not normal_returns and not exception_returns:
            self.errors.append("main函数没有返回语句")
            return {"consistent": False}
        
        # 检查正常返回分支的一致性
        normal_consistent = self._check_branch_consistency(normal_returns, "正常返回分支")
        
        # 检查异常返回分支的一致性
        exception_consistent = self._check_branch_consistency(exception_returns, "异常返回分支")
        
        # 检查正常分支和异常分支之间的一致性
        cross_consistent = True
        if normal_returns and exception_returns:
            normal_vars = normal_returns[0] if normal_returns else set()
            exception_vars = exception_returns[0] if exception_returns else set()

            if normal_vars != exception_vars:
                cross_consistent = False
                self.errors.append(
                    f"正常返回分支和异常返回分支的返回变量不一致，要求保持一致: "
                    f"正常分支={sorted(normal_vars)}, 异常分支={sorted(exception_vars)}"
                )
        
        overall_consistent = normal_consistent and exception_consistent and cross_consistent
        
        return {
            "consistent": overall_consistent,
            "normal_branch_consistent": normal_consistent,
            "exception_branch_consistent": exception_consistent,
            "cross_branch_consistent": cross_consistent
        }
    
    def _check_branch_consistency(self, returns: List[Set[str]], branch_name: str) -> bool:
        """检查单个分支内的返回值一致性"""
        if not returns:
            return True
        
        first_return = returns[0]

        if 'error' in first_return:
            self.errors.append(f"{branch_name}中返回变量名不能包含'error'命名字段。请用其他名字替代，比如'err'。")
            
        for i, return_vars in enumerate(returns[1:], 1):
            if 'error' in return_vars:
                self.errors.append(f"{branch_name}中第{i+1}个返回语句的变量名不能包含'error'命名字段。请用其他名字替代，比如'err'。")
                
            if return_vars != first_return:
                self.errors.append(
                    f"{branch_name}中第{i+1}个返回语句的变量与第1个不一致: "
                    f"第1个={sorted(first_return)}, 第{i+1}个={sorted(return_vars)}"
                )
                return False
        
        return True


# 使用示例和测试函数
def test_validator():
    """测试验证器功能"""
    validator = MainFunctionValidator()
    
    # 测试您提供的示例代码
    test_code = "import json\n\ndef main(json_data: str) -> dict:\n    try:\n        # 提取JSON数据\n        json_text = extract_json_from_markdown(json_data)\n        data = json.loads(json_text)\n        \n        # 生成ECharts HTML模板\n        html_template = \"\"\"\n        <!DOCTYPE html>\n        <html>\n        <head>\n            <meta charset=\"utf-8\">\n            <title>ECharts 可视化</title>\n            <script src=\"https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js\"></script>\n            <style>\n                #chart-container { width: 100%; height: 600px; }\n            </style>\n        </head>\n        <body>\n            <div id=\"chart-container\"></div>\n            <script>\n                var chartDom = document.getElementById('chart-container');\n                var myChart = echarts.init(chartDom);\n                var option = {{chart_config}};\n                myChart.setOption(option);\n            </script>\n        </body>\n        </html>\n        \"\"\"\n        \n        # 将数据转换为ECharts配置\n        chart_config = {\n            \"title\": {\n                \"text\": data.get('title', '数据可视化')\n            },\n            \"tooltip\": {},\n            \"legend\": {\n                \"data\": data.get('categories', [])\n            },\n            \"xAxis\": {\n                \"type\": 'category',\n                \"data\": data.get('xAxis', [])\n            },\n            \"yAxis\": {},\n            \"series\": data.get('series', [])\n        }\n        \n        # 替换模板中的配置\n        html_content = html_template.replace('{{chart_config}}', json.dumps(chart_config))\n        \n        return {\n            \"html\": html_content,\n            \"chart_config\": chart_config\n        }\n        \n    except Exception as e:\n        return {\n            \"error\": str(e),\n            \"html\": \"<p>生成图表时出错: \" + str(e) + \"</p>\",\n            \"chart_config\": {}\n        }\n\ndef extract_json_from_markdown(markdown_text: str) -> str:\n    start = markdown_text.find('```json')\n    if start == -1:\n        start = markdown_text.find('```')\n        if start == -1:\n            return markdown_text.strip()\n    \n    start = markdown_text.find('\\n', start) + 1\n    end = markdown_text.rfind('```')\n    return markdown_text[start:end].strip()"
    test_code = """
def main(cn: str, en: str, jp: str, lang: str) -> dict:
    language_map = {
        "zh-Hans": cn,
        "en-US": en,
        "ja-JP": jp
    }
    return {
        "result": language_map.get(lang, ""),
        "language_map": {
        "zh-Hans": cn,
        "en-US": en,
        "ja-JP": jp
    }
    }"""
    result = validator.validate_code(test_code)
    
    print("验证结果:")
    print(f"代码有效: {result['valid']}")
    print(f"包含main函数: {result['has_main']}")
    
    if result['errors']:
        print("\n错误:")
        for error in result['errors']:
            print(f"  - {error}")
    
    if result['warnings']:
        print("\n警告:")
        for warning in result['warnings']:
            print(f"  - {warning}")
    
    if 'return_analysis' in result:
        analysis = result['return_analysis']
        print(f"\n返回值分析: {analysis}")
        
        print(f"  正常返回分支数量: {len(analysis.get('normal_returns', []))}")
        print(f"  异常返回分支数量: {len(analysis.get('exception_returns', []))}")
        
        if 'consistency' in analysis:
            consistency = analysis['consistency']
            print(f"  返回值一致性: {consistency.get('consistent', False)}")
            print(f"  正常分支一致性: {consistency.get('normal_branch_consistent', False)}")
            print(f"  异常分支一致性: {consistency.get('exception_branch_consistent', False)}")
            print(f"  跨分支一致性: {consistency.get('cross_branch_consistent', False)}")
