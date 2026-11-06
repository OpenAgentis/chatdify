"""日志工具模块"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Dict, List

LOG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"


class LoggerFactory:
    """日志工厂类：控制台输出到 stderr（stdout 留给 DSL 结果），同时写入 ``<log_dir>/system.log``。"""

    _loggers: Dict[str, logging.Logger] = {}
    _handlers: List[logging.Handler] = []

    @classmethod
    def _build_handlers(cls) -> List[logging.Handler]:
        if cls._handlers:
            return cls._handlers

        from chatdify.settings import get_settings

        settings = get_settings()
        formatter = logging.Formatter(LOG_FORMAT)
        handlers: List[logging.Handler] = []

        try:
            settings.log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                settings.log_dir / "system.log",
                maxBytes=100 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except OSError as e:
            print(f"chatdify: cannot write logs to {settings.log_dir}: {e}", file=sys.stderr)

        if settings.log_to_console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(formatter)
            handlers.append(console_handler)

        cls._handlers = handlers
        return handlers

    @classmethod
    def _level(cls) -> int:
        from chatdify.settings import get_settings

        return getattr(logging, get_settings().log_level.upper(), logging.INFO)

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """获取日志记录器"""
        if name in cls._loggers:
            return cls._loggers[name]

        logger = logging.getLogger(name)
        logger.propagate = False
        logger.setLevel(cls._level())
        for handler in cls._build_handlers():
            logger.addHandler(handler)
        cls._loggers[name] = logger
        return logger

    @classmethod
    def reset(cls) -> None:
        """settings 变化后重建所有 handler（日志目录、级别、是否输出到控制台）。"""
        for handler in cls._handlers:
            handler.close()
        old_handlers = cls._handlers
        cls._handlers = []
        new_handlers = cls._build_handlers()
        level = cls._level()
        for logger in cls._loggers.values():
            for handler in old_handlers:
                logger.removeHandler(handler)
            for handler in new_handlers:
                logger.addHandler(handler)
            logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器的便捷方法"""
    return LoggerFactory.get_logger(name)
