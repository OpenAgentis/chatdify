"""字段处理器"""
import logging
from typing import Dict, Any, Optional, Type
from functools import wraps

logger = logging.getLogger(__name__)

class FieldProcessor:
    """字段处理器"""
    
    # 基础类型映射配置
    BASE_TYPE_MAPPING = {
        'bool': (bool, 'Bool'),
        'str': (str, 'Str', 'String'),
        'int': (int, 'Int', 'Integer'),
        'float': (float, 'Float'),
        'bytes': (bytes, 'Bytes'),
        'bytearray': (bytearray, 'ByteArray'),
        'complex': (complex, 'Complex'),
        'frozenset': (frozenset, 'FrozenSet'),
    }
    
    # 集合类型映射配置
    COLLECTION_TYPE_MAPPING = {
        'list': (list, 'List', 'Sequence'),
        'dict': (dict, 'Dict', 'Mapping'),
        'set': (set, 'Set', 'AbstractSet'),
        'tuple': (tuple, 'Tuple'),
    }
    
    # 运算符类型映射
    OPERATOR_TYPE_MAPPING = {
        'and': (bool.__and__, 'And'),
        'or': (bool.__or__, 'Or'),
        'xor': (bool.__xor__, 'Xor'),
        'lt': (int.__lt__, 'Lt', 'LessThan'),
        'le': (int.__le__, 'Le', 'LessEqual'),
        'eq': (int.__eq__, 'Eq', 'Equal'),
        'ne': (int.__ne__, 'Ne', 'NotEqual'),
        'gt': (int.__gt__, 'Gt', 'GreaterThan'),
        'ge': (int.__ge__, 'Ge', 'GreaterEqual'),
    }

    # 类型映射配置
    TYPE_MAPPING = {
        **BASE_TYPE_MAPPING,
        **COLLECTION_TYPE_MAPPING,
        **OPERATOR_TYPE_MAPPING,
    }

    # 基本类型默认值映射
    TYPE_DEFAULT_MAPPING = {
        'bool': False,
        'str': '',
        'int': 0,
        'float': 0.0,
        'list': [],
        'dict': {},
        'tuple': (),
        'set': set(),
        'frozenset': frozenset(),
        'bytes': b'',
        'bytearray': bytearray(),
        'complex': 0j,
        # 运算符默认值
        'and': False,
        'or': False,
        'xor': False,
        'lt': 0,
        'le': 0,
        'eq': 0,
        'ne': 0,
        'gt': 0,
        'ge': 0,
    }
    
    @staticmethod
    def safe_process(func):
        """错误处理装饰器"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"处理字段时出错: {str(e)}")
                return None
        return wrapper
    
    @staticmethod
    def process_model_fields(model_fields: Dict[str, Any], default_config: Dict[str, Any]) -> None:
        """递归处理模型字段的默认值"""
        for field_name, field in model_fields.items():
            if field_name in default_config:
                continue
                
            if hasattr(field, 'is_required') and not field.is_required():
                continue
                
            FieldProcessor._process_field(field_name, field, default_config)
    
    @staticmethod
    def _is_type_match(origin: Any, type_info: tuple) -> bool:
        """统一的类型匹配检查"""
        base_type, *type_names = type_info
        return (origin == base_type or 
                any(str(origin).endswith(name) for name in type_names))

    @staticmethod
    def _get_collection_type(origin: Any) -> Optional[str]:
        """获取集合类型"""
        # print(f"_get_collection_type: origin: {origin}")
        for type_name, type_info in FieldProcessor.COLLECTION_TYPE_MAPPING.items():
            if FieldProcessor._is_type_match(origin, type_info):
                return type_name
        return None
    
    @staticmethod
    def _get_default_value(field: Any) -> Any:
        """统一的默认值获取逻辑"""
        if hasattr(field, 'default') and field.default is not None and str(field.default) != 'PydanticUndefined':
            return field.default
            
        if hasattr(field, 'default_factory') and field.default_factory is not None:
            try:
                return field.default_factory()
            except Exception as e:
                logger.warning(f"执行default_factory时出错: {str(e)}")
                
        return None
    
    @staticmethod
    @safe_process
    def _process_field(field_name: str, field: Any, default_config: Dict[str, Any]) -> None:
        """处理各种字段类型的逻辑"""
        
        if 'optional' in str(field.annotation).lower():
            FieldProcessor._process_optional_field(field_name, field, default_config)
            return 
        
        if hasattr(field.annotation, 'model_fields'):
            FieldProcessor._process_nested_model(field_name, field, default_config)
            return 
        
        if hasattr(field.annotation, '__origin__'):
            origin_name = field.annotation.__origin__.__name__
            # print(f"_process_field: origin_name: {origin_name}")

            # 处理 Literal 类型
            if origin_name == 'Literal' and hasattr(field.annotation, '__args__'):
                default_config[field_name] = field.annotation.__args__[0]
                return
                
            if origin_name == 'Union':
                FieldProcessor._process_union_type(field_name, field, default_config)
                return 
         
        FieldProcessor._process_regular_field(field_name, field, default_config)
    
    @staticmethod
    @safe_process
    def _process_optional_field(field_name: str, field: Any, default_config: Dict[str, Any]) -> None:
        """处理可选字段"""
        # print(f"_process_optional_field: field_name: {field_name}, field: {field}")
        if field_name not in default_config:
            default_config[field_name] = FieldProcessor._get_default_value(field)

    @staticmethod
    @safe_process
    def _process_nested_model(field_name: str, field: Any, default_config: Dict[str, Any]) -> None:
        """处理嵌套模型字段"""
        # print(f"_process_nested_model: field_name: {field_name}, field: {field}")
        if field_name not in default_config:
            default_config[field_name] = {}
            
        if hasattr(field.annotation, 'model_fields'):
            FieldProcessor.process_model_fields(field.annotation.model_fields, default_config[field_name])
       
        elif isinstance(default_config[field_name], dict):
            for k, v in list(default_config[field_name].items()):
                if hasattr(v, 'value'):
                    default_config[field_name][k] = v.value

    @staticmethod
    @safe_process
    def _process_union_type(field_name: str, field: Any, default_config: Dict[str, Any]) -> None:
        """处理Union类型的字段"""
        # print(f"_process_union_type: field_name: {field_name}, field: {field}")
        if field_name in default_config:
            return
            
        type_args = field.annotation.__args__ if hasattr(field.annotation, '__args__') else []
        
        # 处理类型的优先级顺序
        processors = [
            ('enum', FieldProcessor._process_enum_type),
            ('nested', FieldProcessor._process_nested_type),
            ('basic', FieldProcessor._get_type_default),
        ]
        
        for _, processor in processors:
            for type_option in type_args:
                if type_option == type(None):  # noqa
                    continue
                    
                # 处理字面量类型
                if hasattr(type_option, '__forward_arg__'):
                    default_config[field_name] = str(type_option.__forward_arg__)
                    return
                    
                # 处理基本类型
                if isinstance(type_option, type):
                    result = processor(type_option)
                    if result is not None:
                        default_config[field_name] = result
                        return
                        
                # 处理复杂类型
                result = processor(type_option)
                if result is not None:
                    default_config[field_name] = result
                    return
        
        default_config[field_name] = None
    
    
    @staticmethod
    @safe_process
    def _process_enum_type(type_option: Any) -> Any:
        """处理枚举类型"""
        if hasattr(type_option, 'value'):
            return type_option.value
            
        if hasattr(type_option, '__members__'):
            return next(iter(type_option.__members__.values())).value
            
        return None

    @staticmethod
    @safe_process
    def _process_nested_type(type_option: Any) -> Any:
        """处理嵌套类型"""
        if hasattr(type_option, 'model_fields'):
            result = {}
            FieldProcessor.process_model_fields(type_option.model_fields, result)
            return result
        return None

    @staticmethod
    @safe_process
    def _process_regular_field(field_name: str, field: Any, default_config: Dict[str, Any]) -> None:
        """处理普通字段"""
        # print(f"_process_regular_field: field_name: {field_name}, field: {field}")

        if field_name not in default_config:
            # 特殊处理 Union[Sequence[...], ...]
            if hasattr(field.annotation, '__args__'):
                for arg in field.annotation.__args__:
                    if hasattr(arg, '__origin__') and arg.__origin__.__name__ == 'Sequence':
                        default_config[field_name] = []
                        return

            value = FieldProcessor.get_field_type_default(field)

            # print(f"get_field_type_default: field_name: {field_name}, value: {value}")

            if value is not None:
                default_config[field_name] = value
            else:
                default_config[field_name] = FieldProcessor._get_default_value(field)

    @staticmethod
    def get_field_type_default(field: Any) -> Any:
        """根据字段类型获取默认值"""
        # print(f"get_field_type_default: field: {field}")

        if hasattr(field, 'value'):
            return field.value
            
        # 处理枚举类型
        if hasattr(field, 'annotation'):
            enum_default = FieldProcessor._get_enum_default(field)
            if enum_default is not None:
                return enum_default

        # 获取注解类型
        annotation = getattr(field, 'annotation', field)
        
        # 处理泛型类型
        if hasattr(annotation, '__origin__'):
            origin = annotation.__origin__
            # 处理集合类型
            collection_type = FieldProcessor._get_collection_type(origin)
            if collection_type:
                return FieldProcessor.TYPE_DEFAULT_MAPPING[collection_type]
            # 处理字面量类型
            if str(origin).endswith('Literal'):
                args = annotation.__args__
                if args:
                    return args[0]
                    
        # 处理基本类型
        if isinstance(annotation, type):
            ret = FieldProcessor._get_type_default(annotation)
            # print(f"get_field_type_default: {annotation}, ret: {ret}")
            return ret
        
        return None

    @staticmethod
    def _get_type_default(type_cls: Type) -> Any:
        """获取类型的默认值"""
        # print(f"_get_type_default: type_cls: {type_cls}")
        try:
            # 处理基本类型
            for type_name, type_info in FieldProcessor.TYPE_MAPPING.items():
                base_type = type_info[0]
                if isinstance(type_cls, type) and issubclass(type_cls, base_type):
                    return FieldProcessor.TYPE_DEFAULT_MAPPING[type_name]
            
            # 处理字面量类型
            if hasattr(type_cls, '__forward_arg__'):
                return str(type_cls.__forward_arg__)
                
        except (TypeError, AttributeError):
            pass
            
        return None

    @staticmethod
    def _get_enum_default(field: Any) -> Any:
        """获取枚举类型的默认值"""
        # print(f"_get_enum_default: field: {field}")
        try:
            if hasattr(field.annotation, '__members__') and field.annotation.__members__:
                return next(iter(field.annotation.__members__.values())).value
            
            if hasattr(field.annotation, '__args__'):
                for arg in field.annotation.__args__:
                    if hasattr(arg, '__members__') and arg.__members__:
                        return next(iter(arg.__members__.values())).value
        except Exception as e:
            logger.warning(f"获取枚举默认值时出错: {str(e)}")
                    
        return None


