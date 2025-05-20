import os
import sqlite3
import sys
from datetime import datetime
from typing import Dict, Any

import yaml
from loguru import logger

# 全局变量，用于标记日志系统是否已初始化
_logger_initialized = False

def setup_logger(log_level: str = "INFO") -> Dict:
    """
    统一的日志系统初始化函数

    Args:
        log_level: 日志级别，默认为INFO

    Returns:
        包含日志路径信息的字典
    """
    global _logger_initialized

    # 如果日志系统已初始化，直接返回
    if _logger_initialized:
        # 获取当前日志文件路径
        current_date = datetime.now().strftime("%Y/%m/%d")
        year_month = current_date.rsplit("/", 1)[0]  # 年/月 部分
        day_only = current_date.split('/')[-1]  # 只取日期中的"日"部分
        log_dir = f'output/logs/{year_month}/{day_only}'
        main_log_file = f'{log_dir}/{day_only}.log'
        error_log_file = f'{log_dir}/error_{day_only}.log'

        return {
            "log_dir": log_dir,
            "main_log_file": main_log_file,
            "error_log_file": error_log_file
        }

    # 创建日志目录
    current_date = datetime.now().strftime("%Y/%m/%d")
    year_month = current_date.rsplit("/", 1)[0]  # 年/月 部分
    day_only = current_date.split('/')[-1]  # 只取日期中的"日"部分

    # 日志文件夹路径(年/月/日)
    log_dir = f'output/logs/{year_month}/{day_only}'
    os.makedirs(log_dir, exist_ok=True)

    # 日志文件路径
    main_log_file = f'{log_dir}/{day_only}.log'
    error_log_file = f'{log_dir}/error_{day_only}.log'

    # 移除默认处理器
    logger.remove()

    # 配置全局上下文信息
    logger.configure(extra={"app_name": "BilibiliHistoryFetcher", "version": "1.0.0"})

    # 添加控制台处理器（仅INFO级别以上，只显示消息，无时间戳等）
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{message}</green>",
        filter=lambda record: (
            # 只有以特定字符开头的信息才输出到控制台
            isinstance(record["message"], str) and
            record["message"].startswith(("===", "正在", "已", "成功", "错误:", "警告:"))
        ),
        enqueue=True,  # 确保控制台输出也是进程安全的
        diagnose=False  # 禁用诊断以避免日志循环
    )

    # 添加文件处理器（完整日志信息）
    logger.add(
        main_log_file,
        level=log_level,
        format="[{time:YYYY-MM-DD HH:mm:ss}] [{level}] [{extra[app_name]}] [v{extra[version]}] [进程:{process}] [线程:{thread}] [{name}] [{file.name}:{line}] [{function}] {message}\n{exception}",
        encoding="utf-8",
        enqueue=True,  # 启用进程安全的队列
        diagnose=False,  # 禁用诊断信息，避免不必要的栈跟踪导致的死锁
        backtrace=False,  # 禁用异常回溯，避免不必要的栈跟踪
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",  # 保留30天的日志
        compression="zip"  # 压缩旧日志
    )

    # 专门用于记录错误级别日志的处理器
    logger.add(
        error_log_file,
        level="ERROR",  # 只记录ERROR及以上级别
        format="[{time:YYYY-MM-DD HH:mm:ss}] [{level}] [{extra[app_name]}] [{name}] [{file.name}:{line}] [{function}] {message}\n{exception}",
        encoding="utf-8",
        enqueue=True,
        diagnose=False,  # 禁用诊断信息
        backtrace=False,  # 禁用异常回溯
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",
        compression="zip"
    )

    # 标记日志系统已初始化
    _logger_initialized = True

    return {
        "log_dir": log_dir,
        "main_log_file": main_log_file,
        "error_log_file": error_log_file
    }

# 初始化日志系统
setup_logger()


def get_base_path() -> str:
    """获取项目基础路径"""
    if getattr(sys, 'frozen', False):
        # 如果是打包后的exe运行，返回exe所在目录
        return os.path.dirname(sys.executable)
    else:
        # 如果是直接运行python脚本
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_config_path(config_file: str) -> str:
    """
    获取配置文件路径
    Args:
        config_file: 配置文件名
    Returns:
        配置文件的完整路径
    """
    if getattr(sys, 'frozen', False):
        # 如果是打包后的exe运行，配置文件在_internal/config目录中
        base_path = os.path.dirname(sys.executable)
        return os.path.join(base_path, '_internal', 'config', config_file)
    else:
        # 如果是直接运行python脚本
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, 'config', config_file)

def load_config() -> Dict[str, Any]:
    """加载配置文件并验证"""
    try:
        config_path = get_config_path('config.yaml')
        if not os.path.exists(config_path):
            # 打印更多调试信息
            base_path = get_base_path()
            logger.debug(f"\n=== 配置文件信息 ===")
            logger.debug(f"当前基础路径: {base_path}")
            logger.debug(f"尝试加载配置文件: {config_path}")
            logger.debug(f"当前目录内容: {os.listdir(base_path)}")
            if os.path.exists(os.path.dirname(config_path)):
                logger.debug(f"配置目录内容: {os.listdir(os.path.dirname(config_path))}")
            logger.debug("=====================\n")
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 验证邮件配置
        email_config = config.get('email', {})
        required_fields = ['smtp_server', 'smtp_port', 'sender', 'password', 'receiver']
        missing_fields = [field for field in required_fields if not email_config.get(field)]

        if missing_fields:
            raise ValueError(f"邮件配置缺少必要字段: {', '.join(missing_fields)}")

        return config
    except Exception as e:
        logger.error(f"加载配置文件失败: {str(e)}")
        raise

def get_output_path(*paths: str) -> str:
    """
    获取输出文件路径
    Args:
        *paths: 路径片段
    Returns:
        完整的输出路径
    """
    # 总是使用exe所在目录（或项目根目录）作为基础路径
    base_path = get_base_path()

    # 基础输出目录
    output_dir = os.path.join(base_path, 'output')

    # 创建基础输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 组合完整路径
    full_path = os.path.join(output_dir, *paths)

    # 确保父目录存在
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    return full_path

def get_database_path(*paths: str) -> str:
    """
    获取数据库文件路径
    Args:
        *paths: 路径片段
    Returns:
        完整的数据库路径
    """
    # 总是使用exe所在目录（或项目根目录）作为基础路径
    base_path = get_base_path()

    # 基础数据库目录
    database_dir = os.path.join(base_path, 'output', 'database')

    # 创建基础数据库目录
    if not os.path.exists(database_dir):
        os.makedirs(database_dir)

    # 组合完整路径
    full_path = os.path.join(database_dir, *paths)

    # 确保父目录存在
    parent_dir = os.path.dirname(full_path)
    if parent_dir != database_dir:  # 避免重复创建database_dir
        os.makedirs(parent_dir, exist_ok=True)

    return full_path

def get_logs_path() -> str:
    """获取日志文件路径"""
    current_time = datetime.now()
    log_path = get_output_path(
        'logs',
        str(current_time.year),
        f"{current_time.month:02d}",
        f"{current_time.day:02d}.log"
    )
    return log_path

def get_db():
    """获取数据库连接"""
    db_path = get_database_path('bilibili_history.db')
    return sqlite3.connect(db_path)
