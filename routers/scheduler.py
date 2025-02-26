import logging
import os
from datetime import datetime
from typing import List, Dict, Optional, Any

import yaml
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from scripts.scheduler_db import SchedulerDB  # 导入数据库模块
from scripts.scheduler_manager import SchedulerManager
from scripts.utils import get_base_path
import asyncio

# 配置日志记录
logger = logging.getLogger(__name__)

router = APIRouter()

# 获取调度器实例
def get_scheduler():
    return SchedulerManager.get_instance()

# 获取调度器数据库实例
def get_scheduler_db():
    return SchedulerDB.get_instance()

# 定义模型
class TaskSchedule(BaseModel):
    type: str = Field(..., description="调度类型: daily, chain, once")
    time: Optional[str] = Field(None, description="执行时间 (格式: HH:MM，仅用于daily类型)")
    delay: Optional[int] = Field(None, description="延迟时间(秒)，仅用于once类型")

class TaskModel(BaseModel):
    name: str = Field(..., description="任务显示名称")
    endpoint: str = Field(..., description="API端点")
    method: str = Field("GET", description="HTTP请求方法")
    params: Optional[Dict[str, Any]] = Field(None, description="API参数")
    schedule: TaskSchedule = Field(..., description="调度设置")
    requires: List[str] = Field(default=[], description="依赖任务列表")

class SchedulerConfig(BaseModel):
    base_url: str = Field(..., description="API服务的基础URL")
    tasks: Dict[str, TaskModel] = Field(..., description="任务配置")

class TaskStatus(BaseModel):
    task_id: str
    name: str
    schedule_type: str
    schedule_time: Optional[str] = None
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    status: str = "未执行"
    depends_on: List[str] = []
    enabled: bool = True
    success_rate: Optional[float] = None
    avg_duration: Optional[float] = None
    total_runs: int = 0
    success_runs: int = 0
    fail_runs: int = 0
    last_error: Optional[str] = None
    tags: List[str] = []

class TaskListResponse(BaseModel):
    status: str
    message: str
    tasks: List[TaskStatus]

class TaskActionResponse(BaseModel):
    status: str
    message: str
    task_id: Optional[str] = None

class TaskUpdateRequest(BaseModel):
    name: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    schedule: Optional[TaskSchedule] = None
    requires: Optional[List[str]] = None

class TaskCreateRequest(BaseModel):
    task_id: str = Field(..., description="任务唯一标识")
    name: str = Field(..., description="任务显示名称")
    endpoint: str = Field(..., description="API端点")
    method: str = Field("GET", description="HTTP请求方法")
    params: Optional[Dict[str, Any]] = None
    schedule: TaskSchedule
    requires: List[str] = []

class TaskHistoryItem(BaseModel):
    id: int
    task_id: str
    start_time: str
    end_time: Optional[str] = None
    duration: Optional[float] = None
    status: str
    error_message: Optional[str] = None
    triggered_by: Optional[str] = None

class TaskHistoryResponse(BaseModel):
    status: str
    message: str
    history: List[TaskHistoryItem]

class TaskEnableRequest(BaseModel):
    enabled: bool = Field(..., description="是否启用任务")

class TaskPriorityRequest(BaseModel):
    priority: int = Field(..., description="任务优先级，0-10")

class TaskTagsRequest(BaseModel):
    tags: List[str] = Field(..., description="任务标签列表")

def get_config_path():
    """获取配置文件路径"""
    base_path = get_base_path()
    config_path = os.path.join(base_path, 'config', 'scheduler_config.yaml')
    
    # 如果配置文件不存在，尝试其他可能的位置
    if not os.path.exists(config_path):
        alternative_paths = [
            os.path.join(os.getcwd(), 'config', 'scheduler_config.yaml'),
        ]
        for alt_path in alternative_paths:
            if os.path.exists(alt_path):
                config_path = alt_path
                break
    
    return config_path

def save_config(config):
    """保存配置到文件"""
    config_path = get_config_path()
    
    # 确保目录存在
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)
    
    return True

