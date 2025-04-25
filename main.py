import asyncio
import os
import platform
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from routers import (
    analysis,
    clean_data,
    export,
    fetch_bili_history,
    import_data_mysql,
    import_data_sqlite,
    heatmap,
    send_log,
    download,
    history,
    categories,
    viewing_analytics,
    title_analytics,
    daily_count,
    login,
    delete_history,
    image_downloader,
    scheduler,
    video_summary,
    deepseek,
    audio_to_text,
    email_config,
    comment,
    data_sync,
    favorite,
    popular_videos
)
from scripts.popular_videos import schedule_daily_cleanup
from scripts.scheduler_db_enhanced import EnhancedSchedulerDB
from scripts.scheduler_manager import SchedulerManager
from scripts.utils import load_config


# 配置日志系统
def setup_logging():
    """设置Loguru日志系统"""
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
        )
    )
    
    # 添加文件处理器（完整日志信息）
    file_handler_id = logger.add(
        main_log_file,  
        level="INFO",
        format="[{time:YYYY-MM-DD HH:mm:ss}] [{level}] [{extra[app_name]}] [v{extra[version]}] [进程:{process}] [线程:{thread}] [{name}] [{file.name}:{line}] [{function}] {message}\n{exception}",
        encoding="utf-8",
        enqueue=True,  # 启用进程安全的队列
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",  # 保留30天的日志
        compression="zip",  # 压缩旧日志
        backtrace=True,  # 启用异常回溯
        diagnose=True    # 启用诊断信息
    )
    
    # 专门用于记录错误级别日志的处理器
    error_handler_id = logger.add(
        error_log_file,
        level="ERROR",  # 只记录ERROR及以上级别
        format="[{time:YYYY-MM-DD HH:mm:ss}] [{level}] [{extra[app_name]}] [{name}] [{file.name}:{line}] [{function}] {message}\n{exception}",
        encoding="utf-8",
        enqueue=True,
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",
        compression="zip",
        backtrace=True,
        diagnose=True
    )
    
    # 重定向系统异常到日志
    logger.add(
        lambda msg: sys.__stderr__.write(f"{msg}\n"),
        level="ERROR", 
        format="<red>系统错误: {message}</red>",
        backtrace=True, 
        diagnose=True
    )
    
    # 重定向 print 输出到日志
    class PrintToLogger:
        def __init__(self, stdout):
            self.stdout = stdout
            self._line_buffer = []
            self._is_shutting_down = False  # 标记系统是否正在关闭
            
        def write(self, buf):
            # 如果系统正在关闭，直接写入原始stdout而不经过logger
            if self._is_shutting_down:
                self.stdout.write(buf)
                return
                
            # 跳过uvicorn日志
            if any(skip in buf for skip in [
                'INFO:', 'ERROR:', 'WARNING:', '[32m', '[0m', 
                'Application', 'Started', 'Waiting', 'HTTP',
                'uvicorn', 'DEBUG'
            ]):
                # 只写入到控制台
                self.stdout.write(buf)
                return
                
            # 检测是否是关闭信息
            if "应用关闭" in buf or "Shutting down" in buf:
                self._is_shutting_down = True
                
            # 收集完整的行
            for c in buf:
                if c == '\n':
                    line = ''.join(self._line_buffer).rstrip()
                    if line:  # 只记录非空行
                        try:
                            # 使用loguru记录，但保持控制台干净
                            if not self._is_shutting_down:
                                logger.opt(depth=1).log("INFO", line)
                            else:
                                # 关闭阶段直接写入控制台
                                self.stdout.write(f"{line}\n")
                        except Exception:
                            # 如果记录失败，写入原始stdout
                            self.stdout.write(f"{line}\n")
                    self._line_buffer = []
                else:
                    self._line_buffer.append(c)
        
        def flush(self):
            if self._line_buffer:
                line = ''.join(self._line_buffer).rstrip()
                if line:
                    if not self._is_shutting_down:
                        try:
                            logger.opt(depth=1).log("INFO", line)
                        except Exception:
                            self.stdout.write(f"{line}\n")
                    else:
                        self.stdout.write(f"{line}\n")
                self._line_buffer = []
            self.stdout.flush()
        
        def isatty(self):
            return self.stdout.isatty()
        
        def fileno(self):
            return self.stdout.fileno()
        
        # 在应用关闭阶段调用，标记关闭状态
        def mark_shutdown(self):
            self._is_shutting_down = True
    
    # 保存原始的stdout并重定向
    original_stdout = sys.stdout
    sys.stdout = PrintToLogger(original_stdout)
    
    # 配置uvicorn日志与loguru集成
    # 拦截标准库logging
    import logging
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # 获取对应的Loguru级别名称
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
                
            # 获取调用者的文件名和行号
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            
            # 记录到日志文件，但不输出到控制台
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )
    
    # 替换所有标准库的日志处理器
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # 返回当前日志文件夹路径和文件信息
    return {
        "log_dir": log_dir,
        "main_log_file": main_log_file,
        "error_log_file": error_log_file
    }

