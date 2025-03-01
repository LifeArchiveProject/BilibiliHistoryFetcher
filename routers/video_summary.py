import json
import os
import sqlite3
import time
from typing import Optional, List, Dict, Any, Union

import requests
import yaml
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from scripts.utils import get_output_path, load_config
from scripts.wbi_sign import get_wbi_sign

router = APIRouter()
config = load_config()

# 获取是否缓存空摘要的配置，默认为True
CACHE_EMPTY_SUMMARY = config.get('CACHE_EMPTY_SUMMARY', True)

# 定义配置模型
class SummaryConfig(BaseModel):
    cache_empty_summary: bool = True

# 数据模型定义
class OutlinePoint(BaseModel):
    timestamp: int
    content: str

class OutlinePart(BaseModel):
    title: str
    part_outline: List[OutlinePoint]
    timestamp: int

class VideoSummaryResponse(BaseModel):
    bvid: str
    cid: int
    up_mid: int
    stid: Optional[str] = None
    summary: Optional[str] = None
    outline: Optional[List[OutlinePart]] = None
    result_type: int = 0
    status_message: str = ""  # 用于解释result_type的含义
    has_summary: bool = False  # 表示是否存在摘要内容
    fetch_time: int
    update_time: Optional[int] = None
    from_cache: bool = False

class SummaryRequest(BaseModel):
    bvid: str
    cid: int
    up_mid: int

def get_db():
    """获取数据库连接"""
    db_path = get_output_path(config['db_file'])
    
    # 检查数据库文件是否存在
    db_exists = os.path.exists(db_path)
    
    try:
        # 连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 设置数据库兼容性参数
        pragmas = [
            ('legacy_file_format', 1),
            ('journal_mode', 'DELETE'),
            ('synchronous', 'NORMAL'),
            ('user_version', 317)  # 使用固定的用户版本号
        ]
        
        for pragma, value in pragmas:
            cursor.execute(f'PRAGMA {pragma}={value}')
        conn.commit()
        
        # 确保视频摘要表存在
        from config.sql_statements_sqlite import CREATE_TABLE_VIDEO_SUMMARY, CREATE_INDEXES_VIDEO_SUMMARY
        cursor.execute(CREATE_TABLE_VIDEO_SUMMARY)
        
        # 创建索引
        for index_sql in CREATE_INDEXES_VIDEO_SUMMARY:
            cursor.execute(index_sql)
            
        conn.commit()
        
        return conn
        
    except sqlite3.Error as e:
        print(f"数据库连接错误: {str(e)}")
        if 'conn' in locals() and conn:
            conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"数据库连接失败: {str(e)}"
        )

def get_video_summary_from_db(bvid: str, cid: int) -> Optional[Dict[str, Any]]:
    """从数据库获取视频摘要"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT bvid, cid, up_mid, stid, summary, outline, result_type, fetch_time, update_time
            FROM video_summary
            WHERE bvid = ? AND cid = ?
        """, (bvid, cid))
        
        result = cursor.fetchone()
        if result:
            result_type = result[6]
            status_message = get_status_message(result_type)
            
            # 判断是否有有效摘要 (result_type为1或2表示有摘要)
            has_summary = result_type > 0
            
            return {
                "bvid": result[0],
                "cid": result[1],
                "up_mid": result[2],
                "stid": result[3],
                "summary": result[4],
                "outline": json.loads(result[5]) if result[5] else None,
                "result_type": result_type,
                "status_message": status_message,
                "has_summary": has_summary,
                "fetch_time": result[7],
                "update_time": result[8],
                "from_cache": True
            }
        return None
    except sqlite3.Error as e:
        print(f"查询数据库时发生错误: {e}")
        return None
    finally:
        if conn:
            conn.close()

