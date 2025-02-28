from typing import Optional
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from scripts.bilibili_history import fetch_history, find_latest_local_history, fetch_and_compare_history, save_history, \
    load_cookie
from scripts.import_sqlite import import_all_history_files
from scripts.utils import load_config

# 配置日志记录
logger = logging.getLogger(__name__)

router = APIRouter()

config = load_config()

# 定义请求体模型
class FetchHistoryRequest(BaseModel):
    sessdata: Optional[str] = Field(None, description="用户的 SESSDATA")


# 定义响应模型
class ResponseModel(BaseModel):
    status: str
    message: str
    data: Optional[list] = None


def get_headers():
    """获取请求头"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Cookie': f'SESSDATA={config["SESSDATA"]}'
    }
    return headers


@router.get("/bili-history", summary="获取B站历史记录")
async def get_bili_history(output_dir: Optional[str] = "history_by_date"):
    """获取B站历史记录"""
    try:
        result = await fetch_history(output_dir)
        return {
            "status": "success",
            "message": "历史记录获取成功",
            "data": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取历史记录失败: {str(e)}"
        }


@router.get("/bili-history-realtime", summary="实时获取B站历史记录", response_model=ResponseModel)
async def get_bili_history_realtime():
    """实时获取B站历史记录"""
    try:
        # 获取最新的本地历史记录时间戳
        latest_history = find_latest_local_history()
        if not latest_history:
            return {"status": "error", "message": "未找到本地历史记录"}

        # 获取cookie
        cookie = load_cookie()
        if not cookie:
            return {"status": "error", "message": "未找到有效的cookie"}

        # 获取新的历史记录
        new_records = fetch_and_compare_history(cookie, latest_history)
        if not new_records:
            return {"status": "success", "message": "没有新的历史记录"}

        # 保存新记录
        save_history(new_records)
        logger.info("成功保存新记录到本地文件")

        # 更新SQLite数据库
        logger.info("=== 开始更新SQLite数据库 ===")
        result = import_all_history_files()
        
        if result["status"] == "success":
            message = f"实时更新成功，获取到 {len(new_records)} 条新记录，成功导入 {result['inserted_count']} 条记录到SQLite数据库"
            return {"status": "success", "message": message, "data": new_records}
        else:
            return {"status": "error", "message": f"更新SQLite数据库失败: {result['message']}"}

    except Exception as e:
        error_msg = f"实时更新失败: {str(e)}"
        logger.error(error_msg)
        return {"status": "error", "message": error_msg}
