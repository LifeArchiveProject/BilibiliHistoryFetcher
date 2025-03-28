import json
import os
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, Query, HTTPException
from pydantic import BaseModel

from scripts.check_data_integrity import check_data_integrity
from scripts.sync_db_json import sync_data

router = APIRouter()

class SyncedDayInfo(BaseModel):
    date: str
    imported_count: int
    source: str
    titles: List[str]

class SyncDBJsonResponse(BaseModel):
    success: bool
    json_to_db_count: int
    db_to_json_count: int
    total_synced: int
    timestamp: str
    synced_days: Optional[List[SyncedDayInfo]] = None
    message: Optional[str] = None
    
class CheckDataIntegrityResponse(BaseModel):
    success: bool
    total_json_files: int
    total_json_records: int
    total_db_records: int
    missing_records_count: int
    extra_records_count: int
    difference: int
    result_file: str
    report_file: str
    timestamp: str

def run_sync_data(db_path: Optional[str] = None, json_root_path: Optional[str] = None):
    """在后台运行数据同步任务"""
    # 确保输出目录存在
    os.makedirs("output/check", exist_ok=True)
    
    # 调用同步函数
    result = sync_data(db_path, json_root_path)
    return result
    
def run_check_integrity(db_path: Optional[str] = None, json_root_path: Optional[str] = None):
    """在后台运行数据完整性检查任务"""
    # 确保输出目录存在
    os.makedirs("output/check", exist_ok=True)
    
    # 调用检查函数
    result = check_data_integrity(db_path, json_root_path)
    return result

@router.post("/sync", response_model=SyncDBJsonResponse, summary="同步数据库和JSON文件")
async def sync_db_json(
    background_tasks: BackgroundTasks,
    db_path: Optional[str] = Query(None, description="数据库文件路径，默认为 output/bilibili_history.db"),
    json_path: Optional[str] = Query(None, description="JSON文件根目录，默认为 output/history_by_date"),
    async_mode: bool = Query(False, description="是否异步执行（后台任务）")
):
    """
    同步数据库和JSON文件中的历史记录数据。
    
    - 将JSON文件中的新记录导入到数据库
    - 将数据库中的新记录导出到JSON文件
    
    返回:
    - 导入和导出的记录数量
    - 按日期同步的详细信息，包括每天同步的记录数和记录标题
    """
    if async_mode:
        # 异步模式下，将任务放入后台执行
        background_tasks.add_task(run_sync_data, db_path, json_path)
        return {
            "success": True,
            "json_to_db_count": 0,
            "db_to_json_count": 0,
            "total_synced": 0,
            "timestamp": datetime.now().isoformat(),
            "message": "同步任务已在后台启动，请稍后查看日志获取结果"
        }
    else:
        # 同步模式下，直接执行并返回结果
        result = run_sync_data(db_path, json_path)
        
        # 如果result不包含synced_days字段，添加一个空列表
        if "synced_days" not in result:
            result["synced_days"] = []
            
        # 添加timestamp如果不存在
        if "timestamp" not in result:
            result["timestamp"] = datetime.now().isoformat()
            
        return result

@router.post("/check", response_model=CheckDataIntegrityResponse, summary="检查数据完整性")
async def check_integrity(
    background_tasks: BackgroundTasks,
    db_path: Optional[str] = Query(None, description="数据库文件路径，默认为 output/bilibili_history.db"),
    json_path: Optional[str] = Query(None, description="JSON文件根目录，默认为 output/history_by_date"),
    async_mode: bool = Query(False, description="是否异步执行（后台任务）")
):
    """
    检查数据库和JSON文件之间的数据完整性。
    
    - 检查JSON文件是否都被正确导入到数据库
    - 检查数据库中的记录是否都存在于JSON文件中
    - 生成详细的差异报告
    
    返回检查结果和报告文件路径。
    """
    if async_mode:
        # 异步模式下，将任务放入后台执行
        background_tasks.add_task(run_check_integrity, db_path, json_path)
        return {
            "success": True,
            "total_json_files": 0,
            "total_json_records": 0,
            "total_db_records": 0,
            "missing_records_count": 0,
            "extra_records_count": 0,
            "difference": 0,
            "result_file": "output/check/data_integrity_results.json",
            "report_file": "output/check/data_integrity_report.md",
            "timestamp": datetime.now().isoformat(),
            "message": "数据完整性检查任务已在后台启动，请稍后查看报告文件获取结果"
        }
    else:
        # 同步模式下，直接执行并返回结果
        result = run_check_integrity(db_path, json_path)
        return {
            **result,
            "timestamp": datetime.now().isoformat()
        }

@router.get("/report", summary="获取最新的数据完整性报告")
async def get_report():
    """
    获取最新的数据完整性检查报告的内容。
    
    返回报告的内容和最后修改时间。
    """
    report_file = "output/check/data_integrity_report.md"
    
    if not os.path.exists(report_file):
        raise HTTPException(status_code=404, detail="报告文件不存在，请先执行数据完整性检查")
    
    try:
        with open(report_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 获取文件修改时间
        mod_time = os.path.getmtime(report_file)
        mod_time_str = datetime.fromtimestamp(mod_time).isoformat()
        
        return {
            "content": content,
            "modified_time": mod_time_str,
            "file_path": report_file
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取报告文件时出错: {str(e)}")

@router.get("/sync/result", summary="获取最新的同步结果")
async def get_sync_result():
    """
    获取最新的数据同步结果。
    
    返回同步的详细信息，包括每天同步的记录数量和记录标题。
    """
    result_file = "output/check/sync_result.json"
    
    if not os.path.exists(result_file):
        raise HTTPException(status_code=404, detail="同步结果文件不存在，请先执行数据同步")
    
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            result = json.load(f)
        
        # 获取文件修改时间
        mod_time = os.path.getmtime(result_file)
        mod_time_str = datetime.fromtimestamp(mod_time).isoformat()
        
        # 添加文件修改时间
        result["file_modified_time"] = mod_time_str
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取同步结果文件时出错: {str(e)}") 