import json
import sqlite3
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scripts.utils import load_config, get_output_path

router = APIRouter()
config = load_config()

class DeleteHistoryItem(BaseModel):
    bvid: str
    view_at: int  # 观看时间戳

def get_db():
    """获取数据库连接"""
    db_path = get_output_path(config['db_file'])
    return sqlite3.connect(db_path)

def update_last_import_time(timestamp: int):
    """更新最后导入时间记录"""
    record = {
        "last_import_file": "",
        "last_import_time": timestamp,
        "last_import_date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    }
    
    record_file = get_output_path('last_import.json')
    with open(record_file, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=4)

@router.delete("/batch-delete", summary="批量删除历史记录")
async def batch_delete_history(items: List[DeleteHistoryItem]):
    """批量删除历史记录
    
    Args:
        items: 要删除的视频记录列表，每个记录包含BV号和观看时间戳
    
    Returns:
        dict: 删除操作的结果
    """
    if not items:
        raise HTTPException(status_code=400, detail="请提供要删除的视频记录列表")
        
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 获取当前所有年份的表
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name LIKE 'bilibili_history_%'
        """)
        tables = [table[0] for table in cursor.fetchall()]
        
        total_deleted = 0
        deleted_details = []
        min_timestamp = float('inf')  # 记录最早的删除时间
        
        for item in items:
            # 从时间戳获取年份
            year = datetime.fromtimestamp(item.view_at).year
            table_name = f"bilibili_history_{year}"
            
            if table_name in tables:
                # 在对应年份的表中删除指定的记录
                query = f"""
                    DELETE FROM {table_name} 
                    WHERE bvid = ? AND view_at = ?
                """
                cursor.execute(query, (item.bvid, item.view_at))
                if cursor.rowcount > 0:
                    total_deleted += cursor.rowcount
                    deleted_details.append({
                        "bvid": item.bvid,
                        "view_at": item.view_at,
                        "view_time": datetime.fromtimestamp(item.view_at).strftime("%Y-%m-%d %H:%M:%S")
                    })
                    # 更新最早的删除时间
                    min_timestamp = min(min_timestamp, item.view_at)
            
        conn.commit()
        
        # 如果有记录被删除，更新last_import.json
        if total_deleted > 0 and min_timestamp != float('inf'):
            update_last_import_time(min_timestamp - 1)  # 减1秒以确保能获取到被删除时间点的记录
        
        return {
            "status": "success",
            "message": f"成功删除 {total_deleted} 条历史记录",
            "data": {
                "deleted_count": total_deleted,
                "deleted_records": deleted_details
            }
        }
        
    except sqlite3.Error as e:
        raise HTTPException(
            status_code=500,
            detail=f"数据库操作失败: {str(e)}"
        )
    finally:
        if 'conn' in locals() and conn:
            conn.close() 