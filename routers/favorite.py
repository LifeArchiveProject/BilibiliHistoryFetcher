import os
import sqlite3
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

import requests
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from scripts.utils import load_config

router = APIRouter()
config = load_config()

# 数据库路径 - 存储在output/database目录下
DB_PATH = os.path.join("output", "database", "bilibili_favorites.db")

# 确保目录存在
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 数据库表创建语句
CREATE_FAVORITES_FOLDER_TABLE = """
CREATE TABLE IF NOT EXISTS favorites_folder (
    id INTEGER PRIMARY KEY,
    media_id INTEGER NOT NULL,
    fid INTEGER NOT NULL,
    mid INTEGER NOT NULL,
    title TEXT NOT NULL,
    cover TEXT,
    attr INTEGER,
    intro TEXT,
    ctime INTEGER,
    mtime INTEGER,
    state INTEGER,
    media_count INTEGER,
    fav_state INTEGER,
    like_state INTEGER,
    fetch_time INTEGER,
    UNIQUE(media_id)
);
"""

CREATE_FAVORITES_CREATOR_TABLE = """
CREATE TABLE IF NOT EXISTS favorites_creator (
    mid INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    face TEXT,
    followed INTEGER,
    vip_type INTEGER,
    vip_status INTEGER,
    fetch_time INTEGER
);
"""