# 在应用启动时调用
setup_logging()

# 检查系统资源（针对Linux系统）
is_linux = platform.system().lower() == "linux"
if is_linux:
    try:
        from scripts.system_resource_check import check_system_resources
        resources = check_system_resources()
        if not resources["summary"]["can_run_speech_to_text"]:
            limitation = resources.get("summary", {}).get("resource_limitation", "未知原因")
            logger.warning(f"警告: 系统资源不足，语音转文字功能将被禁用。限制原因: {limitation}")
            logger.info(f"系统信息: 内存: {resources['memory']['total_gb']}GB (可用: {resources['memory']['available_gb']}GB), "
                      f"CPU: {resources['cpu']['physical_cores']}核心, 磁盘可用空间: {resources['disk']['free_gb']}GB")
    except ImportError:
        logger.warning("警告: 未安装psutil模块，无法检查系统资源。如需使用语音转文字功能，请安装psutil: pip install psutil")
    except Exception as e:
        logger.warning(f"警告: 检查系统资源时出错: {str(e)}")

# 全局调度器实例
scheduler_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global scheduler_manager
    
    logger.info("正在启动应用...")
    
    try:
        # 初始化增强版数据库
        EnhancedSchedulerDB.get_instance()
        logger.info("已初始化增强版调度器数据库")
        
        # 初始化调度器
        scheduler_manager = SchedulerManager.get_instance(app)
        
        # 显示调度器配置
        logger.info(f"调度器配置:")
        logger.info(f"  基础URL: {scheduler_manager.base_url}")
        logger.info(f"  (从 config/config.yaml 的 server 配置生成)")
        
        # 检查基础URL是否包含协议前缀
        if not scheduler_manager.base_url.startswith(('http://', 'https://')):
            logger.warning(f"  警告: 基础URL不包含协议前缀，这可能导致任务执行错误")
            logger.warning(f"  建议: 检查服务器配置确保正确构建URL")
        
        # 创建异步任务运行调度器
        scheduler_task = asyncio.create_task(scheduler_manager.run_scheduler())

        logger.success("=== 应用启动完成 ===")
        logger.info(f"启动时间: {datetime.now().isoformat()}")
        
        yield
        
        # 关闭时
        logger.info("\n=== 应用关闭阶段 ===")
        logger.info(f"开始时间: {datetime.now().isoformat()}")
        
        # 标记stdout重定向器为关闭状态，防止重入
        if hasattr(sys.stdout, 'mark_shutdown'):
            sys.stdout.mark_shutdown()
        
        if scheduler_manager:
            logger.info("正在停止调度器...")
            scheduler_manager.stop_scheduler()
            # 取消调度器任务
            scheduler_task.cancel()
            try:
                logger.info("等待调度器任务完成...")
                await scheduler_task
            except asyncio.CancelledError:
                logger.info("调度器任务已取消")
        
        # 恢复原始的 stdout
        if hasattr(sys.stdout, 'stdout'):
            logger.info("正在恢复标准输出...")
            sys.stdout = sys.stdout.stdout
            
        logger.success("=== 应用关闭完成 ===")
        logger.info(f"结束时间: {datetime.now().isoformat()}")
        
        # 清理日志处理器，防止关闭时的死锁
        # 注意：必须在所有日志记录之后调用
        logger_handlers = logger._core.handlers.copy()  # 复制处理器列表
        for handler_id in logger_handlers:
            logger.remove(handler_id)
            
    except Exception as e:
        logger.error(f"\n=== 应用生命周期出错 ===")
        logger.error(f"错误信息: {str(e)}")
        logger.error(f"错误类型: {type(e).__name__}")
        # Loguru会自动提供详细堆栈
        logger.exception("应用生命周期异常")
        raise

# 创建 FastAPI 应用实例
app = FastAPI(
    title="Bilibili History Analyzer",
    description="一个用于分析和导出Bilibili观看历史的API",
    version="1.0.0",
    lifespan=lifespan
)

# 添加启动状态端点
@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "scheduler_status": "running" if scheduler_manager and scheduler_manager.is_running else "stopped"
    }

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头部
)