# 添加一个辅助函数获取状态消息
def get_status_message(result_type: int) -> str:
    """
    根据result_type获取对应的状态消息
    
    官方状态码含义：
    - 0: 没有摘要
    - 1: 仅存在摘要总结
    - 2: 存在摘要以及提纲
    """
    if result_type == 0:
        return "该视频没有摘要"
    elif result_type == 1:
        return "该视频仅有摘要总结"
    elif result_type == 2:
        return "该视频有摘要总结和提纲"
    elif result_type == -1:
        return "该视频不支持AI摘要（可能含有敏感内容或其他因素导致）"
    else:
        return f"未知状态码: {result_type}"

def save_video_summary_to_db(
    bvid: str, 
    cid: int, 
    up_mid: int, 
    stid: str, 
    summary: str, 
    outline: Union[List[Dict], None], 
    result_type: int
) -> bool:
    """保存视频摘要到数据库"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        current_time = int(time.time())
        
        # 检查是否已存在
        cursor.execute(
            "SELECT id FROM video_summary WHERE bvid = ? AND cid = ?", 
            (bvid, cid)
        )
        
        existing = cursor.fetchone()
        
        if existing:
            # 更新现有记录
            from config.sql_statements_sqlite import UPDATE_VIDEO_SUMMARY
            cursor.execute(
                UPDATE_VIDEO_SUMMARY,
                (
                    stid, 
                    summary, 
                    json.dumps(outline, ensure_ascii=False) if outline else None, 
                    result_type,
                    current_time,
                    bvid,
                    cid
                )
            )
        else:
            # 插入新记录
            from config.sql_statements_sqlite import INSERT_VIDEO_SUMMARY
            # 生成ID (使用时间戳+随机数)
            id = int(f"{current_time}{hash(bvid + str(cid)) % 10000:04d}")
            
            cursor.execute(
                INSERT_VIDEO_SUMMARY,
                (
                    id,
                    bvid,
                    cid,
                    up_mid,
                    stid,
                    summary,
                    json.dumps(outline, ensure_ascii=False) if outline else None,
                    result_type,
                    current_time,
                    current_time
                )
            )
            
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"保存到数据库时发生错误: {e}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

async def fetch_video_summary_from_api(bvid: str, cid: int, up_mid: int) -> Dict[str, Any]:
    """从B站API获取视频摘要"""
    try:
        # 获取wbi签名
        wbi_params = {
            'bvid': bvid,
            'cid': cid,
            'up_mid': up_mid
        }
        
        signed_params = get_wbi_sign(wbi_params)
        
        # 构建请求URL
        url = "https://api.bilibili.com/x/web-interface/view/conclusion/get"
        
        # 从配置中读取SESSDATA
        sessdata = config.get('SESSDATA', '')
        
        # 添加必要的HTTP头信息
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.bilibili.com/"
        }
        
        # 如果有SESSDATA，添加到Cookie
        if sessdata:
            headers["Cookie"] = f"SESSDATA={sessdata}"
        
        # 发送请求
        response = requests.get(url, params=signed_params, headers=headers)
        data = response.json()
        
        # 记录原始返回数据用于调试
        print(f"API返回数据: {json.dumps(data, ensure_ascii=False)}")
        
        # 根据返回的code进行处理
        if data['code'] == 0:
            # API请求成功
            return data['data']
        elif data['code'] == -1:
            # 不支持AI摘要或请求异常
            return {
                'model_result': {
                    'result_type': -1,  # 使用-1表示不支持AI摘要
                    'summary': '该视频不支持AI摘要（可能含有敏感内容或其他因素导致）',
                    'outline': None
                },
                'stid': ''
            }
        else:
            # 其他错误情况
            raise HTTPException(
                status_code=400,
                detail=f"获取视频摘要失败: {data['message']} (code: {data['code']})"
            )
            
    except Exception as e:
        # 记录详细错误信息
        print(f"获取视频摘要时发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取视频摘要时发生错误: {str(e)}"
        )

@router.get("/get_summary", summary="获取视频摘要", response_model=VideoSummaryResponse)
async def get_video_summary(bvid: str, cid: int, up_mid: int, force_refresh: Optional[bool] = False):
    """
    获取视频摘要
    
    - **bvid**: 视频的BVID
    - **cid**: 视频的CID
    - **up_mid**: UP主的MID
    - **force_refresh**: 是否强制刷新（不使用缓存）
    """
    # 处理force_refresh参数，确保是正确的布尔值
    if isinstance(force_refresh, str):
        force_refresh = force_refresh.lower() == 'true'
    
    try:
        # 首先尝试从数据库获取
        if not force_refresh:
            db_result = get_video_summary_from_db(bvid, cid)
            if db_result:
                return db_result
        
        # 从API获取
        api_result = await fetch_video_summary_from_api(bvid, cid, up_mid)
        
        # 解析API结果
        result_type = api_result.get('model_result', {}).get('result_type', 0)
        summary = api_result.get('model_result', {}).get('summary', '')
        outline_data = api_result.get('model_result', {}).get('outline', None)
        stid = api_result.get('stid', '')
        
        # 获取状态消息
        status_message = get_status_message(result_type)
        
        # 判断是否有有效摘要 (result_type为1或2表示有摘要)
        has_summary = result_type > 0
        
        # 根据配置决定是否保存到数据库
        # 如果CACHE_EMPTY_SUMMARY为True，则保存所有结果
        # 如果CACHE_EMPTY_SUMMARY为False，则只保存有摘要的结果
        should_save = has_summary or CACHE_EMPTY_SUMMARY
        
        if should_save:
            # 保存到数据库
            save_success = save_video_summary_to_db(
                bvid=bvid,
                cid=cid,
                up_mid=up_mid,
                stid=stid,
                summary=summary,
                outline=outline_data,
                result_type=result_type
            )
            if not save_success:
                print(f"警告: 保存视频摘要到数据库失败: {bvid}, {cid}")
        else:
            print(f"跳过保存无摘要数据到数据库: {bvid}, {cid}, result_type={result_type}")
        
        # 返回结果
        return {
            "bvid": bvid,
            "cid": cid,
            "up_mid": up_mid,
            "stid": stid,
            "summary": summary,
            "outline": outline_data,
            "result_type": result_type,
            "status_message": status_message,
            "has_summary": has_summary,
            "fetch_time": int(time.time()),
            "update_time": int(time.time()),
            "from_cache": False
        }
    
    except Exception as e:
        # 捕获所有可能的异常，确保API有良好的错误处理
        print(f"获取视频摘要出错: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取视频摘要失败: {str(e)}"
        )

# 配置操作函数
def save_config(new_config: Dict[str, Any]) -> bool:
    """保存配置到配置文件"""
    try:
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.yaml')
        
        # 读取当前配置
        with open(config_path, 'r', encoding='utf-8') as f:
            current_config = yaml.safe_load(f)
        
        # 更新配置
        current_config.update(new_config)
        
        # 写入配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(current_config, f, allow_unicode=True)
        
        # 更新全局变量
        global config, CACHE_EMPTY_SUMMARY
        config = current_config
        CACHE_EMPTY_SUMMARY = config.get('CACHE_EMPTY_SUMMARY', True)
        
        return True
    except Exception as e:
        print(f"保存配置失败: {str(e)}")
        return False

# 添加配置接口
@router.get("/config", summary="获取摘要相关配置", response_model=SummaryConfig)
async def get_summary_config():
    """获取摘要相关配置"""
    return {
        "cache_empty_summary": CACHE_EMPTY_SUMMARY
    }

@router.post("/config", summary="更新摘要相关配置", response_model=SummaryConfig)
async def update_summary_config(config_data: SummaryConfig = Body(...)):
    """
    更新摘要相关配置
    
    - **cache_empty_summary**: 是否缓存空摘要结果
    """
    # 准备要更新的配置项
    new_config = {
        "CACHE_EMPTY_SUMMARY": config_data.cache_empty_summary
    }
    
    # 保存配置
    success = save_config(new_config)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="更新配置失败"
        )
    
    return {
        "cache_empty_summary": CACHE_EMPTY_SUMMARY
    } 