CREATE_FAVORITES_CONTENT_TABLE = """
CREATE TABLE IF NOT EXISTS favorites_content (
    id INTEGER PRIMARY KEY,
    media_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    type INTEGER NOT NULL,
    title TEXT NOT NULL,
    cover TEXT,
    bvid TEXT,
    intro TEXT,
    page INTEGER,
    duration INTEGER,
    upper_mid INTEGER,
    attr INTEGER,
    ctime INTEGER,
    pubtime INTEGER,
    fav_time INTEGER,
    link TEXT,
    fetch_time INTEGER,
    creator_name TEXT,
    creator_face TEXT,
    bv_id TEXT,
    collect INTEGER,
    play INTEGER,
    danmaku INTEGER,
    vt INTEGER,
    play_switch INTEGER,
    reply INTEGER,
    view_text_1 TEXT,
    first_cid INTEGER,
    media_list_link TEXT,
    UNIQUE(media_id, content_id)
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_favorites_folder_mid ON favorites_folder (mid);",
    "CREATE INDEX IF NOT EXISTS idx_favorites_folder_mtime ON favorites_folder (mtime);",
    "CREATE INDEX IF NOT EXISTS idx_favorites_content_media_id ON favorites_content (media_id);",
    "CREATE INDEX IF NOT EXISTS idx_favorites_content_upper_mid ON favorites_content (upper_mid);",
    "CREATE INDEX IF NOT EXISTS idx_favorites_content_fav_time ON favorites_content (fav_time);"
]

# 数据模型
class FolderMetadata(BaseModel):
    id: int
    fid: int
    mid: int
    attr: Optional[int] = None
    title: str
    cover: Optional[str] = None
    upper: Dict[str, Any]
    cover_type: Optional[int] = None
    cnt_info: Dict[str, int]
    type: Optional[int] = None
    intro: Optional[str] = None
    ctime: int
    mtime: int
    state: Optional[int] = None
    fav_state: Optional[int] = None
    like_state: Optional[int] = None
    media_count: int

class FavoriteContent(BaseModel):
    id: int
    type: int
    title: str
    cover: Optional[str] = None
    bvid: Optional[str] = None
    bv_id: Optional[str] = None
    intro: Optional[str] = None
    page: Optional[int] = None
    duration: Optional[int] = None
    upper: Dict[str, Any]
    attr: Optional[int] = None
    cnt_info: Dict[str, int]
    link: Optional[str] = None
    ctime: Optional[int] = None
    pubtime: Optional[int] = None
    fav_time: Optional[int] = None
    season: Optional[Any] = None

def get_headers(sessdata=None):
    """获取请求头"""
    # 如果未提供SESSDATA，尝试从配置中获取
    if sessdata is None:
        current_config = load_config()
        sessdata = current_config.get("SESSDATA", "")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }
    
    # 构建完整Cookie字符串
    cookies = []
    if sessdata:
        cookies.append(f"SESSDATA={sessdata}")
    
    # 如果配置中有bili_jct，也添加到Cookie中
    current_config = load_config()
    bili_jct = current_config.get("bili_jct", "")
    if bili_jct:
        cookies.append(f"bili_jct={bili_jct}")
    
    # 如果配置中有DedeUserID，也添加到Cookie中
    dede_user_id = current_config.get("DedeUserID", "")
    if dede_user_id:
        cookies.append(f"DedeUserID={dede_user_id}")
    
    # 如果配置中有DedeUserID__ckMd5，也添加到Cookie中
    dede_user_id_ckmd5 = current_config.get("DedeUserID__ckMd5", "")
    if dede_user_id_ckmd5:
        cookies.append(f"DedeUserID__ckMd5={dede_user_id_ckmd5}")
    
    # 将所有Cookie合并为一个字符串
    if cookies:
        headers["Cookie"] = "; ".join(cookies)
    
    return headers

async def get_current_user_info(sessdata=None):
    """获取当前登录用户信息"""
    try:
        headers = get_headers(sessdata)
        
        # 使用B站官方API获取用户信息
        response = requests.get("https://api.bilibili.com/x/web-interface/nav", headers=headers)
        data = response.json()
        
        if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
            user_data = data.get("data", {})
            return {
                "uid": user_data.get("mid"),
                "uname": user_data.get("uname"),
                "level": user_data.get("level_info", {}).get("current_level")
            }
        return None
    except Exception as e:
        print(f"获取用户信息时出错: {str(e)}")
        return None

def get_db_connection():
    """获取数据库连接"""
    # 确保数据库目录存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 创建表和索引
    cursor = conn.cursor()
    cursor.execute(CREATE_FAVORITES_FOLDER_TABLE)
    cursor.execute(CREATE_FAVORITES_CREATOR_TABLE)
    cursor.execute(CREATE_FAVORITES_CONTENT_TABLE)
    
    for index_sql in CREATE_INDEXES:
        cursor.execute(index_sql)
    
    conn.commit()
    return conn

def save_json_response(data, prefix, identifier):
    """不再保存JSON响应到文件，直接返回数据"""
    # 保留此函数是为了保持代码兼容性，但不再执行实际的保存操作
    return None

@router.get("/folder/created/list-all", summary="获取指定用户创建的所有收藏夹信息")
async def get_created_folders(
    up_mid: Optional[int] = Query(None, description="目标用户mid，不提供则使用当前登录用户"),
    type: int = Query(0, description="目标内容属性，0=全部，2=视频稿件"),
    rid: Optional[int] = Query(None, description="目标内容id，视频稿件为avid"),
    sessdata: Optional[str] = Query(None, description="用户的 SESSDATA")
):
    """
    获取指定用户创建的所有收藏夹信息
    
    需要用户登录才能查看私密收藏夹
    """
    try:
        # 如果未提供up_mid，获取当前登录用户的UID
        if up_mid is None:
            user_info = await get_current_user_info(sessdata)
            if user_info is None:
                return {
                    "status": "error",
                    "message": "未提供up_mid且未登录，无法获取收藏夹信息"
                }
            up_mid = user_info.get("uid")
            print(f"使用当前登录用户UID: {up_mid}")
                
        url = "https://api.bilibili.com/x/v3/fav/folder/created/list-all"
        params = {"up_mid": up_mid, "type": type}
        if rid is not None:
            params["rid"] = rid
            
        headers = get_headers(sessdata)
        
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        
        # 检查API响应
        if data.get('code') != 0:
            return {
                "status": "error",
                "message": data.get('message', '未知错误'),
                "code": data.get('code')
            }
        
        folders_data = data.get('data', {})
        
        # 保存到数据库
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            timestamp = int(time.time())
            
            # 遍历所有收藏夹
            for folder in folders_data.get('list', []):
                # 保存创建者信息
                upper = folder.get('upper', {})
                if upper and 'mid' in upper:
                    cursor.execute("""
                    INSERT OR REPLACE INTO favorites_creator 
                    (mid, name, face, followed, vip_type, vip_status, fetch_time) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        upper.get('mid'),
                        upper.get('name', ''),
                        upper.get('face', ''),
                        1 if upper.get('followed') else 0,
                        upper.get('vip_type', 0),
                        upper.get('vip_statue', 0),  # API返回的字段名可能有误
                        timestamp
                    ))
                
                # 保存收藏夹信息
                cursor.execute("""
                INSERT OR REPLACE INTO favorites_folder 
                (media_id, fid, mid, title, cover, attr, intro, ctime, mtime, state, media_count, fav_state, like_state, fetch_time) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    folder.get('id'),
                    folder.get('fid'),
                    folder.get('mid'),
                    folder.get('title', ''),
                    folder.get('cover', ''),
                    folder.get('attr'),
                    folder.get('intro', ''),
                    folder.get('ctime'),
                    folder.get('mtime'),
                    folder.get('state'),
                    folder.get('media_count', 0),
                    folder.get('fav_state', 0),
                    folder.get('like_state', 0),
                    timestamp
                ))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"保存用户收藏夹信息到数据库时出错: {str(e)}")
        finally:
            conn.close()
        
        return {
            "status": "success",
            "message": "获取用户创建的收藏夹列表成功",
            "data": folders_data
        }
        
    except Exception as e:
        print(f"获取用户创建的收藏夹列表时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"获取用户创建的收藏夹列表失败: {str(e)}"
        }

@router.get("/folder/collected/list", summary="查询用户收藏的视频收藏夹")
async def get_collected_folders(
    up_mid: Optional[int] = Query(None, description="目标用户mid，不提供则使用当前登录用户"),
    pn: int = Query(1, description="页码"),
    ps: int = Query(40, description="每页项数"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    sessdata: Optional[str] = Query(None, description="用户的 SESSDATA")
):
    """
    查询用户收藏的视频收藏夹
    """
    try:
        # 如果未提供up_mid，获取当前登录用户的UID
        if up_mid is None:
            user_info = await get_current_user_info(sessdata)
            if user_info is None:
                return {
                    "status": "error",
                    "message": "未提供up_mid且未登录，无法获取收藏夹信息"
                }
            up_mid = user_info.get("uid")
            print(f"使用当前登录用户UID: {up_mid}")
                
        url = "https://api.bilibili.com/x/v3/fav/folder/collected/list"
        params = {"up_mid": up_mid, "pn": pn, "ps": ps}
        if keyword:
            params["keyword"] = keyword
            
        headers = get_headers(sessdata)
        
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        
        # 检查API响应
        if data.get('code') != 0:
            return {
                "status": "error",
                "message": data.get('message', '未知错误'),
                "code": data.get('code')
            }
        
        collected_data = data.get('data', {})
        
        # 保存到数据库
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            timestamp = int(time.time())
            
            # 遍历所有收藏夹
            for folder in collected_data.get('list', []):
                # 保存创建者信息
                upper = folder.get('upper', {})
                if upper and 'mid' in upper:
                    cursor.execute("""
                    INSERT OR REPLACE INTO favorites_creator 
                    (mid, name, face, followed, vip_type, vip_status, fetch_time) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        upper.get('mid'),
                        upper.get('name', ''),
                        upper.get('face', ''),
                        1 if upper.get('followed') else 0,
                        upper.get('vip_type', 0),
                        upper.get('vip_statue', 0),  # API返回的字段名可能有误
                        timestamp
                    ))
                
                # 保存收藏夹信息
                cursor.execute("""
                INSERT OR REPLACE INTO favorites_folder 
                (media_id, fid, mid, title, cover, attr, intro, ctime, mtime, state, media_count, fav_state, like_state, fetch_time) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    folder.get('id'),
                    folder.get('fid'),
                    folder.get('mid'),
                    folder.get('title', ''),
                    folder.get('cover', ''),
                    folder.get('attr'),
                    folder.get('intro', ''),
                    folder.get('ctime'),
                    folder.get('mtime'),
                    folder.get('state'),
                    folder.get('media_count', 0),
                    folder.get('fav_state', 0),
                    folder.get('like_state', 0),
                    timestamp
                ))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"保存用户收藏的收藏夹信息到数据库时出错: {str(e)}")
        finally:
            conn.close()
        
        return {
            "status": "success",
            "message": "获取用户收藏的收藏夹列表成功",
            "data": collected_data
        }
        
    except Exception as e:
        print(f"获取用户收藏的收藏夹列表时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"获取用户收藏的收藏夹列表失败: {str(e)}"
        }

@router.get("/resource/infos", summary="批量获取指定收藏id的内容")
async def get_resource_infos(
    resources: str = Query(..., description="资源列表，格式为id:type,id:type，如583785685:2,15664:12"),
    sessdata: Optional[str] = Query(None, description="用户的 SESSDATA")
):
    """
    批量获取指定收藏id的内容
    
    type: 2=视频稿件，12=音频，...
    """
    try:
        url = "https://api.bilibili.com/x/v3/fav/resource/infos"
        params = {"resources": resources}
        headers = get_headers(sessdata)
        
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        
        # 检查API响应
        if data.get('code') != 0:
            return {
                "status": "error",
                "message": data.get('message', '未知错误'),
                "code": data.get('code')
            }
        
        resources_data = data.get('data', [])
        
        # 保存到数据库
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            timestamp = int(time.time())
            
            # 为每个资源创建一个虚拟的media_id，因为这个API不返回对应的media_id
            # 使用当前时间戳作为标识
            virtual_media_id = timestamp
            
            # 遍历所有资源
            for resource in resources_data:
                # 保存UP主信息
                upper = resource.get('upper', {})
                if upper and 'mid' in upper:
                    cursor.execute("""
                    INSERT OR REPLACE INTO favorites_creator 
                    (mid, name, face, followed, vip_type, vip_status, fetch_time) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        upper.get('mid'),
                        upper.get('name', ''),
                        upper.get('face', ''),
                        0,  # API不返回是否关注
                        0,  # API不返回会员类型
                        0,  # API不返回会员状态
                        timestamp
                    ))
                
                # 保存资源信息
                cursor.execute("""
                INSERT OR REPLACE INTO favorites_content 
                (media_id, content_id, type, title, cover, bvid, intro, page, duration, upper_mid, attr, ctime, pubtime, fav_time, link, fetch_time,
                creator_name, creator_face, bv_id, collect, play, danmaku, vt, play_switch, reply, view_text_1, first_cid, media_list_link) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    virtual_media_id,
                    resource.get('id'),
                    resource.get('type'),
                    resource.get('title', ''),
                    resource.get('cover', ''),
                    resource.get('bvid', ''),
                    resource.get('intro', ''),
                    resource.get('page', 0),
                    resource.get('duration', 0),
                    upper.get('mid') if upper else 0,
                    resource.get('attr', 0),
                    resource.get('ctime', 0),
                    resource.get('pubtime', 0),
                    resource.get('fav_time', 0),
                    resource.get('link', ''),
                    timestamp,
                    upper.get('name', '') if upper else '',
                    upper.get('face', '') if upper else '',
                    resource.get('bv_id', ''),
                    resource.get('cnt_info', {}).get('collect', 0),
                    resource.get('cnt_info', {}).get('play', 0),
                    resource.get('cnt_info', {}).get('danmaku', 0),
                    resource.get('cnt_info', {}).get('vt', 0),
                    resource.get('cnt_info', {}).get('play_switch', 0),
                    resource.get('cnt_info', {}).get('reply', 0),
                    resource.get('cnt_info', {}).get('view_text_1', ''),
                    resource.get('ugc', {}).get('first_cid', 0) if resource.get('ugc') else 0,
                    resource.get('media_list_link', '')
                ))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"保存资源信息到数据库时出错: {str(e)}")
        finally:
            conn.close()
        
        return {
            "status": "success",
            "message": "获取资源信息成功",
            "data": resources_data
        }
        
    except Exception as e:
        print(f"获取资源信息时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"获取资源信息失败: {str(e)}"
        }

@router.get("/folder/resource/list", summary="获取收藏夹内容列表")
async def get_folder_resource_list(
    media_id: int = Query(..., description="目标收藏夹id（完整id）"),
    pn: int = Query(1, description="页码"),
    ps: int = Query(40, description="每页项数"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    order: str = Query("mtime", description="排序方式，mtime（收藏时间）或view（播放量）"),
    type: int = Query(0, description="筛选类型，0=全部，2=视频"),
    tid: int = Query(0, description="分区ID，0=全部"),
    platform: str = Query("web", description="平台标识"),
    sessdata: Optional[str] = Query(None, description="用户的 SESSDATA")
):
    """
    获取收藏夹内容列表
    
    需要登录才能查看私密收藏夹
    """
    try:
        url = "https://api.bilibili.com/x/v3/fav/resource/list"
        params = {
            "media_id": media_id,
            "pn": pn,
            "ps": ps,
            "order": order,
            "type": type,
            "tid": tid,
            "platform": platform
        }
        if keyword:
            params["keyword"] = keyword
            
        headers = get_headers(sessdata)
        
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        
        # 检查API响应
        if data.get('code') != 0:
            return {
                "status": "error",
                "message": data.get('message', '未知错误'),
                "code": data.get('code')
            }
        
        result_data = data.get('data', {})
        
        # 保存到数据库
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            timestamp = int(time.time())
            
            # 保存收藏夹元数据
            info = result_data.get('info', {})
            if info and 'id' in info:
                # 保存创建者信息
                upper = info.get('upper', {})
                if upper and 'mid' in upper:
                    cursor.execute("""
                    INSERT OR REPLACE INTO favorites_creator 
                    (mid, name, face, followed, vip_type, vip_status, fetch_time) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        upper.get('mid'),
                        upper.get('name', ''),
                        upper.get('face', ''),
                        1 if upper.get('followed') else 0,
                        upper.get('vip_type', 0),
                        upper.get('vip_statue', 0),  # API返回的字段名可能有误
                        timestamp
                    ))
                
                # 保存收藏夹信息
                cursor.execute("""
                INSERT OR REPLACE INTO favorites_folder 
                (media_id, fid, mid, title, cover, attr, intro, ctime, mtime, state, media_count, fav_state, like_state, fetch_time) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    info.get('id'),
                    info.get('fid'),
                    info.get('mid'),
                    info.get('title', ''),
                    info.get('cover', ''),
                    info.get('attr'),
                    info.get('intro', ''),
                    info.get('ctime'),
                    info.get('mtime'),
                    info.get('state'),
                    info.get('media_count', 0),
                    info.get('fav_state', 0),
                    info.get('like_state', 0),
                    timestamp
                ))
            
            # 保存收藏夹内容
            for resource in result_data.get('medias', []):
                # 保存UP主信息
                upper = resource.get('upper', {})
                if upper and 'mid' in upper:
                    cursor.execute("""
                    INSERT OR REPLACE INTO favorites_creator 
                    (mid, name, face, followed, vip_type, vip_status, fetch_time) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        upper.get('mid'),
                        upper.get('name', ''),
                        upper.get('face', ''),
                        0,  # API不返回是否关注
                        0,  # API不返回会员类型
                        0,  # API不返回会员状态
                        timestamp
                    ))
                
                # 保存资源信息
                cursor.execute("""
                INSERT OR REPLACE INTO favorites_content 
                (media_id, content_id, type, title, cover, bvid, intro, page, duration, upper_mid, attr, ctime, pubtime, fav_time, link, fetch_time,
                creator_name, creator_face, bv_id, collect, play, danmaku, vt, play_switch, reply, view_text_1, first_cid, media_list_link) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    media_id,
                    resource.get('id'),
                    resource.get('type'),
                    resource.get('title', ''),
                    resource.get('cover', ''),
                    resource.get('bvid', ''),
                    resource.get('intro', ''),
                    resource.get('page', 0),
                    resource.get('duration', 0),
                    upper.get('mid') if upper else 0,
                    resource.get('attr', 0),
                    resource.get('ctime', 0),
                    resource.get('pubtime', 0),
                    resource.get('fav_time', 0),
                    resource.get('link', ''),
                    timestamp,
                    upper.get('name', '') if upper else '',
                    upper.get('face', '') if upper else '',
                    resource.get('bv_id', ''),
                    resource.get('cnt_info', {}).get('collect', 0),
                    resource.get('cnt_info', {}).get('play', 0),
                    resource.get('cnt_info', {}).get('danmaku', 0),
                    resource.get('cnt_info', {}).get('vt', 0),
                    resource.get('cnt_info', {}).get('play_switch', 0),
                    resource.get('cnt_info', {}).get('reply', 0),
                    resource.get('cnt_info', {}).get('view_text_1', ''),
                    resource.get('ugc', {}).get('first_cid', 0) if resource.get('ugc') else 0,
                    resource.get('media_list_link', '')
                ))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"保存收藏夹内容到数据库时出错: {str(e)}")
        finally:
            conn.close()
        
        return {
            "status": "success",
            "message": "获取收藏夹内容成功",
            "data": result_data
        }
        
    except Exception as e:
        print(f"获取收藏夹内容时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"获取收藏夹内容失败: {str(e)}"
        }

@router.get("/list", summary="获取数据库中的收藏夹列表")
async def get_favorites_list(
    mid: Optional[int] = Query(None, description="用户UID，不提供则返回所有收藏夹"),
    page: int = Query(1, description="页码"),
    size: int = Query(40, description="每页数量")
):
    """获取已保存到数据库中的收藏夹列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 构建查询条件
        where_clause = "WHERE 1=1"
        params = []
        
        if mid is not None:
            where_clause += " AND mid = ?"
            params.append(mid)
        
        # 计算总数
        cursor.execute(f"SELECT COUNT(*) FROM favorites_folder {where_clause}", params)
        total = cursor.fetchone()[0]
        
        # 分页查询
        offset = (page - 1) * size
        cursor.execute(f"""
        SELECT f.*, 
               c.name as creator_name, c.face as creator_face 
        FROM favorites_folder f
        LEFT JOIN favorites_creator c ON f.mid = c.mid
        {where_clause}
        ORDER BY f.mtime DESC
        LIMIT ? OFFSET ?
        """, params + [size, offset])
        
        rows = cursor.fetchall()
        folders = []
        
        for row in rows:
            folder = dict(row)
            folders.append(folder)
        
        conn.close()
        
        return {
            "status": "success",
            "message": "获取收藏夹列表成功",
            "data": {
                "list": folders,
                "total": total,
                "page": page,
                "size": size
            }
        }
        
    except Exception as e:
        print(f"获取收藏夹列表时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"获取收藏夹列表失败: {str(e)}"
        }

@router.get("/content/list", summary="获取数据库中的收藏内容列表")
async def get_favorites_content(
    media_id: int = Query(..., description="收藏夹ID"),
    page: int = Query(1, description="页码"),
    size: int = Query(40, description="每页数量")
):
    """获取已保存到数据库中的收藏内容列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 计算总数
        cursor.execute("SELECT COUNT(*) FROM favorites_content WHERE media_id = ?", (media_id,))
        total = cursor.fetchone()[0]
        
        # 分页查询
        offset = (page - 1) * size
        cursor.execute("""
        SELECT c.*, 
               cr.name as creator_name, cr.face as creator_face 
        FROM favorites_content c
        LEFT JOIN favorites_creator cr ON c.upper_mid = cr.mid
        WHERE c.media_id = ?
        ORDER BY c.fav_time DESC
        LIMIT ? OFFSET ?
        """, (media_id, size, offset))
        
        rows = cursor.fetchall()
        contents = []
        
        for row in rows:
            content = dict(row)
            contents.append(content)
        
        conn.close()
        
        return {
            "status": "success",
            "message": "获取收藏内容列表成功",
            "data": {
                "list": contents,
                "total": total,
                "page": page,
                "size": size
            }
        }
        
    except Exception as e:
        print(f"获取收藏内容列表时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"获取收藏内容列表失败: {str(e)}"
        }

# 添加请求体数据模型
class FavoriteResourceRequest(BaseModel):
    rid: int = Field(..., description="稿件avid")
    add_media_ids: Optional[str] = Field(None, description="需要加入的收藏夹ID，多个用逗号分隔")
    del_media_ids: Optional[str] = Field(None, description="需要取消的收藏夹ID，多个用逗号分隔")
    sessdata: Optional[str] = Field(None, description="用户的SESSDATA")

@router.post("/resource/deal", summary="收藏或取消收藏单个视频")
async def favorite_resource(
    request: Optional[FavoriteResourceRequest] = None,
    rid: Optional[int] = Query(None, description="稿件avid"),
    add_media_ids: Optional[str] = Query(None, description="需要加入的收藏夹ID，多个用逗号分隔"),
    del_media_ids: Optional[str] = Query(None, description="需要取消的收藏夹ID，多个用逗号分隔"),
    sessdata: Optional[str] = Query(None, description="用户的SESSDATA")
):
    """
    收藏或取消收藏单个视频到指定收藏夹
    
    可以通过查询参数或请求体提交参数，支持两种方式
    
    - rid: 视频的av号(不含av前缀)
    - add_media_ids: 需要添加到的收藏夹ID，多个用逗号分隔
    - del_media_ids: 需要从中取消的收藏夹ID，多个用逗号分隔
    - sessdata: 用户的SESSDATA，不提供则从配置文件读取
    
    需要用户登录才能操作
    """
    try:
        # 优先使用请求体中的参数
        if request:
            rid = request.rid
            add_media_ids = request.add_media_ids
            del_media_ids = request.del_media_ids
            if request.sessdata:
                sessdata = request.sessdata
        
        # 检查必填参数
        if rid is None:
            return {
                "status": "error",
                "message": "缺少必填参数: rid (稿件avid)"
            }
        
        if not add_media_ids and not del_media_ids:
            return {
                "status": "error",
                "message": "需要提供至少一个收藏夹ID (add_media_ids 或 del_media_ids)"
            }
        
        # 获取请求头和Cookie
        headers = get_headers(sessdata)
        
        # 从配置或Cookie中获取bili_jct (CSRF Token)
        current_config = load_config()
        bili_jct = current_config.get("bili_jct", "")
        
        if not bili_jct:
            return {
                "status": "error",
                "message": "缺少CSRF Token (bili_jct)，请先使用QR码登录并确保已正确获取bili_jct"
            }
        
        # 准备请求参数
        data = {
            "rid": rid,
            "type": 2,  # 固定为2，表示视频稿件
            "csrf": bili_jct,
            "platform": "web",
            "eab_x": 1,
            "ramval": 0,
            "ga": 1,
            "gaia_source": "web_normal"
        }
        
        if add_media_ids:
            data["add_media_ids"] = add_media_ids
        
        if del_media_ids:
            data["del_media_ids"] = del_media_ids
        
        # 发起请求
        url = "https://api.bilibili.com/x/v3/fav/resource/deal"
        response = requests.post(url, data=data, headers=headers)
        result = response.json()
        
        # 检查响应
        if result.get('code') != 0:
            return {
                "status": "error",
                "message": result.get('message', '未知错误'),
                "code": result.get('code')
            }
        
        return {
            "status": "success",
            "message": "操作成功",
            "data": result.get('data', {})
        }
        
    except Exception as e:
        print(f"收藏操作失败: {str(e)}")
        return {
            "status": "error",
            "message": f"收藏操作失败: {str(e)}"
        }

# 添加批量请求体数据模型
class BatchFavoriteResourceRequest(BaseModel):
    rids: str = Field(..., description="稿件avid列表，多个用逗号分隔")
    add_media_ids: Optional[str] = Field(None, description="需要加入的收藏夹ID，多个用逗号分隔")
    del_media_ids: Optional[str] = Field(None, description="需要取消的收藏夹ID，多个用逗号分隔")
    sessdata: Optional[str] = Field(None, description="用户的SESSDATA")

@router.post("/resource/batch-deal", summary="批量收藏或取消收藏视频")
async def batch_favorite_resource(
    request: Optional[BatchFavoriteResourceRequest] = None,
    rids: Optional[str] = Query(None, description="稿件avid列表，多个用逗号分隔"),
    add_media_ids: Optional[str] = Query(None, description="需要加入的收藏夹ID，多个用逗号分隔"),
    del_media_ids: Optional[str] = Query(None, description="需要取消的收藏夹ID，多个用逗号分隔"),
    sessdata: Optional[str] = Query(None, description="用户的SESSDATA")
):
    """
    批量收藏或取消收藏多个视频到指定收藏夹
    
    可以通过查询参数或请求体提交参数，支持两种方式
    
    - rids: 视频的av号列表(不含av前缀)，多个用逗号分隔
    - add_media_ids: 需要添加到的收藏夹ID，多个用逗号分隔
    - del_media_ids: 需要从中取消的收藏夹ID，多个用逗号分隔
    - sessdata: 用户的SESSDATA，不提供则从配置文件读取
    
    需要用户登录才能操作
    """
    try:
        # 优先使用请求体中的参数
        if request:
            rids = request.rids
            add_media_ids = request.add_media_ids
            del_media_ids = request.del_media_ids
            if request.sessdata:
                sessdata = request.sessdata
        
        # 检查必填参数
        if not rids:
            return {
                "status": "error",
                "message": "缺少必填参数: rids (稿件avid列表)"
            }
            
        if not add_media_ids and not del_media_ids:
            return {
                "status": "error",
                "message": "需要提供至少一个收藏夹ID (add_media_ids 或 del_media_ids)"
            }
        
        # 处理输入参数
        try:
            rid_list = [int(rid.strip()) for rid in rids.split(',') if rid.strip()]
        except ValueError:
            return {
                "status": "error",
                "message": "无效的rids参数格式，请使用逗号分隔的整数列表"
            }
        
        if not rid_list:
            return {
                "status": "error",
                "message": "请提供至少一个有效的视频ID"
            }
        
        # 获取请求头和Cookie
        headers = get_headers(sessdata)
        
        # 从配置或Cookie中获取bili_jct (CSRF Token)
        current_config = load_config()
        bili_jct = current_config.get("bili_jct", "")
        
        if not bili_jct:
            return {
                "status": "error",
                "message": "缺少CSRF Token (bili_jct)，请先使用QR码登录并确保已正确获取bili_jct"
            }
        
        # 批量处理每个视频
        results = []
        for rid in rid_list:
            # 准备请求参数
            data = {
                "rid": rid,
                "type": 2,  # 固定为2，表示视频稿件
                "csrf": bili_jct,
                "platform": "web",
                "eab_x": 1,
                "ramval": 0,
                "ga": 1,
                "gaia_source": "web_normal"
            }
            
            if add_media_ids:
                data["add_media_ids"] = add_media_ids
            
            if del_media_ids:
                data["del_media_ids"] = del_media_ids
            
            # 发起请求
            url = "https://api.bilibili.com/x/v3/fav/resource/deal"
            response = requests.post(url, data=data, headers=headers)
            result = response.json()
            
            # 添加结果
            results.append({
                "rid": rid,
                "code": result.get('code'),
                "message": result.get('message'),
                "data": result.get('data')
            })
            
            # 添加短暂延迟，防止频繁请求
            time.sleep(0.5)
        
        # 检查是否全部成功
        all_success = all(result["code"] == 0 for result in results)
        
        return {
            "status": "success" if all_success else "partial_success",
            "message": "所有操作成功完成" if all_success else "部分操作成功",
            "results": results
        }
        
    except Exception as e:
        print(f"批量收藏操作失败: {str(e)}")
        return {
            "status": "error",
            "message": f"批量收藏操作失败: {str(e)}"
        }

class CheckFavoritesRequest(BaseModel):
    oids: List[int] = Field(..., description="视频的av号列表")
    sessdata: Optional[str] = Field(None, description="用户的SESSDATA")

@router.post("/check/batch", summary="批量检查视频是否已被收藏", tags=["收藏夹管理"])
async def check_favorites_batch(request: CheckFavoritesRequest):
    """
    批量检查多个视频是否已被收藏
    
    - oids: 视频的av号列表
    - sessdata: 用户的SESSDATA，不提供则从配置文件读取
    
    响应格式:
    ```json
    {
        "status": "success",
        "data": {
            "results": [
                {
                    "oid": 123456,
                    "is_favorited": true,
                    "favorite_folders": [
                        {"media_id": 1234567, "title": "收藏夹名称"}
                    ]
                }
            ]
        }
    }
    ```
    """
    try:
        # 获取请求参数
        oids = request.oids
        sessdata = request.sessdata
        
        if not oids:
            return {
                "status": "error",
                "message": "请提供至少一个视频av号"
            }
        
        # 查询B站API获取用户的收藏夹列表
        user_info = await get_current_user_info(sessdata)
        if not user_info:
            return {
                "status": "error",
                "message": "无法获取用户信息，请确保已登录"
            }
        
        # 获取本地数据库中的相关收藏信息
        conn = get_db_connection()
        cursor = conn.cursor()
        
        results = []
        # 遍历每个视频av号
        for oid in oids:
            # 查询本地数据库中是否收藏了该视频
            cursor.execute("""
            SELECT fc.media_id, ff.title 
            FROM favorites_content fc
            JOIN favorites_folder ff ON fc.media_id = ff.media_id
            WHERE fc.content_id = ? AND fc.type = 2
            """, (oid,))
            
            rows = cursor.fetchall()
            is_favorited = len(rows) > 0
            favorite_folders = []
            
            if is_favorited:
                for row in rows:
                    favorite_folders.append({
                        "media_id": row[0],
                        "title": row[1]
                    })
            
            results.append({
                "oid": oid,
                "is_favorited": is_favorited,
                "favorite_folders": favorite_folders
            })
        
        conn.close()
        
        return {
            "status": "success",
            "data": {
                "results": results
            }
        }
        
    except Exception as e:
        print(f"批量检查收藏状态时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"批量检查收藏状态失败: {str(e)}"
        }

@router.get("/check", summary="检查单个视频是否已被收藏", tags=["收藏夹管理"])
async def check_favorite(
    oid: int = Query(..., description="视频的av号"),
    sessdata: Optional[str] = Query(None, description="用户的SESSDATA")
):
    """
    检查单个视频是否已被收藏
    
    - oid: 视频的av号
    - sessdata: 用户的SESSDATA，不提供则从配置文件读取
    
    响应格式:
    ```json
    {
        "status": "success",
        "data": {
            "oid": 123456,
            "is_favorited": true,
            "favorite_folders": [
                {"media_id": 1234567, "title": "收藏夹名称"}
            ]
        }
    }
    ```
    """
    try:
        # 查询本地数据库中是否收藏了该视频
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT fc.media_id, ff.title 
        FROM favorites_content fc
        JOIN favorites_folder ff ON fc.media_id = ff.media_id
        WHERE fc.content_id = ? AND fc.type = 2
        """, (oid,))
        
        rows = cursor.fetchall()
        is_favorited = len(rows) > 0
        favorite_folders = []
        
        if is_favorited:
            for row in rows:
                favorite_folders.append({
                    "media_id": row[0],
                    "title": row[1]
                })
        
        conn.close()
        
        return {
            "status": "success",
            "data": {
                "oid": oid,
                "is_favorited": is_favorited,
                "favorite_folders": favorite_folders
            }
        }
        
    except Exception as e:
        print(f"检查收藏状态时出错: {str(e)}")
        return {
            "status": "error",
            "message": f"检查收藏状态失败: {str(e)}"
        }