# 注册路由
app.include_router(login.router, prefix="/login", tags=["用户登录"])
app.include_router(analysis.router, prefix="/analysis", tags=["数据分析"])
app.include_router(clean_data.router, prefix="/clean", tags=["数据清洗"])
app.include_router(export.router, prefix="/export", tags=["数据导出"])
app.include_router(fetch_bili_history.router, prefix="/fetch", tags=["历史记录获取"])
app.include_router(import_data_mysql.router, prefix="/importMysql", tags=["MySQL数据导入"])
app.include_router(import_data_sqlite.router, prefix="/importSqlite", tags=["SQLite数据导入"])
app.include_router(heatmap.router, prefix="/heatmap", tags=["热力图生成"])
app.include_router(send_log.router, prefix="/log", tags=["日志发送"])
app.include_router(download.router, prefix="/download", tags=["视频下载"])
app.include_router(history.router, prefix="/history", tags=["历史记录管理"])
app.include_router(categories.router, prefix="/categories", tags=["分类管理"])
app.include_router(viewing_analytics.router, prefix="/viewing", tags=["观看时间分析"])
app.include_router(title_analytics.router, prefix="/title", tags=["标题分析"])
app.include_router(daily_count.router, prefix="/daily", tags=["每日观看统计"])
app.include_router(delete_history.router, prefix="/delete", tags=["删除历史记录"])
app.include_router(image_downloader.router, prefix="/images", tags=["图片下载管理"])
app.include_router(scheduler.router, prefix="/scheduler", tags=["计划任务管理"])
app.include_router(video_summary.router, prefix="/summary", tags=["视频摘要"])
app.include_router(deepseek.router, prefix="/deepseek", tags=["DeepSeek AI"])
app.include_router(audio_to_text.router, prefix="/audio_to_text", tags=["音频转文字"])
app.include_router(email_config.router, prefix="/config", tags=["配置管理"])
app.include_router(comment.router, prefix="/comment", tags=["评论管理"])
app.include_router(data_sync.router, prefix="/data_sync", tags=["数据同步与完整性检查"])
app.include_router(favorite.router, prefix="/favorite", tags=["收藏夹管理"])
app.include_router(popular_videos.router, prefix="/bilibili", tags=["B站热门"])

# 入口点，启动应用
if __name__ == "__main__":
    import uvicorn
    import atexit
    import signal
    
    # 配置日志系统
    log_info = setup_logging()
    
    # 信号处理函数
    def signal_handler(sig, frame):
        print(f"\n接收到信号 {sig}，正在优雅关闭...")
        # 标记stdout为关闭状态
        if hasattr(sys.stdout, 'mark_shutdown'):
            sys.stdout.mark_shutdown()
        sys.exit(0)
    
    # 注册信号处理函数
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 终止信号
    
    # 注册退出时清理函数
    @atexit.register
    def cleanup_at_exit():
        print("程序退出，正在清理资源...")
        # 恢复原始stdout
        if hasattr(sys.stdout, 'stdout'):
            sys.stdout = sys.stdout.stdout
        # 移除所有日志处理器
        logger.info("正在关闭日志系统...")
        handlers = list(logger._core.handlers.keys())
        for handler_id in handlers:
            try:
                logger.remove(handler_id)
            except:
                pass
        print("日志系统已关闭")
    
    # 加载配置
    config = load_config()
    server_config = config.get('server', {})
    
    # 检查是否启用SSL
    ssl_enabled = server_config.get('ssl_enabled', False)
    ssl_certfile = server_config.get('ssl_certfile', None)
    ssl_keyfile = server_config.get('ssl_keyfile', None)
    
    # 使用SSL证书启动应用（如果启用）
    if ssl_enabled and ssl_certfile and ssl_keyfile:
        logger.info(f"使用HTTPS启动服务，端口: {server_config.get('port', 8899)}")
        logger.info(f"SSL证书路径: {ssl_certfile}")
        logger.info(f"SSL密钥路径: {ssl_keyfile}")
        try:
            # 检查证书文件是否存在
            if not os.path.exists(ssl_certfile):
                logger.error(f"错误: SSL证书文件不存在: {ssl_certfile}")
                sys.exit(1)
            
            if not os.path.exists(ssl_keyfile):
                logger.error(f"错误: SSL密钥文件不存在: {ssl_keyfile}")
                sys.exit(1)
            
            # 检查文件权限
            logger.info(f"证书文件权限: {oct(os.stat(ssl_certfile).st_mode)[-3:]}")
            logger.info(f"密钥文件权限: {oct(os.stat(ssl_keyfile).st_mode)[-3:]}")
            
            uvicorn.run(
                "main:app",
                host=server_config.get('host', "127.0.0.1"),
                port=server_config.get('port', 8899),
                log_level="debug",  # 修改为debug级别
                reload=False,  # 禁用热重载以避免多个调度器实例
                ssl_certfile=ssl_certfile,
                ssl_keyfile=ssl_keyfile
            )
        except Exception as e:
            logger.error(f"启动服务时出错: {e}")
            traceback.print_exc()
    else:
        logger.info(f"使用HTTP启动服务，端口: {server_config.get('port', 8899)}")
        uvicorn.run(
            "main:app",
            host=server_config.get('host', "127.0.0.1"),
            port=server_config.get('port', 8899),
            log_level="info",
            reload=False  # 禁用热重载以避免多个调度器实例
        )