@router.get("/tasks", summary="获取所有计划任务", response_model=TaskListResponse)
async def get_all_tasks(scheduler: SchedulerManager = Depends(get_scheduler),
                       db: SchedulerDB = Depends(get_scheduler_db)):
    """获取所有计划任务"""
    try:
        tasks = []
        all_db_tasks = {task['task_id']: task for task in db.get_all_task_status()}
        
        # 构建任务依赖图（反向图）
        task_graph = {}
        for task_id, task_config in scheduler.tasks.items():
            task_graph[task_id] = []
        
        # 构建反向依赖关系
        for task_id, task_config in scheduler.tasks.items():
            for required_task in task_config.get('requires', []):
                if required_task in task_graph:
                    task_graph[required_task].append(task_id)
        
        # 使用拓扑排序获取任务顺序
        def topological_sort(graph):
            # 计算入度
            in_degree = {node: 0 for node in graph}
            for node in graph:
                for neighbor in graph[node]:
                    in_degree[neighbor] = in_degree.get(neighbor, 0) + 1
            
            # 找出入度为0的节点
            queue = [node for node in graph if in_degree[node] == 0]
            result = []
            
            while queue:
                node = queue.pop(0)
                result.append(node)
                
                # 更新相邻节点的入度
                for neighbor in graph[node]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
            
            return result
        
        # 获取排序后的任务ID列表
        sorted_task_ids = topological_sort(task_graph)
        
        # 按排序后的顺序构建任务列表
        for task_id in sorted_task_ids:
            task_config = scheduler.tasks[task_id]
            schedule_info = task_config.get('schedule', {})
            
            # 获取数据库中的任务状态
            db_task = all_db_tasks.get(task_id, {})
            
            # 处理标签
            tags = db_task.get('tags', [])
            if not isinstance(tags, list):
                tags = []
            
            # 计算成功率
            total_runs = db_task.get('total_runs', 0)
            success_rate = None
            if total_runs > 0:
                success_runs = db_task.get('success_runs', 0)
                success_rate = (success_runs / total_runs) * 100
            
            # 确保status字段不为None
            last_status = db_task.get('last_status')
            if last_status is None:
                last_status = "未执行"
            
            task_status = {
                "task_id": task_id,
                "name": task_config.get('name', task_id),
                "schedule_type": schedule_info.get('type', '未知'),
                "schedule_time": schedule_info.get('time') if schedule_info.get('type') == 'daily' else None,
                "last_run": db_task.get('last_run_time', "未记录"),
                "next_run": db_task.get('next_run_time', "未计算"),
                "status": last_status,
                "depends_on": task_config.get('requires', []),
                "enabled": bool(db_task.get('enabled', True)),
                "success_rate": success_rate,
                "avg_duration": db_task.get('avg_duration'),
                "total_runs": db_task.get('total_runs', 0),
                "success_runs": db_task.get('success_runs', 0),
                "fail_runs": db_task.get('fail_runs', 0),
                "last_error": db_task.get('last_error'),
                "tags": tags
            }
            tasks.append(task_status)
        
        return {
            "status": "success",
            "message": f"找到 {len(tasks)} 个计划任务",
            "tasks": tasks
        }
    except Exception as e:
        logger.error(f"获取任务列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")