class BatchLocalFavoriteRequest(BaseModel):
    rids: str = Field(..., description="稿件avid列表，多个用逗号分隔")
    add_media_ids: Optional[str] = Field(None, description="需要加入的收藏夹ID，多个用逗号分隔")
    del_media_ids: Optional[str] = Field(None, description="需要取消的收藏夹ID，多个用逗号分隔")
    operation_type: str = Field("sync", description="操作类型，sync=同步到远程，local=仅本地操作")

@router.post("/resource/local-batch-deal", summary="本地批量收藏或取消收藏视频")
async def local_batch_favorite_resource(
    request: BatchLocalFavoriteRequest,
    sessdata: Optional[str] = Query(None, description="用户的SESSDATA")
):
    """
    在本地数据库中批量收藏或取消收藏多个视频
    
    - rids: 视频的av号列表(不含av前缀)，多个用逗号分隔
    - add_media_ids: 需要添加到的收藏夹ID，多个用逗号分隔
    - del_media_ids: 需要从中取消的收藏夹ID，多个用逗号分隔
    - operation_type: 操作类型，sync=同步到远程，local=仅本地操作
    
    此接口用于本地数据库和远程B站的收藏同步管理
    """
    try:
        # 获取请求参数
        rids = request.rids
        add_media_ids = request.add_media_ids
        del_media_ids = request.del_media_ids
        operation_type = request.operation_type
        
        # 检查必填参数
        if not rids:
            return {
                "status": "error",
                "message": "缺少必填参数: rids (稿件avid列表)"
            }
            
        if not add_media_ids and not del_media_ids:
            return {
                "status": "error",
                "message": "需要提供至少一个收藏夹ID (add_media_ids 或 del_media_ids)"
            }
        
        # 处理输入参数
        try:
            rid_list = [int(rid.strip()) for rid in rids.split(',') if rid.strip()]
        except ValueError:
            return {
                "status": "error",
                "message": "无效的rids参数格式，请使用逗号分隔的整数列表"
            }
        
        if not rid_list:
            return {
                "status": "error",
                "message": "请提供至少一个有效的视频ID"
            }
        
        # 解析收藏夹ID
        add_folders = []
        if add_media_ids:
            add_folders = [int(mid.strip()) for mid in add_media_ids.split(',') if mid.strip()]
            
        del_folders = []
        if del_media_ids:
            del_folders = [int(mid.strip()) for mid in del_media_ids.split(',') if mid.strip()]
            
        # 连接数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取当前时间戳
        timestamp = int(datetime.now().timestamp())
        
        # 获取用户信息
        user_info = await get_current_user_info(sessdata)
        user_mid = user_info.get("uid") if user_info else 0
        
        results = []
        
        # 同步到远程B站
        if operation_type == "sync":
            # 复用现有的批量收藏接口
            batch_request = BatchFavoriteResourceRequest(
                rids=rids,
                add_media_ids=add_media_ids,
                del_media_ids=del_media_ids,
                sessdata=sessdata
            )
            remote_result = await batch_favorite_resource(request=batch_request)
            
            # 如果远程操作失败，则只返回远程结果不进行本地操作
            if remote_result.get("status") != "success" and remote_result.get("status") != "partial_success":
                return remote_result
        
        # 遍历每个视频，处理本地数据库操作
        for rid in rid_list:
            result_item = {"rid": rid, "code": 0, "message": "success", "data": {}}
            
            try:
                # 处理取消收藏 (删除记录)
                if del_folders:
                    for media_id in del_folders:
                        cursor.execute("""
                        DELETE FROM favorites_content 
                        WHERE content_id = ? AND media_id = ? AND type = 2
                        """, (rid, media_id))
                        
                        if cursor.rowcount > 0:
                            result_item["data"]["removed_folders"] = result_item.get("data", {}).get("removed_folders", 0) + 1
                
                # 处理添加收藏 (添加记录)
                if add_folders:
                    for media_id in add_folders:
                        # 检查收藏夹是否存在
                        cursor.execute("SELECT * FROM favorites_folder WHERE media_id = ?", (media_id,))
                        folder = cursor.fetchone()
                        
                        if not folder:
                            # 收藏夹不存在，跳过
                            result_item["data"]["folder_not_found"] = result_item.get("data", {}).get("folder_not_found", 0) + 1
                            continue
                        
                        # 检查视频是否已在收藏夹中
                        cursor.execute("""
                        SELECT * FROM favorites_content 
                        WHERE content_id = ? AND media_id = ? AND type = 2
                        """, (rid, media_id))
                        
                        if cursor.fetchone():
                            # 已收藏，跳过
                            result_item["data"]["already_favorited"] = result_item.get("data", {}).get("already_favorited", 0) + 1
                            continue
                        
                        # 获取视频信息 (如标题等) - 尝试从数据库中其他收藏夹获取
                        cursor.execute("""
                        SELECT * FROM favorites_content 
                        WHERE content_id = ? AND type = 2
                        """, (rid,))
                        
                        existing_content = cursor.fetchone()
                        
                        # 如果在数据库中找到了视频信息，使用这些信息
                        if existing_content:
                            title = existing_content["title"]
                            cover = existing_content["cover"]
                            bvid = existing_content["bvid"]
                            intro = existing_content["intro"]
                            page = existing_content["page"]
                            duration = existing_content["duration"]
                            upper_mid = existing_content["upper_mid"]
                            attr = existing_content["attr"]
                            ctime = existing_content["ctime"]
                            pubtime = existing_content["pubtime"]
                            link = existing_content["link"]
                        else:
                            # 未找到视频信息，使用默认值
                            title = f"视频 av{rid}"
                            cover = ""
                            bvid = ""
                            intro = ""
                            page = 1
                            duration = 0
                            upper_mid = 0
                            attr = 0
                            ctime = timestamp
                            pubtime = timestamp
                            link = f"https://www.bilibili.com/video/av{rid}"
                        
                        # 添加收藏
                        cursor.execute("""
                        INSERT OR REPLACE INTO favorites_content 
                        (media_id, content_id, type, title, cover, bvid, intro, page, duration, upper_mid, attr, ctime, pubtime, fav_time, link, fetch_time,
                        creator_name, creator_face, bv_id, collect, play, danmaku, vt, play_switch, reply, view_text_1, first_cid, media_list_link) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            media_id,
                            rid,
                            2,  # 固定为2，表示视频稿件
                            title,
                            cover,
                            bvid,
                            intro,
                            page,
                            duration,
                            upper_mid,
                            attr,
                            ctime,
                            pubtime,
                            timestamp,  # 当前时间作为收藏时间
                            link,
                            timestamp,
                            existing_content["creator_name"] if existing_content and "creator_name" in existing_content else "",
                            existing_content["creator_face"] if existing_content and "creator_face" in existing_content else "",
                            existing_content["bv_id"] if existing_content and "bv_id" in existing_content else "",
                            existing_content["collect"] if existing_content and "collect" in existing_content else 0,
                            existing_content["play"] if existing_content and "play" in existing_content else 0,
                            existing_content["danmaku"] if existing_content and "danmaku" in existing_content else 0,
                            existing_content["vt"] if existing_content and "vt" in existing_content else 0,
                            existing_content["play_switch"] if existing_content and "play_switch" in existing_content else 0,
                            existing_content["reply"] if existing_content and "reply" in existing_content else 0,
                            existing_content["view_text_1"] if existing_content and "view_text_1" in existing_content else "",
                            existing_content["first_cid"] if existing_content and "first_cid" in existing_content else 0,
                            existing_content["media_list_link"] if existing_content and "media_list_link" in existing_content else ""
                        ))
                        
                        result_item["data"]["added_folders"] = result_item.get("data", {}).get("added_folders", 0) + 1
                
                # 添加成功消息
                result_item["data"]["prompt"] = True
                result_item["data"]["toast_msg"] = "本地收藏更新成功"
                results.append(result_item)
                
            except Exception as e:
                print(f"处理视频 {rid} 时出错: {str(e)}")
                result_item["code"] = -1
                result_item["message"] = f"本地操作失败: {str(e)}"
                results.append(result_item)
        
        # 提交事务
        conn.commit()
        conn.close()
        
        # 检查是否全部成功
        all_success = all(result["code"] == 0 for result in results)
        
        return {
            "status": "success" if all_success else "partial_success",
            "message": "所有本地操作成功完成" if all_success else "部分本地操作成功",
            "operation_type": operation_type,
            "results": results
        }
        
    except Exception as e:
        print(f"本地批量收藏操作失败: {str(e)}")
        return {
            "status": "error",
            "message": f"本地批量收藏操作失败: {str(e)}"
        }

# 添加需要的库
import re


# 添加新的请求模型
class RepairVideosRequest(BaseModel):
    video_ids: List[int] = Field(..., description="需要修复的视频av号列表")
    media_id: Optional[int] = Field(None, description="指定收藏夹ID，如果提供则会修复该收藏夹下的所有失效视频")
    repair_all: bool = Field(False, description="是否修复所有收藏夹中的失效视频")
    bvids: Optional[List[str]] = Field(None, description="需要修复的视频BV号列表(选填，与video_ids互补)")
    sessdata: Optional[str] = Field(None, description="用户的SESSDATA")

@router.post("/repair/batch", summary="批量修复失效收藏视频信息")
async def batch_repair_videos(
    request: RepairVideosRequest
):
    """
    批量修复失效收藏视频信息
    
    尝试通过多个数据源（B站API、BiliPlus、JijiDown、XBeiBeiX等）获取失效视频的信息，
    并将结果整合保存到本地数据库。
    
    - video_ids: 需要修复的视频av号列表
    - media_id: 指定收藏夹ID，如果提供则会修复该收藏夹下的所有失效视频
    - repair_all: 是否修复所有收藏夹中的失效视频
    - bvids: 需要修复的视频BV号列表(选填，与video_ids互补)
    - sessdata: 用户的SESSDATA，不提供则从配置文件读取
    
    响应包含各个数据源的查询结果和整合后的最终结果
    """
    try:
        # 获取请求参数
        video_ids = request.video_ids or []
        media_id = request.media_id
        repair_all = request.repair_all
        bvids = request.bvids or []
        sessdata = request.sessdata
        
        # 连接数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取当前时间戳
        timestamp = int(datetime.now().timestamp())
        
        # 如果提供了media_id，获取该收藏夹下所有失效视频
        if media_id:
            cursor.execute("""
            SELECT content_id, bvid FROM favorites_content 
            WHERE media_id = ? AND type = 2 AND title = '已失效视频'
            """, (media_id,))
            
            for row in cursor.fetchall():
                if row["content_id"] not in video_ids:
                    video_ids.append(row["content_id"])
                if row["bvid"] and row["bvid"] not in bvids:
                    bvids.append(row["bvid"])
        
        # 如果repair_all=True，获取所有收藏夹中的失效视频
        if repair_all:
            cursor.execute("""
            SELECT DISTINCT content_id, bvid FROM favorites_content 
            WHERE type = 2 AND title = '已失效视频'
            """)
            
            for row in cursor.fetchall():
                if row["content_id"] not in video_ids:
                    video_ids.append(row["content_id"])
                if row["bvid"] and row["bvid"] not in bvids:
                    bvids.append(row["bvid"])
        
        # 如果没有提供视频ID和BV号，返回错误
        if not video_ids and not bvids:
            return {
                "status": "error",
                "message": "请至少提供一个视频ID或者指定一个包含失效视频的收藏夹"
            }
        
        # 确保每个BV号都有对应的AV号
        for bvid in bvids:
            if bvid:
                # 从数据库中查询是否已有对应的AV号
                cursor.execute("SELECT content_id FROM favorites_content WHERE bvid = ?", (bvid,))
                row = cursor.fetchone()
                
                if row and row["content_id"] not in video_ids:
                    video_ids.append(row["content_id"])
                # 如果数据库中没有，在这里我们可以添加BV号到AV号的转换逻辑
                # 但这需要依赖外部API或算法，暂时跳过
        
        # 准备结果数据结构
        results = []
        
        # 对每个视频进行修复
        for avid in video_ids:
            if not avid:
                continue
                
            # 准备该视频的结果对象
            video_result = {
                "avid": avid,
                "bvid": "",
                "success": False,
                "bilibili_api": None,
                "biliplus_api": None,
                "jijidown_api": None,
                "xbeibeix_api": None,
                "final_data": None
            }
            
            # 查找视频对应的BV号
            bvid = None
            cursor.execute("SELECT bvid FROM favorites_content WHERE content_id = ? LIMIT 1", (avid,))
            row = cursor.fetchone()
            if row and row["bvid"]:
                bvid = row["bvid"]
                video_result["bvid"] = bvid
            
            # 1. 尝试B站官方API
            try:
                url = f"https://api.bilibili.com/x/web-interface/view?aid={avid}"
                headers = get_headers(sessdata)
                
                response = requests.get(url, headers=headers)
                bilibili_data = response.json()
                
                video_result["bilibili_api"] = bilibili_data
                
                # 如果B站API返回成功
                if bilibili_data.get("code") == 0 and bilibili_data.get("data"):
                    data = bilibili_data.get("data", {})
                    
                    # 提取数据
                    title = data.get("title", "")
                    cover = data.get("pic", "")
                    intro = data.get("desc", "")
                    bvid = data.get("bvid", "")
                    duration = data.get("duration", 0)
                    upper_mid = data.get("owner", {}).get("mid", 0)
                    creator_name = data.get("owner", {}).get("name", "")
                    creator_face = data.get("owner", {}).get("face", "")
                    ctime = data.get("ctime", 0)
                    pubtime = data.get("pubdate", 0)
                    
                    # 统计数据
                    stat = data.get("stat", {})
                    play = stat.get("view", 0)
                    danmaku = stat.get("danmaku", 0)
                    reply = stat.get("reply", 0)
                    collect = stat.get("favorite", 0)
                    
                    # 更新视频结果
                    video_result["success"] = True
                    video_result["final_data"] = {
                        "title": title,
                        "cover": cover,
                        "intro": intro,
                        "bvid": bvid,
                        "duration": duration,
                        "upper_mid": upper_mid,
                        "creator_name": creator_name,
                        "creator_face": creator_face,
                        "ctime": ctime,
                        "pubtime": pubtime,
                        "play": play,
                        "danmaku": danmaku,
                        "reply": reply,
                        "collect": collect,
                        "source": "bilibili_api"
                    }
                    
                    # 更新数据库中的视频信息
                    cursor.execute("""
                    UPDATE favorites_content
                    SET title = ?, cover = ?, intro = ?, bvid = ?, 
                        duration = ?, upper_mid = ?, creator_name = ?, creator_face = ?,
                        ctime = ?, pubtime = ?, play = ?, danmaku = ?, reply = ?, collect = ?,
                        fetch_time = ?
                    WHERE content_id = ? AND type = 2
                    """, (
                        title, cover, intro, bvid,
                        duration, upper_mid, creator_name, creator_face,
                        ctime, pubtime, play, danmaku, reply, collect,
                        timestamp, avid
                    ))
                    
                    # 如果已经从B站API获取到了有效数据，可以跳过其他数据源
                    continue
            except Exception as e:
                print(f"从B站API获取视频 {avid} 信息时出错: {str(e)}")
            
            # 2. 尝试BiliPlus API
            try:
                url = f"https://www.biliplus.com/api/aidinfo?aid={avid}"
                
                response = requests.get(url)
                biliplus_data = response.json()
                
                video_result["biliplus_api"] = biliplus_data
                
                # 如果BiliPlus API返回成功
                if biliplus_data.get("code") == 0 and str(avid) in biliplus_data.get("data", {}):
                    data = biliplus_data.get("data", {}).get(str(avid), {})
                    
                    # 提取数据
                    title = data.get("title", "")
                    cover = data.get("pic", "")
                    bvid = data.get("bvid", "")
                    creator_name = data.get("author", "")
                    
                    # 如果之前没有成功，更新视频结果
                    if not video_result["success"]:
                        video_result["success"] = True
                        video_result["final_data"] = {
                            "title": title,
                            "cover": cover,
                            "bvid": bvid,
                            "creator_name": creator_name,
                            "source": "biliplus_api"
                        }
                        
                        # 更新数据库中的视频信息
                        update_fields = ["title = ?", "cover = ?", "bvid = ?", "creator_name = ?", "fetch_time = ?"]
                        update_values = [title, cover, bvid, creator_name, timestamp]
                        
                        cursor.execute(f"""
                        UPDATE favorites_content
                        SET {", ".join(update_fields)}
                        WHERE content_id = ? AND type = 2
                        """, update_values + [avid])
                        
                        # 尝试获取更详细的信息
                        try:
                            detail_url = f"https://www.biliplus.com/api/view?id={avid}"
                            detail_response = requests.get(detail_url)
                            detail_data = detail_response.json()
                            
                            if detail_data.get("code") == 0:
                                video_result["biliplus_detail"] = detail_data
                                
                                # 更新一些额外字段
                                if detail_data.get("title"):
                                    video_result["final_data"]["title"] = detail_data.get("title")
                                
                                if detail_data.get("description"):
                                    video_result["final_data"]["intro"] = detail_data.get("description")
                                    cursor.execute("UPDATE favorites_content SET intro = ? WHERE content_id = ? AND type = 2", 
                                                  (detail_data.get("description"), avid))
                                
                                # 分P信息
                                if detail_data.get("list") and len(detail_data.get("list")) > 0:
                                    video_result["final_data"]["parts"] = [item.get("part") for item in detail_data.get("list")]
                        except Exception as e:
                            print(f"从BiliPlus详情API获取视频 {avid} 信息时出错: {str(e)}")
                    
                    # 如果已经获取到了有效数据，但还想从其他源获取更多信息，可以继续
            except Exception as e:
                print(f"从BiliPlus API获取视频 {avid} 信息时出错: {str(e)}")
            
            # 3. 尝试JijiDown API
            try:
                url = f"https://www.jijidown.com/api/v1/video/get_info?id={avid}"
                
                response = requests.get(url)
                jijidown_data = response.json()
                
                video_result["jijidown_api"] = jijidown_data
                
                # 如果JijiDown API返回成功
                if jijidown_data.get("upid") and jijidown_data.get("upid") != -1 and jijidown_data.get("title") and jijidown_data.get("title") != "视频去哪了呢？" and jijidown_data.get("title") != "该视频或许已经被删除了":
                    # 提取数据
                    title = jijidown_data.get("title", "")
                    cover = jijidown_data.get("img", "")
                    creator_name = jijidown_data.get("up", {}).get("author", "")
                    
                    # 如果之前没有成功，更新视频结果
                    if not video_result["success"]:
                        video_result["success"] = True
                        video_result["final_data"] = {
                            "title": title,
                            "cover": cover,
                            "creator_name": creator_name,
                            "source": "jijidown_api"
                        }
                        
                        # 更新数据库中的视频信息
                        update_fields = ["title = ?", "cover = ?", "creator_name = ?", "fetch_time = ?"]
                        update_values = [title, cover, creator_name, timestamp]
                        
                        cursor.execute(f"""
                        UPDATE favorites_content
                        SET {", ".join(update_fields)}
                        WHERE content_id = ? AND type = 2
                        """, update_values + [avid])
                    
                    # 否则补充缺失信息
                    elif video_result["final_data"] and not video_result["final_data"].get("cover") and cover:
                        video_result["final_data"]["cover"] = cover
                        cursor.execute("UPDATE favorites_content SET cover = ? WHERE content_id = ? AND type = 2", 
                                      (cover, avid))
            except Exception as e:
                print(f"从JijiDown API获取视频 {avid} 信息时出错: {str(e)}")
            
            # 4. 尝试XBeiBeiX网站
            try:
                # 需要先获取BV号
                if bvid:
                    url = f"https://xbeibeix.com/video/{bvid}"
                    
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1"
                    }
                    
                    response = requests.get(url, headers=headers)
                    
                    # 使用正则表达式提取信息
                    title_match = re.search(r'<h1[^>]*class="fw-bold"[^>]*>(.*?)</h1>', response.text)
                    img_match = re.search(r'<img[^>]*class="img-thumbnail"[^>]*src="([^"]+)"', response.text)
                    author_match = re.search(r'<input[^>]*value="([^"]+)"[^>]*>', response.text)
                    
                    title = title_match.group(1) if title_match else None
                    cover = img_match.group(1) if img_match else None
                    creator_name = author_match.group(1) if author_match else None
                    
                    video_result["xbeibeix_api"] = {
                        "status": "success" if title else "failed",
                        "title": title,
                        "cover": cover,
                        "creator_name": creator_name
                    }
                    
                    # 如果XBeiBeiX返回成功
                    if title and title != "视频去哪了呢？" and title != "该视频或许已经被删除了":
                        # 如果之前没有成功，更新视频结果
                        if not video_result["success"]:
                            video_result["success"] = True
                            video_result["final_data"] = {
                                "title": title,
                                "cover": cover,
                                "creator_name": creator_name,
                                "source": "xbeibeix"
                            }
                            
                            # 更新数据库中的视频信息
                            update_fields = []
                            update_values = []
                            
                            if title:
                                update_fields.append("title = ?")
                                update_values.append(title)
                            
                            if cover:
                                update_fields.append("cover = ?")
                                update_values.append(cover)
                            
                            if creator_name:
                                update_fields.append("creator_name = ?")
                                update_values.append(creator_name)
                            
                            update_fields.append("fetch_time = ?")
                            update_values.append(timestamp)
                            
                            if update_fields:
                                cursor.execute(f"""
                                UPDATE favorites_content
                                SET {", ".join(update_fields)}
                                WHERE content_id = ? AND type = 2
                                """, update_values + [avid])
                        
                        # 否则补充缺失信息
                        elif video_result["final_data"]:
                            updates_needed = False
                            update_fields = []
                            update_values = []
                            
                            if not video_result["final_data"].get("cover") and cover:
                                video_result["final_data"]["cover"] = cover
                                update_fields.append("cover = ?")
                                update_values.append(cover)
                                updates_needed = True
                            
                            if not video_result["final_data"].get("creator_name") and creator_name:
                                video_result["final_data"]["creator_name"] = creator_name
                                update_fields.append("creator_name = ?")
                                update_values.append(creator_name)
                                updates_needed = True
                            
                            if updates_needed:
                                update_fields.append("fetch_time = ?")
                                update_values.append(timestamp)
                                
                                cursor.execute(f"""
                                UPDATE favorites_content
                                SET {", ".join(update_fields)}
                                WHERE content_id = ? AND type = 2
                                """, update_values + [avid])
                else:
                    video_result["xbeibeix_api"] = {
                        "status": "skipped",
                        "reason": "missing_bvid"
                    }
            except Exception as e:
                print(f"从XBeiBeiX网站获取视频 {avid} 信息时出错: {str(e)}")
                video_result["xbeibeix_api"] = {
                    "status": "error",
                    "error": str(e)
                }
            
            # 将该视频的结果添加到总结果列表
            results.append(video_result)
        
        # 提交数据库更改
        conn.commit()
        conn.close()
        
        # 返回结果
        return {
            "status": "success",
            "message": f"已处理 {len(results)} 个视频",
            "success_count": sum(1 for r in results if r["success"]),
            "results": results
        }
        
    except Exception as e:
        print(f"批量修复失效视频时出错: {str(e)}")
        # 确保关闭数据库连接
        try:
            if conn and conn.in_transaction:
                conn.rollback()
            if conn:
                conn.close()
        except:
            pass
            
        return {
            "status": "error",
            "message": f"批量修复失效视频失败: {str(e)}"
        } 