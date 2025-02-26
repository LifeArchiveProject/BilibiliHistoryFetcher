import asyncio
import logging
import os
import sys
import threading
from datetime import datetime
from typing import Optional

import httpx
import schedule
import yaml

from scripts.scheduler_db import SchedulerDB  # 导入新的数据库模块
from scripts.utils import get_base_path, load_config

# 配置日志记录
logger = logging.getLogger(__name__)

class SchedulerManager:
    _instance = None
    _lock = threading.Lock()  # 添加线程锁
    
    @classmethod
    def get_instance(cls, app=None) -> 'SchedulerManager':
        """获取 SchedulerManager 的单例实例"""
        if not cls._instance:
            with cls._lock:  # 使用线程锁确保线程安全
                if not cls._instance:  # 双重检查
                    if app is None:
                        raise ValueError("First initialization requires app instance")
                    cls._instance = cls(app)
        return cls._instance

    def __init__(self, app):
        """初始化调度管理器"""
        # 防止重复初始化
        if hasattr(self, '_initialized'):  # 检查是否已初始化
            return
            
        self.app = app
        self.tasks = {}
        self.daily_tasks = {}
        self.task_chains = {}  # 通过依赖关系构建的任务链
        self.scheduler = None
        self.task_status = {}
        self.chain_status = {}
        self.is_running = False
        self.log_capture = None
        self.current_log_file = None
        # 移除默认值，确保配置必须从配置文件中读取
        self.base_url = None
        
        # 初始化数据库
        self.db = SchedulerDB.get_instance()
        
        # 加载配置（会设置self.base_url）
        self.load_config()
        self._initialized = True  # 标记为已初始化

    def load_config(self):
        """加载调度配置"""
        try:
            # 使用 get_base_path 获取基础路径
            base_path = get_base_path()
            if getattr(sys, 'frozen', False):
                # 如果是打包后的exe运行，配置文件应该在_internal目录中
                config_path = os.path.join(base_path, 'config', 'scheduler_config.yaml')
            else:
                # 如果是直接运行python脚本
                config_path = os.path.join('config', 'scheduler_config.yaml')
            
            # 打印调试信息
            print(f"\n=== 调度器配置信息 ===")
            print(f"基础路径: {base_path}")
            print(f"配置文件路径: {config_path}")
            print(f"配置文件存在: {os.path.exists(config_path)}")
            
            # 如果配置文件不存在，尝试其他可能的位置
            if not os.path.exists(config_path):
                alternative_paths = [
                    os.path.join(os.path.dirname(sys.executable), 'config', 'scheduler_config.yaml'),
                    os.path.join(os.getcwd(), 'config', 'scheduler_config.yaml'),
                    os.path.join(base_path, '_internal', 'config', 'scheduler_config.yaml'),
                    os.path.join(os.path.dirname(base_path), 'config', 'scheduler_config.yaml')
                ]
                print("\n尝试其他可能的配置文件位置:")
                for alt_path in alternative_paths:
                    print(f"检查: {alt_path} - {'存在' if os.path.exists(alt_path) else '不存在'}")
                    if os.path.exists(alt_path):
                        config_path = alt_path
                        break
            
            # 打印目录内容
            print("\n目录内容:")
            print(f"基础目录 ({base_path}): {os.listdir(base_path)}")
            config_dir = os.path.dirname(config_path)
            if os.path.exists(config_dir):
                print(f"配置目录 ({config_dir}): {os.listdir(config_dir)}")
            print("=====================\n")
            
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"找不到配置文件: {config_path}")
                
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
                # 读取base_url，必须存在
                if 'base_url' in config:
                    self.base_url = config['base_url']
                    print(f"从配置文件读取base_url: {self.base_url}")
                else:
                    raise KeyError(f"配置文件中缺少必要的'base_url'配置项，请检查配置文件: {config_path}")
                
                # 更新任务配置
                old_tasks = self.tasks.copy() if hasattr(self, 'tasks') else {}
                self.tasks = config.get('tasks', {})
                
                # 如果是重新加载配置，检查任务调度时间是否有变化
                if old_tasks:
                    for task_id, task in self.tasks.items():
                        if task_id in old_tasks:
                            old_task = old_tasks[task_id]
                            # 检查调度时间是否变化
                            if ('schedule' in task and 'schedule' in old_task and
                                task['schedule'].get('type') == 'daily' and old_task['schedule'].get('type') == 'daily' and
                                task['schedule'].get('time') != old_task['schedule'].get('time')):
                                print(f"任务 {task_id} 的调度时间已变更: {old_task['schedule'].get('time')} -> {task['schedule'].get('time')}")
                
            logging.info(f"成功加载调度配置")
            logging.info(f"已配置的任务: {list(self.tasks.keys())}")
            
            # 分类任务
            self.daily_tasks = {}
            for task_id, task in self.tasks.items():
                schedule = task.get('schedule', {})
                if schedule.get('type') == 'daily':
                    self.daily_tasks[task_id] = task
                    # 打印每日任务的调度时间
                    print(f"每日任务: {task_id}, 调度时间: {schedule.get('time')}")
            
            # 构建任务链
            self.task_chains = self._build_task_chains()
            
            # 初始化数据库中的任务状态记录
            self._init_task_status_in_db()
            
        except Exception as e:
            logging.error(f"加载配置文件失败: {e}")
            raise
            
    def _init_task_status_in_db(self):
        """初始化数据库中的任务状态记录"""
        for task_id, task in self.tasks.items():
            # 检查任务是否已在数据库中存在
            task_status = self.db.get_task_status(task_id)
            if not task_status:
                # 新任务，添加到数据库
                self.db.update_task_status(task_id, {
                    'name': task.get('name', task_id),
                    'enabled': 1
                })

    def _build_task_chains(self):
        """构建任务链（基于任务依赖关系）"""
        task_chains = {}
        
        # 查找不依赖其他任务的任务（作为链的起点）
        for task_id, task in self.tasks.items():
            if not task.get('requires', []):
                chain = self._build_chain_from_task(task_id)
                if chain:
                    task_chains[task_id] = chain
        
        return task_chains
    
    def _build_chain_from_task(self, start_task_id: str, visited=None):
        """从一个起始任务构建任务链"""
        if visited is None:
            visited = set()
            
        if start_task_id in visited:
            # 检测到循环依赖
            logger.warning(f"检测到循环依赖: {start_task_id}")
            return None
        
        visited.add(start_task_id)
        chain = [start_task_id]
        
        # 查找依赖这个任务的其他任务
        for task_id, task in self.tasks.items():
            requires = task.get('requires', [])
            if start_task_id in requires:
                sub_chain = self._build_chain_from_task(task_id, visited.copy())
                if sub_chain:
                    chain.extend(sub_chain)
        
        return chain

    async def execute_task(self, task_id: str) -> bool:
        """执行单个任务"""
        print(f"\n=== 执行任务: {task_id} ===")
        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 检查任务是否存在
            if task_id not in self.tasks:
                print(f"错误: 任务 {task_id} 不存在")
                return False
            
            task = self.tasks[task_id]
            print(f"开始执行任务: {task['name']}")
            
            # 创建后台任务并等待其完成
            task_result = await self.execute_task_chain(task_id)
            
            print(f"任务 {task_id} 执行完成")
            return task_result
        
        except Exception as e:
            print(f"执行任务时发生错误: {str(e)}")
            return False

    async def execute_task_chain(self, task_id: str) -> bool:
        """执行任务链"""
        print(f"\n=== 执行任务链: {task_id} ===")
        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 检查任务是否存在
            if task_id not in self.tasks:
                print(f"错误: 任务 {task_id} 不存在")
                return False
            
            # 获取任务链
            task_chain = self._build_chain_from_task(task_id)
            if not task_chain:
                print(f"错误: 无法构建任务 {task_id} 的执行链")
                return False
            
            print(f"任务链: {' -> '.join(task_chain)}")
            
            # 依次执行任务链中的每个任务
            for chain_task_id in task_chain:
                print(f"\n执行链中的任务: {chain_task_id}")
                
                # 设置当前正在执行的任务链
                self.current_chain = task_id
                
                # 执行任务并等待完成
                success = await self._execute_single_task(chain_task_id)
                
                if not success:
                    print(f"任务链执行失败: {chain_task_id} 执行失败")
                    return False
                
            print(f"\n任务链执行完成: {task_id}")
            return True
            
        except Exception as e:
            print(f"执行任务链时发生错误: {str(e)}")
            return False
        finally:
            # 清除当前任务链标记
            self.current_chain = None

    def find_next_task(self, current_task: str) -> Optional[str]:
        """查找下一个要执行的任务"""
        for task_name, task in self.tasks.items():
            if 'requires' in task and current_task in task['requires']:
                return task_name
        return None

    def schedule_tasks(self):
        """设置任务调度"""
        print("\n=== 开始设置任务调度 ===")
        now = datetime.now()
        print(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 先清除所有现有的调度任务
        schedule.clear()
        schedule.jobs.clear()  # 确保完全清除所有任务
        print("已清除所有现有调度任务")
        
        # 重置所有任务的状态
        self.task_status.clear()
        print(f"当前已配置的任务: {list(self.tasks.keys())}")
        
        # 创建一个同步的执行函数
        def sync_execute_task(task_name):
            print(f"\n=== 调度器触发任务执行 ===")
            print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"任务名称: {task_name}")
            
            # 获取或创建事件循环
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 在事件循环中执行异步任务
            try:
                # 创建任务并等待其完成
                task = loop.create_task(self.execute_task_chain(task_name))
                loop.run_until_complete(asyncio.gather(task))
            except Exception as e:
                print(f"执行任务时发生错误: {str(e)}")
            finally:
                # 如果我们创建了新的事件循环，需要关闭它
                if loop and not loop.is_running():
                    loop.close()
        
        for task_name, task in self.tasks.items():
            print(f"\n--- 处理任务: {task_name} ---")
            if 'schedule' in task:
                schedule_info = task['schedule']
                schedule_type = schedule_info['type']
                print(f"调度类型: {schedule_type}")
                
                if schedule_type == 'daily':
                    # 获取任务的启用状态
                    task_status = self.db.get_task_status(task_name)
                    is_enabled = True
                    if task_status and 'enabled' in task_status:
                        is_enabled = bool(task_status['enabled'])
                    print(f"任务状态: {'启用' if is_enabled else '禁用'}")
                    
                    # 只调度启用的任务
                    if is_enabled:
                        time_str = schedule_info['time']
                        print(f"调度时间: {time_str}")
                        
                        # 计算下次执行时间
                        next_run = self._calculate_next_run_time(time_str)
                        if next_run:
                            next_run_str = next_run.strftime('%Y-%m-%d %H:%M:%S')
                            self.db.update_task_status(task_name, {'next_run_time': next_run_str})
                            print(f"计算的下次执行时间: {next_run_str}")
                            time_diff = (next_run - now).total_seconds() / 60
                            print(f"距离现在: {time_diff:.1f} 分钟")
                            
                            # 使用schedule库设置任务
                            try:
                                # 确保时间格式正确
                                if ':' not in time_str or len(time_str.split(':')) != 2:
                                    raise ValueError(f"时间格式不正确: {time_str}, 应为 HH:MM 格式")
                                
                                print(f"正在设置schedule任务...")
                                # 使用同步函数包装异步执行
                                job = schedule.every().day.at(time_str).do(
                                    sync_execute_task, task_name
                                )
                                
                                # 验证任务是否已正确设置
                                if job in schedule.jobs:
                                    print(f"任务已成功添加到调度队列")
                                else:
                                    print(f"警告: 任务可能未成功添加到调度队列")
                            except Exception as e:
                                print(f"设置任务调度失败: {str(e)}")
                        else:
                            print(f"警告: 无法计算下次执行时间")
                    else:
                        print(f"任务已禁用，跳过调度")
                
                elif schedule_type == 'once':
                    # 检查任务是否已执行过
                    task_status = self.db.get_task_status(task_name)
                    if task_status and task_status.get('last_run_time'):
                        print(f"一次性任务 {task_name} 已执行过，跳过")
                        continue
                    
                    delay = schedule_info.get('delay', 0)
                    print(f"设置一次性任务: {task_name}, {delay}秒后执行")
                    
                    # 使用同步函数包装异步执行
                    def delayed_sync_execute(task_name, delay):
                        import time
                        print(f"等待{delay}秒后执行任务: {task_name}")
                        time.sleep(delay)
                        sync_execute_task(task_name)
                    
                    # 在新线程中执行延迟任务
                    import threading
                    thread = threading.Thread(
                        target=delayed_sync_execute,
                        args=(task_name, delay)
                    )
                    thread.daemon = True
                    thread.start()
        
        # 打印最终的调度状态
        print("\n=== 当前调度状态 ===")
        if not schedule.jobs:
            print("没有已调度的任务")
        else:
            for job in schedule.jobs:
                print(f"- {job}")
                if hasattr(job, 'next_run') and job.next_run:
                    time_diff = (job.next_run - now).total_seconds() / 60
                    print(f"  下次执行时间: {job.next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"  距离现在: {time_diff:.1f} 分钟")
        
        print("\n=== 任务调度设置完成 ===")

    def _calculate_next_run_time(self, time_str, allow_today=True):
        """计算下次执行时间
        
        Args:
            time_str: 时间字符串，格式为 HH:MM
            allow_today: 是否允许将今天的时间作为下次执行时间
        
        Returns:
            datetime: 下次执行时间
        """
        try:
            # 解析时间字符串，格式为 HH:MM
            hour, minute = map(int, time_str.split(':'))
            
            # 获取当前时间
            now = datetime.now()
            print(f"计算下次执行时间 - 当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"计算下次执行时间 - 目标时间: {time_str}")
            
            # 创建今天的执行时间
            today_run_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            print(f"计算下次执行时间 - 今天的执行时间: {today_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 计算时间差（分钟）
            time_diff_minutes = (today_run_time - now).total_seconds() / 60
            print(f"时间差: {time_diff_minutes:.1f} 分钟")
            
            # 如果目标时间在未来，直接使用今天的时间
            if time_diff_minutes > 0:
                next_run = today_run_time
                print(f"目标时间在未来，使用今天的时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                # 如果目标时间已过，使用明天的时间
                from datetime import timedelta
                next_run = today_run_time + timedelta(days=1)
                print(f"目标时间已过，使用明天的时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            
            return next_run
        except Exception as e:
            error_msg = f"计算下次执行时间失败: {str(e)}"
            print(error_msg)
            logging.error(error_msg, exc_info=True)
            return None

    async def run_scheduler(self):
        """运行调度器"""
        print(f"\n=== 开始运行调度器 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===")
        
        # 重新加载配置并设置任务
        self.load_config()
        schedule.clear()
        schedule.jobs.clear()
        self.task_status.clear()
        self.chain_status.clear()
        self.schedule_tasks()
        
        # 打印初始调度状态
        if schedule.jobs:
            print("\n当前已调度的任务:")
            for job in schedule.jobs:
                if hasattr(job, 'next_run') and job.next_run:
                    print(f"- {job}")
                    print(f"  下次执行时间: {job.next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("\n没有已调度的任务")
        
        self.is_running = True
        last_check_minute = -1
        
        while self.is_running:
            try:
                now = datetime.now()
                current_minute = now.minute
                
                # 每分钟检查一次任务状态
                if current_minute != last_check_minute:
                    last_check_minute = current_minute
                    schedule.run_pending()
                
                # 等待1秒
                await asyncio.sleep(1)
            except Exception as e:
                error_msg = f"调度器运行错误: {str(e)}"
                print(f"\n!!! 调度器错误: {error_msg}")
                logging.error(error_msg, exc_info=True)
                
                await asyncio.sleep(60)  # 出错后等待60秒再重试
                self.reload_scheduler()

    def stop_scheduler(self):
        """停止调度器"""
        self.is_running = False
        
        # 关闭数据库连接
        if hasattr(self, 'db'):
            self.db.close()

    def reload_scheduler(self):
        """重新加载调度配置"""
        print("\n=== 重新加载调度配置 ===")
        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 清除所有现有的调度任务
        schedule.clear()
        schedule.jobs.clear()  # 确保完全清除所有任务
        print("已清除所有现有调度任务")
        
        # 清除内部状态
        self.task_status.clear()
        self.chain_status.clear()
        
        # 重新加载配置
        self.load_config()
        
        # 重新设置调度
        self.schedule_tasks()
        
        # 打印当前的调度状态
        print("\n当前调度状态:")
        for job in schedule.jobs:
            print(f"- {job}")
            if hasattr(job, 'next_run') and job.next_run:
                time_diff = (job.next_run - datetime.now()).total_seconds() / 60
                print(f"  下次执行时间: {job.next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  距离现在: {time_diff:.1f} 分钟")
        
        print("\n调度配置重新加载完成")
        
    def update_task_enabled_status(self, task_id: str, enabled: bool):
        """更新任务的启用状态并重新加载调度配置"""
        if task_id not in self.tasks:
            return False
            
        # 更新数据库中的任务状态
        self.db.update_task_status(task_id, {'enabled': 1 if enabled else 0})
        
        # 重新加载调度配置
        self.reload_scheduler()
        
        return True
        
    def update_task_schedule_time(self, task_id: str, new_time: str):
        """更新任务的调度时间"""
        print(f"\n=== 更新任务调度时间 ===")
        print(f"任务ID: {task_id}")
        print(f"新的调度时间: {new_time}")
        
        try:
            # 1. 检查任务是否存在
            if task_id not in self.tasks:
                print(f"错误: 任务 {task_id} 不存在")
                return False
            
            # 2. 验证时间格式
            try:
                datetime.strptime(new_time, "%H:%M")
            except ValueError:
                print(f"错误: 无效的时间格式 {new_time}，应为 HH:MM")
                return False
            
            # 3. 更新内存中的任务配置
            print("更新内存中的任务配置...")
            self.tasks[task_id]['schedule']['time'] = new_time
            
            # 4. 保存到配置文件
            print("保存配置到文件...")
            self._save_config_to_file()
            
            # 5. 停止当前调度器
            print("停止当前调度器...")
            old_running = self.is_running
            self.is_running = False
            schedule.clear()
            schedule.jobs.clear()
            
            # 6. 重新加载配置
            print("重新加载配置...")
            self.load_config()
            
            # 7. 重新设置所有任务的调度
            print("重新设置任务调度...")
            self.schedule_tasks()
            
            # 8. 恢复调度器状态
            print("恢复调度器状态...")
            self.is_running = old_running
            
            # 9. 检查新任务是否已正确设置
            print("\n=== 检查新的调度设置 ===")
            found = False
            now = datetime.now()
            for job in schedule.jobs:
                if task_id in str(job):
                    found = True
                    next_run = job.next_run
                    time_diff = (next_run - now).total_seconds() / 60
                    print(f"找到任务: {job}")
                    print(f"下次执行时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"距离现在: {time_diff:.1f} 分钟")
            
            if not found:
                print(f"警告: 未找到任务 {task_id} 的新调度设置")
                return False
            
            print("\n任务调度时间更新成功")
            return True
            
        except Exception as e:
            print(f"更新任务调度时间时发生错误: {str(e)}")
            return False
        
    def _save_config_to_file(self):
        """保存当前配置到文件"""
        try:
            # 使用与加载相同的路径逻辑
            base_path = get_base_path()
            if getattr(sys, 'frozen', False):
                config_path = os.path.join(base_path, 'config', 'scheduler_config.yaml')
            else:
                config_path = os.path.join('config', 'scheduler_config.yaml')
                
            # 如果配置文件不存在，尝试其他可能的位置
            if not os.path.exists(config_path):
                alternative_paths = [
                    os.path.join(os.path.dirname(sys.executable), 'config', 'scheduler_config.yaml'),
                    os.path.join(os.getcwd(), 'config', 'scheduler_config.yaml'),
                    os.path.join(base_path, '_internal', 'config', 'scheduler_config.yaml'),
                    os.path.join(os.path.dirname(base_path), 'config', 'scheduler_config.yaml')
                ]
                for alt_path in alternative_paths:
                    if os.path.exists(alt_path):
                        config_path = alt_path
                        break
            
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"找不到配置文件: {config_path}")
                
            # 先读取现有配置，以保留其他设置
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            # 更新任务配置
            config['tasks'] = self.tasks
            
            # 写回文件
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
                
            print(f"配置已保存到: {config_path}")
            return True
        except Exception as e:
            logging.error(f"保存配置文件失败: {str(e)}")
            raise

    def sync_execute_task(self, task_name):
        """同步执行任务的包装函数"""
        print(f"\n=== 同步执行任务: {task_name} ===")
        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 获取或创建事件循环
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 在事件循环中执行任务
            try:
                # 创建任务并等待其完成
                task = asyncio.ensure_future(self.execute_task_chain(task_name), loop=loop)
                loop.run_until_complete(task)
                return task.result()
            finally:
                # 如果我们创建了新的事件循环，需要关闭它
                if loop and not loop.is_running():
                    loop.close()
        except Exception as e:
            print(f"执行任务时发生错误: {str(e)}")
            return False

    async def _execute_single_task(self, task_id: str) -> bool:
        """执行单个任务的内部方法"""
        print(f"\n=== 执行单个任务: {task_id} ===")
        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 检查任务是否存在
            if task_id not in self.tasks:
                print(f"错误: 任务 {task_id} 不存在")
                return False
            
            # 检查任务状态
            task_status = self.db.get_task_status(task_id) or {}
            if not task_status.get('enabled', True):
                print(f"任务 {task_id} 已禁用，跳过执行")
                return False
            
            task = self.tasks[task_id]
            print(f"任务配置: {task}")
            
            # 记录任务开始执行
            start_time = datetime.now()
            start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
            triggered_by = "manual" if not hasattr(self, 'current_chain') else f"chain:{self.current_chain}"
            
            url = f"{self.base_url}{task['endpoint']}"
            method = task.get('method', 'GET').upper()
            params = task.get('params', {})
            
            print(f"准备发送请求:")
            print(f"- URL: {url}")
            print(f"- 方法: {method}")
            print(f"- 参数: {params}")
            
            # 设置超时时间
            timeout = task.get('timeout', 300)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method == 'GET':
                    response = await client.get(url, params=params)
                else:
                    response = await client.post(url, json=params)
                    
                end_time = datetime.now()
                end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
                duration = (end_time - start_time).total_seconds()
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "success":
                        print(f"任务 {task_id} 执行成功")
                        self.task_status[task_id] = True
                        # 记录成功的执行历史
                        self.db.record_task_execution(
                            task_id=task_id,
                            start_time=start_time_str,
                            end_time=end_time_str,
                            duration=duration,
                            status="success",
                            triggered_by=triggered_by,
                            output=str(result)
                        )
                        return True
                    else:
                        error_msg = result.get('message', '未知错误')
                        print(f"任务 {task_id} 执行失败: {error_msg}")
                        self.task_status[task_id] = False
                        # 记录失败的执行历史
                        self.db.record_task_execution(
                            task_id=task_id,
                            start_time=start_time_str,
                            end_time=end_time_str,
                            duration=duration,
                            status="fail",
                            error_message=error_msg,
                            triggered_by=triggered_by
                        )
                        return False
                else:
                    error_msg = f"请求失败: {response.status_code} - {response.text}"
                    print(f"任务 {task_id} 请求失败: {response.status_code}")
                    self.task_status[task_id] = False
                    # 记录请求失败的执行历史
                    self.db.record_task_execution(
                        task_id=task_id,
                        start_time=start_time_str,
                        end_time=end_time_str,
                        duration=duration,
                        status="fail",
                        error_message=error_msg,
                        triggered_by=triggered_by
                    )
                    return False
                
        except Exception as e:
            end_time = datetime.now()
            end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            duration = (end_time - start_time).total_seconds()
            error_msg = str(e)
            print(f"执行任务时发生错误: {error_msg}")
            self.task_status[task_id] = False
            # 记录异常的执行历史
            self.db.record_task_execution(
                task_id=task_id,
                start_time=start_time_str,
                end_time=end_time_str,
                duration=duration,
                status="fail",
                error_message=error_msg,
                triggered_by=triggered_by
            )
            return False

async def send_error_notification(error_message):
    """发送错误通知邮件"""
    config = load_config()
    email_config = config.get('email', {})
    
    subject = "Bilibili历史记录分析任务执行出错"
    body = f"""
    执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    错误信息: {error_message}
    """
    
    try:
        await send_email(
            email_config.get('smtp_server'),
            email_config.get('smtp_port'),
            email_config.get('sender'),
            email_config.get('password'),
            email_config.get('receiver'),
            subject,
            body
        )
    except Exception as e:
        print(f"发送错误通知邮件失败: {e}")
        logging.error(f"发送错误通知邮件失败: {e}", exc_info=True)