@router.get("/tasks/{task_id}", summary="获取特定计划任务详情")
async def get_task_detail(task_id: str, 
                         scheduler: SchedulerManager = Depends(get_scheduler),
                         db: SchedulerDB = Depends(get_scheduler_db)):
    """获取特定计划任务的详细信息"""
    try:
        if task_id not in scheduler.tasks:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        
        task_config = scheduler.tasks[task_id]
        
        # 获取数据库中的任务状态
        db_task = db.get_task_status(task_id) or {}
        
        # 处理标签
        tags = db_task.get('tags', [])
        if not isinstance(tags, list):
            tags = []
        
        # 计算成功率
        total_runs = db_task.get('total_runs', 0)
        success_rate = None
        if total_runs > 0:
            success_runs = db_task.get('success_runs', 0)
            success_rate = (success_runs / total_runs) * 100
        
        # 确保last_status字段不为None
        last_status = db_task.get('last_status')
        if last_status is None:
            last_status = "未执行"
        
        # 合并配置和状态信息
        task_detail = {
            "task_id": task_id,
            **task_config,
            "last_run_time": db_task.get('last_run_time'),
            "next_run_time": db_task.get('next_run_time'),
            "last_status": last_status,
            "enabled": bool(db_task.get('enabled', True)),
            "success_rate": success_rate,
            "avg_duration": db_task.get('avg_duration'),
            "total_runs": total_runs,
            "success_runs": db_task.get('success_runs', 0),
            "fail_runs": db_task.get('fail_runs', 0),
            "last_error": db_task.get('last_error'),
            "last_modified": db_task.get('last_modified'),
            "priority": db_task.get('priority', 0),
            "tags": tags
        }
        
        return {
            "status": "success",
            "message": f"成功获取任务 {task_id} 详情",
            "task": task_detail
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务详情失败: {str(e)}")

@router.post("/tasks", summary="创建新的计划任务", response_model=TaskActionResponse)
async def create_task(task: TaskCreateRequest, 
                     scheduler: SchedulerManager = Depends(get_scheduler),
                     db: SchedulerDB = Depends(get_scheduler_db)):
    """创建新的计划任务"""
    try:
        # 获取当前配置
        config_path = get_config_path()
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 检查任务ID是否已存在
        if task.task_id in config['tasks']:
            raise HTTPException(status_code=400, detail=f"任务ID '{task.task_id}' 已存在")
        
        # 创建新任务配置
        new_task = {
            "name": task.name,
            "endpoint": task.endpoint,
            "method": task.method,
            "schedule": {
                "type": task.schedule.type,
            }
        }
        
        # 添加可选参数
        if task.params:
            new_task["params"] = task.params
        
        if task.requires:
            new_task["requires"] = task.requires
        
        # 根据调度类型添加特定配置
        if task.schedule.type == "daily" and task.schedule.time:
            new_task["schedule"]["time"] = task.schedule.time
        elif task.schedule.type == "once" and task.schedule.delay is not None:
            new_task["schedule"]["delay"] = task.schedule.delay
        
        # 更新配置
        config['tasks'][task.task_id] = new_task
        save_config(config)
        
        # 在数据库中创建任务状态记录
        db.update_task_status(task.task_id, {
            'name': task.name,
            'enabled': 1
        })
        
        # 重新加载调度器配置
        scheduler.load_config()
        
        return {
            "status": "success",
            "message": f"成功创建任务 {task.task_id}",
            "task_id": task.task_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")

@router.put("/tasks/{task_id}", summary="更新计划任务", response_model=TaskActionResponse)
async def update_task(task_id: str, task_update: TaskUpdateRequest, 
                     scheduler: SchedulerManager = Depends(get_scheduler)):
    """更新计划任务配置"""
    try:
        print(f"\n=== 开始处理任务更新请求 ===")
        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"任务ID: {task_id}")
        print(f"更新内容: {task_update}")
        
        # 获取当前配置
        config_path = get_config_path()
        print(f"配置文件路径: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 检查任务是否存在
        if task_id not in config['tasks']:
            error_msg = f"任务 {task_id} 不存在"
            print(f"错误: {error_msg}")
            raise HTTPException(status_code=404, detail=error_msg)
        
        # 获取当前任务配置
        current_task = config['tasks'][task_id]
        print(f"当前任务配置: {current_task}")
        
        # 更新任务配置
        if task_update.name is not None:
            print(f"更新任务名称: {task_update.name}")
            current_task['name'] = task_update.name
        
        if task_update.endpoint is not None:
            print(f"更新任务端点: {task_update.endpoint}")
            current_task['endpoint'] = task_update.endpoint
        
        if task_update.method is not None:
            print(f"更新请求方法: {task_update.method}")
            current_task['method'] = task_update.method
        
        if task_update.params is not None:
            print(f"更新请求参数: {task_update.params}")
            current_task['params'] = task_update.params
        
        if task_update.requires is not None:
            print(f"更新依赖任务: {task_update.requires}")
            current_task['requires'] = task_update.requires
        
        # 保存旧的调度配置用于比较
        old_schedule = current_task.get('schedule', {}).copy()
        schedule_updated = False
        
        if task_update.schedule is not None:
            print(f"更新调度配置: {task_update.schedule}")
            current_task['schedule']['type'] = task_update.schedule.type
            
            # 根据调度类型更新特定配置
            if task_update.schedule.type == "daily":
                if task_update.schedule.time:
                    print(f"更新每日执行时间: {task_update.schedule.time}")
                    current_task['schedule']['time'] = task_update.schedule.time
                    schedule_updated = True
                if 'delay' in current_task['schedule']:
                    del current_task['schedule']['delay']
            
            elif task_update.schedule.type == "once":
                if task_update.schedule.delay is not None:
                    print(f"更新延迟执行时间: {task_update.schedule.delay}秒")
                    current_task['schedule']['delay'] = task_update.schedule.delay
                if 'time' in current_task['schedule']:
                    del current_task['schedule']['time']
            
            elif task_update.schedule.type == "chain":
                if 'time' in current_task['schedule']:
                    del current_task['schedule']['time']
                if 'delay' in current_task['schedule']:
                    del current_task['schedule']['delay']
        
        # 保存配置
        print("保存更新后的配置...")
        save_config(config)
        
        # 如果调度时间发生变化，使用专门的方法更新
        if (schedule_updated and 
            task_update.schedule.type == "daily" and 
            task_update.schedule.time != old_schedule.get('time')):
            print(f"检测到调度时间变更: {old_schedule.get('time')} -> {task_update.schedule.time}")
            print("调用update_task_schedule_time更新调度时间...")
            success = scheduler.update_task_schedule_time(task_id, task_update.schedule.time)
            if not success:
                error_msg = "更新任务调度时间失败"
                print(f"错误: {error_msg}")
                raise HTTPException(status_code=500, detail=error_msg)
        else:
            # 重新加载调度器配置
            print("重新加载调度器配置...")
            scheduler.load_config()
        
        print("任务更新成功")
        
        return {
            "status": "success",
            "message": f"成功更新任务 {task_id}",
            "task_id": task_id
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"更新任务失败: {str(e)}"
        print(f"错误: {error_msg}")
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.delete("/tasks/{task_id}", summary="删除计划任务", response_model=TaskActionResponse)
async def delete_task(task_id: str, 
                     scheduler: SchedulerManager = Depends(get_scheduler),
                     db: SchedulerDB = Depends(get_scheduler_db)):
    """删除计划任务"""
    try:
        # 获取当前配置
        config_path = get_config_path()
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 检查任务是否存在
        if task_id not in config['tasks']:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        
        # 检查是否有其他任务依赖这个任务
        for other_id, other_task in config['tasks'].items():
            if other_id != task_id and 'requires' in other_task:
                if task_id in other_task['requires']:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"无法删除任务 {task_id}，因为任务 {other_id} 依赖它"
                    )
        
        # 删除任务
        del config['tasks'][task_id]
        
        # 保存配置
        save_config(config)
        
        # 重新加载调度器配置
        scheduler.load_config()
        
        return {
            "status": "success",
            "message": f"成功删除任务 {task_id}",
            "task_id": task_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除任务失败: {str(e)}")

@router.post("/tasks/{task_id}/execute", summary="立即执行计划任务", response_model=TaskActionResponse)
async def execute_task(task_id: str, scheduler: SchedulerManager = Depends(get_scheduler)):
    """立即执行指定的计划任务"""
    try:
        print(f"\n=== 开始执行任务 ===")
        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"任务ID: {task_id}")
        
        if task_id not in scheduler.tasks:
            error_msg = f"任务 {task_id} 不存在"
            print(f"错误: {error_msg}")
            raise HTTPException(status_code=404, detail=error_msg)
        
        print("创建后台任务...")
        # 创建后台任务并等待其启动
        task = asyncio.create_task(scheduler.execute_task_chain(task_id))
        
        # 等待一小段时间确保任务已经开始执行
        await asyncio.sleep(0.1)
        
        print(f"任务已开始在后台执行")
        
        return {
            "status": "success",
            "message": f"任务 {task_id} 开始执行",
            "task_id": task_id
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"执行任务失败: {str(e)}"
        print(f"错误: {error_msg}")
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.get("/history/task/{task_id}", summary="获取任务执行历史", response_model=TaskHistoryResponse)
async def get_task_history(task_id: str, limit: int = 10, 
                          db: SchedulerDB = Depends(get_scheduler_db),
                          scheduler: SchedulerManager = Depends(get_scheduler)):
    """获取特定任务的执行历史"""
    try:
        # 检查任务是否存在
        if task_id not in scheduler.tasks:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        
        # 获取任务执行历史
        history = db.get_task_execution_history(task_id, limit)
        
        return {
            "status": "success",
            "message": f"成功获取任务 {task_id} 执行历史",
            "history": history
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务执行历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务执行历史失败: {str(e)}")

@router.get("/history/recent", summary="获取最近执行的任务", response_model=TaskHistoryResponse)
async def get_recent_executions(limit: int = 20, db: SchedulerDB = Depends(get_scheduler_db)):
    """获取最近执行的任务历史"""
    try:
        history = db.get_recent_task_executions(limit)
        
        return {
            "status": "success",
            "message": f"成功获取最近 {len(history)} 条任务执行记录",
            "history": history
        }
    except Exception as e:
        logger.error(f"获取最近任务执行记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取最近任务执行记录失败: {str(e)}")

@router.get("/history/chains", summary="获取任务链执行历史")
async def get_chain_executions(limit: int = 10, db: SchedulerDB = Depends(get_scheduler_db)):
    """获取任务链执行历史"""
    try:
        chains = db.get_chain_execution_history(limit)
        
        return {
            "status": "success",
            "message": f"成功获取 {len(chains)} 条任务链执行记录",
            "chains": chains
        }
    except Exception as e:
        logger.error(f"获取任务链执行记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务链执行记录失败: {str(e)}")

@router.post("/tasks/{task_id}/enable", summary="启用或禁用任务")
async def enable_task(
    task_id: str, 
    request: TaskEnableRequest,
    scheduler: SchedulerManager = Depends(get_scheduler)
):
    """启用或禁用任务"""
    try:
        if task_id not in scheduler.tasks:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        
        # 使用新方法更新任务启用状态并重新加载调度
        success = scheduler.update_task_enabled_status(task_id, request.enabled)
        
        if not success:
            raise HTTPException(status_code=500, detail=f"更新任务 {task_id} 的启用状态失败")
        
        return {
            "status": "success",
            "message": f"成功{'启用' if request.enabled else '禁用'}任务 {task_id}",
            "task_id": task_id,
            "enabled": request.enabled
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新任务启用状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新任务启用状态失败: {str(e)}")

@router.post("/tasks/{task_id}/priority", summary="设置任务优先级")
async def set_task_priority(task_id: str, request: TaskPriorityRequest, 
                           scheduler: SchedulerManager = Depends(get_scheduler),
                           db: SchedulerDB = Depends(get_scheduler_db)):
    """设置任务的优先级"""
    try:
        # 检查任务是否存在
        if task_id not in scheduler.tasks:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        
        # 验证优先级范围
        if request.priority < 0 or request.priority > 10:
            raise HTTPException(status_code=400, detail="优先级必须在0-10之间")
        
        # 更新数据库中的优先级
        result = db.set_task_priority(task_id, request.priority)
        
        if not result:
            raise HTTPException(status_code=500, detail=f"设置任务优先级失败")
        
        return {
            "status": "success",
            "message": f"成功设置任务 {task_id} 的优先级为 {request.priority}",
            "task_id": task_id,
            "priority": request.priority
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置任务优先级失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"设置任务优先级失败: {str(e)}")

@router.post("/tasks/{task_id}/tags/add", summary="添加任务标签")
async def add_task_tags(task_id: str, request: TaskTagsRequest, 
                       scheduler: SchedulerManager = Depends(get_scheduler),
                       db: SchedulerDB = Depends(get_scheduler_db)):
    """为任务添加标签"""
    try:
        # 检查任务是否存在
        if task_id not in scheduler.tasks:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        
        # 更新数据库中的标签
        result = db.add_task_tags(task_id, request.tags)
        
        if not result:
            raise HTTPException(status_code=500, detail=f"添加任务标签失败")
        
        # 获取更新后的标签
        task_status = db.get_task_status(task_id)
        current_tags = task_status.get('tags', []) if task_status else []
        
        return {
            "status": "success",
            "message": f"成功为任务 {task_id} 添加标签",
            "task_id": task_id,
            "tags": current_tags
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加任务标签失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加任务标签失败: {str(e)}")

@router.post("/tasks/{task_id}/tags/remove", summary="移除任务标签")
async def remove_task_tags(task_id: str, request: TaskTagsRequest, 
                          scheduler: SchedulerManager = Depends(get_scheduler),
                          db: SchedulerDB = Depends(get_scheduler_db)):
    """移除任务标签"""
    try:
        # 检查任务是否存在
        if task_id not in scheduler.tasks:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        
        # 更新数据库中的标签
        result = db.remove_task_tags(task_id, request.tags)
        
        if not result:
            raise HTTPException(status_code=500, detail=f"移除任务标签失败")
        
        # 获取更新后的标签
        task_status = db.get_task_status(task_id)
        current_tags = task_status.get('tags', []) if task_status else []
        
        return {
            "status": "success",
            "message": f"成功从任务 {task_id} 移除标签",
            "task_id": task_id,
            "tags": current_tags
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移除任务标签失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"移除任务标签失败: {str(e)}") 