"""
日志配置模块

简化版日志系统：
1. 控制台输出：用于开发调试
2. 应用日志文件：记录所有日志（自动轮转）
3. 错误日志文件：仅记录ERROR级别（便于快速排查）
4. 业务行为记录：已迁移到数据库 activity_logs 表
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path


# ============== 日志配置函数 ==============
def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "./logs",
    app_name: str = "SwingPro2",
    json_format: bool = False,
) -> logging.Logger:
    """
    配置应用日志系统（精简版）

    Args:
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_dir: 日志文件目录
        app_name: 应用名称
        json_format: 保留参数（暂不使用）
    """
    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 获取根 logger（放开到 DEBUG，具体输出由各 handler 级别控制）
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    handler_level = getattr(logging, log_level.upper(), logging.INFO)

    # 清除已有的 handlers
    root_logger.handlers.clear()

    # ===== 1. 控制台 Handler（开发调试用）=====
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(handler_level)
    console_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    console_handler.setFormatter(logging.Formatter(console_format, datefmt="%H:%M:%S"))
    root_logger.addHandler(console_handler)

    # ===== 2. 应用日志文件（所有级别，按时间轮转）=====
    app_log_file = log_path / f"{app_name}.log"
    # 使用 TimedRotatingFileHandler 以便按日期归档，缓解多进程轮转竞争问题，并提供清晰的时间顺序
    app_handler = logging.handlers.TimedRotatingFileHandler(
        app_log_file,
        when="midnight",
        interval=1,
        backupCount=30,  # 保留30天
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)

    # 增加 %(name)s 和 %(lineno)d 以便于定位代码位置
    file_format = "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"
    app_handler.setFormatter(logging.Formatter(file_format, datefmt="%Y-%m-%d %H:%M:%S"))
    root_logger.addHandler(app_handler)

    # ===== 3. 错误日志文件（仅ERROR及以上）=====
    error_log_file = log_path / f"{app_name}.error.log"
    error_handler = logging.handlers.TimedRotatingFileHandler(
        error_log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(file_format, datefmt="%Y-%m-%d %H:%M:%S"))
    root_logger.addHandler(error_handler)

    # ===== 第三方库日志级别（减少噪音）=====
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)  # 屏蔽 multipart 解析的详细 debug
    logging.getLogger("python_multipart").setLevel(logging.WARNING)
    logging.getLogger("python_multipart.multipart").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING) # 屏蔽热重载监控日志

    return root_logger


# ============== 便捷函数 ==============
def get_logger(name: str = None) -> logging.Logger:
    """获取 logger 实例"""
    return logging.getLogger(name)


# 保留旧接口兼容性（但不再使用）
def get_access_logger() -> logging.Logger:
    """访问日志已迁移到数据库 activity_logs 表"""
    return logging.getLogger("app")


def get_audit_logger() -> logging.Logger:
    """审计日志已迁移到数据库 activity_logs 表"""
    return logging.getLogger("app")
