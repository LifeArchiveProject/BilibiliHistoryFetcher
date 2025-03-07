import asyncio
import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
import platform

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    email_config
)
from scripts.scheduler_manager import SchedulerManager
from scripts.scheduler_db_enhanced import EnhancedSchedulerDB
from scripts.utils import load_config


# 配置根日志记录器
def setup_logging():
    """设置日志系统"""
    class DailyRotatingHandler(logging.FileHandler):
        def __init__(self, base_path):
            self.base_path = base_path
            self.current_date = None
            # 先获取初始日志文件路径
            current_date = datetime.now().strftime("%Y/%m/%d")
            log_dir = f'output/logs/{current_date.rsplit("/", 1)[0]}'
            os.makedirs(log_dir, exist_ok=True)
            self.log_file = f'output/logs/{current_date}.log'
            
            # 先调用父类的初始化
            super().__init__(self.log_file, mode='a', encoding='utf-8', errors='replace')
            self.current_date = current_date
        
        def update_file(self):
            """更新日志文件路径"""
            current_date = datetime.now().strftime("%Y/%m/%d")
            if current_date != self.current_date:
                self.current_date = current_date
                log_dir = f'output/logs/{current_date.rsplit("/", 1)[0]}'
                os.makedirs(log_dir, exist_ok=True)
                self.log_file = f'output/logs/{current_date}.log'
                
                # 关闭旧的文件流
                self.close()
                
                # 更新文件路径并打开新的文件流
                self.baseFilename = self.log_file
                self._open()
        
        def emit(self, record):
            """发送日志记录"""
            self.update_file()
            super().emit(record)
    
    # 创建日志格式化器
    formatter = logging.Formatter('%(message)s')
    
    # 使用新的处理器
    file_handler = DailyRotatingHandler('output/logs')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)

    # 重定向 print 输出到日志
    class PrintToLogger:
        def __init__(self, logger, stdout):
            self.logger = logger
            self.stdout = stdout
            self._line_buffer = []
        
        def write(self, buf):
            # 跳过调度器和FastAPI的日志
            if any(skip in buf for skip in [
                'INFO:', 'ERROR:', 'WARNING:', '[32m', '[0m', 
                'Application', 'Started', 'Waiting', 'HTTP',
                'uvicorn', 'DEBUG'
            ]):
                # 只写入到控制台
                self.stdout.write(buf)
                return
            
            # 收集完整的行
            for c in buf:
                if c == '\n':
                    line = ''.join(self._line_buffer).rstrip()
                    if line:  # 只记录非空行
                        # 只写入到日志文件，不再写入控制台
                        record = logging.LogRecord(
                            name='print',
                            level=logging.INFO,
                            pathname='',
                            lineno=0,
                            msg=line,
                            args=(),
                            exc_info=None
                        )
                        file_handler.emit(record)
                    self._line_buffer = []
                else:
                    self._line_buffer.append(c)
        
        def flush(self):
            if self._line_buffer:
                line = ''.join(self._line_buffer).rstrip()
                if line:
                    record = logging.LogRecord(
                        name='print',
                        level=logging.INFO,
                        pathname='',
                        lineno=0,
                        msg=line,
                        args=(),
                        exc_info=None
                    )
                    file_handler.emit(record)
                self._line_buffer = []
            self.stdout.flush()
        
        def isatty(self):
            return self.stdout.isatty()
        
        def fileno(self):
            return self.stdout.fileno()

    # 保存原始的 stdout
    original_stdout = sys.stdout
    # 创建新的 PrintToLogger 实例,传入原始 stdout
    sys.stdout = PrintToLogger(root_logger, original_stdout)

    return file_handler.baseFilename

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
            print(f"警告: 系统资源不足，语音转文字功能将被禁用。限制原因: {limitation}")
            print(f"系统信息: 内存: {resources['memory']['total_gb']}GB (可用: {resources['memory']['available_gb']}GB), "
                  f"CPU: {resources['cpu']['physical_cores']}核心, 磁盘可用空间: {resources['disk']['free_gb']}GB")
    except ImportError:
        print("警告: 未安装psutil模块，无法检查系统资源。如需使用语音转文字功能，请安装psutil: pip install psutil")
    except Exception as e:
        print(f"警告: 检查系统资源时出错: {str(e)}")

# 全局调度器实例
scheduler_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global scheduler_manager
    
    print("正在启动应用...")
    
    try:
        # 初始化增强版数据库
        EnhancedSchedulerDB.get_instance()
        print("已初始化增强版调度器数据库")
        
        # 初始化调度器
        scheduler_manager = SchedulerManager.get_instance(app)
        
        # 创建异步任务运行调度器
        scheduler_task = asyncio.create_task(scheduler_manager.run_scheduler())
        
        print("=== 应用启动完成 ===")
        print(f"启动时间: {datetime.now().isoformat()}")
        
        yield
        
        # 关闭时
        print("\n=== 应用关闭阶段 ===")
        print(f"开始时间: {datetime.now().isoformat()}")
        
        if scheduler_manager:
            print("正在停止调度器...")
            scheduler_manager.stop_scheduler()
            # 取消调度器任务
            scheduler_task.cancel()
            try:
                print("等待调度器任务完成...")
                await scheduler_task
            except asyncio.CancelledError:
                print("调度器任务已取消")
        
        # 恢复原始的 stdout
        if hasattr(sys.stdout, 'stdout'):
            print("正在恢复标准输出...")
            sys.stdout = sys.stdout.stdout
            
        print("=== 应用关闭完成 ===")
        print(f"结束时间: {datetime.now().isoformat()}")
        
    except Exception as e:
        print(f"\n=== 应用生命周期出错 ===")
        print(f"错误信息: {str(e)}")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误堆栈:\n{traceback.format_exc()}")
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

# 入口点，启动应用
if __name__ == "__main__":
    import uvicorn
    
    # 加载配置
    config = load_config()
    server_config = config.get('server', {})
    
    uvicorn.run(
        "main:app",
        host=server_config.get('host', "127.0.0.1"),
        port=server_config.get('port', 8000),
        log_level="info",
        reload=False  # 禁用热重载以避免多个调度器实例
    )
