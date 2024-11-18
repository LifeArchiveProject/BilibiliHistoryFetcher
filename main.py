import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

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
    title_analytics
)
from scripts.scheduler_manager import SchedulerManager
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

# 全局调度器实例
scheduler_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global scheduler_manager
    
    print("正在启动应用...")
    
    try:
        # 初始化调度器
        scheduler_manager = SchedulerManager.get_instance(app)
        
        # 创建异步任务运行调度器
        scheduler_task = asyncio.create_task(scheduler_manager.run_scheduler())
        
        print("应用启动完成")
        
        yield
        
        # 关闭时
        print("正在关闭应用...")
        if scheduler_manager:
            scheduler_manager.stop_scheduler()
            # 取消调度器任务
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        
        # 恢复原始的 stdout
        if hasattr(sys.stdout, 'stdout'):
            sys.stdout = sys.stdout.stdout
            
        print("应用已关闭")
        
    except Exception as e:
        print(f"应用启动/关闭过程中出错: {e}")
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
app.include_router(analysis.router, prefix="/analysis", tags=["Analysis"])
app.include_router(fetch_bili_history.router, prefix="/fetch", tags=["Fetch"])
app.include_router(export.router, prefix="/export", tags=["Export"])
app.include_router(import_data_mysql.router, prefix="/importMysql", tags=["Import"])
app.include_router(import_data_sqlite.router, prefix="/importSqlite", tags=["Import"])
app.include_router(clean_data.router, prefix="/clean", tags=["Clean"])
app.include_router(heatmap.router, prefix="/heatmap", tags=["Heatmap"])
app.include_router(send_log.router, prefix="/log", tags=["Log"])
app.include_router(download.router, prefix="/download", tags=["Download"])
app.include_router(history.router, prefix="/BiliHistory2024", tags=["History"])
app.include_router(categories.router, prefix="/BiliHistory2024", tags=["Categories"])
app.include_router(viewing_analytics.router, prefix="/viewing-analytics", tags=["ViewingAnalytics"])
app.include_router(title_analytics.router, prefix="/title-analytics", tags=["TitleAnalytics"])

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
