import asyncio
import concurrent.futures
import json
import os
import random
import sqlite3
import time
from typing import Dict, Any, Optional, List

import httpx
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from loguru import logger

from scripts.utils import load_config, get_output_path
from scripts.bilibili_history import check_invalid_video, save_invalid_video, create_invalid_videos_table

router = APIRouter(tags=["视频详情"])

# 数据库路径
DB_PATH = os.path.join("output", "database", "bilibili_video_details.db")

# 全局进度状态
video_details_progress = {
    "is_processing": False,
    "is_complete": False,
    "is_stopped": False,  # 新增：是否被用户停止
    "total_videos": 0,
    "processed_videos": 0,
    "success_count": 0,
    "failed_count": 0,
    "error_videos": [],
    "skipped_invalid_count": 0,
    "start_time": 0,
    "last_update_time": 0
}

# 确保数据库目录存在
os.makedirs(os.path.join("output", "database"), exist_ok=True)

def _build_video_original_url(video: Dict[str, Any]) -> str:
    """根据视频详情字段构建可打开的B站视频链接"""
    bvid = (video.get("bvid") or "").strip()
    if not bvid:
        return ""
    return f"https://www.bilibili.com/video/{bvid}"


def init_db() -> None:
    """初始化数据库"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # 视频基本信息表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_base_info (
            id INTEGER PRIMARY KEY,
            bvid TEXT NOT NULL UNIQUE,
            aid INTEGER NOT NULL,
            videos INTEGER DEFAULT 1,
            tid INTEGER,
            tid_v2 INTEGER,
            tname TEXT,
            tname_v2 TEXT,
            copyright INTEGER,
            pic TEXT,
            title TEXT NOT NULL,
            pubdate INTEGER,
            ctime INTEGER,
            desc TEXT,
            desc_v2 TEXT,
            state INTEGER DEFAULT 0,
            duration INTEGER,
            mission_id INTEGER,
            dynamic TEXT,
            cid INTEGER,
            season_id INTEGER,
            premiere INTEGER,
            teenage_mode INTEGER DEFAULT 0,
            is_chargeable_season INTEGER DEFAULT 0,
            is_story INTEGER DEFAULT 0,
            is_upower_exclusive INTEGER DEFAULT 0,
            is_upower_play INTEGER DEFAULT 0,
            is_upower_preview INTEGER DEFAULT 0,
            is_upower_exclusive_with_qa INTEGER DEFAULT 0,
            no_cache INTEGER DEFAULT 0,
            is_season_display INTEGER DEFAULT 0,
            like_icon TEXT,
            need_jump_bv INTEGER DEFAULT 0,
            disable_show_up_info INTEGER DEFAULT 0,
            is_story_play INTEGER DEFAULT 0,
            owner_mid INTEGER,
            owner_name TEXT,
            owner_face TEXT,
            stat_view INTEGER DEFAULT 0,
            stat_danmaku INTEGER DEFAULT 0,
            stat_reply INTEGER DEFAULT 0,
            stat_favorite INTEGER DEFAULT 0,
            stat_coin INTEGER DEFAULT 0,
            stat_share INTEGER DEFAULT 0,
            stat_like INTEGER DEFAULT 0,
            stat_dislike INTEGER DEFAULT 0,
            stat_his_rank INTEGER DEFAULT 0,
            stat_now_rank INTEGER DEFAULT 0,
            stat_evaluation TEXT,
            dimension_width INTEGER,
            dimension_height INTEGER,
            dimension_rotate INTEGER DEFAULT 0,
            rights_bp INTEGER DEFAULT 0,
            rights_elec INTEGER DEFAULT 0,
            rights_download INTEGER DEFAULT 0,
            rights_movie INTEGER DEFAULT 0,
            rights_pay INTEGER DEFAULT 0,
            rights_hd5 INTEGER DEFAULT 0,
            rights_no_reprint INTEGER DEFAULT 0,
            rights_autoplay INTEGER DEFAULT 0,
            rights_ugc_pay INTEGER DEFAULT 0,
            rights_is_cooperation INTEGER DEFAULT 0,
            rights_ugc_pay_preview INTEGER DEFAULT 0,
            rights_no_background INTEGER DEFAULT 0,
            rights_clean_mode INTEGER DEFAULT 0,
            rights_is_stein_gate INTEGER DEFAULT 0,
            rights_is_360 INTEGER DEFAULT 0,
            rights_no_share INTEGER DEFAULT 0,
            rights_arc_pay INTEGER DEFAULT 0,
            rights_free_watch INTEGER DEFAULT 0,
            argue_msg TEXT,
            argue_type INTEGER DEFAULT 0,
            argue_link TEXT,
            fetch_time INTEGER NOT NULL,
            update_time INTEGER DEFAULT 0
        )
        """)

        # 视频分P信息表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_pages (
            id INTEGER PRIMARY KEY,
            bvid TEXT NOT NULL,
            cid INTEGER NOT NULL,
            page INTEGER NOT NULL,
            part TEXT,
            duration INTEGER,
            from_source TEXT,
            vid TEXT,
            weblink TEXT,
            dimension_width INTEGER,
            dimension_height INTEGER,
            dimension_rotate INTEGER DEFAULT 0,
            first_frame TEXT,
            ctime INTEGER DEFAULT 0,
            UNIQUE(bvid, cid)
        )
        """)

        # 视频标签信息表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_tags (
            id INTEGER PRIMARY KEY,
            bvid TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            tag_name TEXT NOT NULL,
            music_id TEXT,
            tag_type TEXT,
            jump_url TEXT,
            cover TEXT,
            content TEXT,
            short_content TEXT,
            type INTEGER,
            state INTEGER,
            UNIQUE(bvid, tag_id)
        )
        """)

        # UP主详细信息表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploader_info (
            mid INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sex TEXT,
            face TEXT,
            face_nft INTEGER DEFAULT 0,
            face_nft_type INTEGER DEFAULT 0,
            sign TEXT,
            rank TEXT,
            level INTEGER DEFAULT 0,
            regtime INTEGER DEFAULT 0,
            spacesta INTEGER DEFAULT 0,
            birthday TEXT,
            place TEXT,
            description TEXT,
            article INTEGER DEFAULT 0,
            fans INTEGER DEFAULT 0,
            friend INTEGER DEFAULT 0,
            attention INTEGER DEFAULT 0,
            official_role INTEGER DEFAULT 0,
            official_title TEXT,
            official_desc TEXT,
            official_type INTEGER DEFAULT 0,
            vip_type INTEGER DEFAULT 0,
            vip_status INTEGER DEFAULT 0,
            vip_due_date INTEGER DEFAULT 0,
            vip_pay_type INTEGER DEFAULT 0,
            vip_theme_type INTEGER DEFAULT 0,
            vip_avatar_subscript INTEGER DEFAULT 0,
            vip_nickname_color TEXT,
            vip_role INTEGER DEFAULT 0,
            vip_avatar_subscript_url TEXT,
            pendant_pid INTEGER DEFAULT 0,
            pendant_name TEXT,
            pendant_image TEXT,
            pendant_expire INTEGER DEFAULT 0,
            nameplate_nid INTEGER DEFAULT 0,
            nameplate_name TEXT,
            nameplate_image TEXT,
            nameplate_image_small TEXT,
            nameplate_level TEXT,
            nameplate_condition TEXT,
            is_senior_member INTEGER DEFAULT 0,
            following INTEGER DEFAULT 0,
            archive_count INTEGER DEFAULT 0,
            article_count INTEGER DEFAULT 0,
            like_num INTEGER DEFAULT 0,
            fetch_time INTEGER NOT NULL,
            update_time INTEGER DEFAULT 0
        )
        """)

        # 视频荣誉信息表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_honors (
            id INTEGER PRIMARY KEY,
            bvid TEXT NOT NULL,
            aid INTEGER NOT NULL,
            type INTEGER NOT NULL,
            desc TEXT,
            weekly_recommend_num INTEGER DEFAULT 0,
            UNIQUE(bvid, type)
        )
        """)

        # 视频字幕信息表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_subtitles (
            id INTEGER PRIMARY KEY,
            bvid TEXT NOT NULL,
            allow_submit INTEGER DEFAULT 0,
            subtitle_id INTEGER,
            lan TEXT,
            lan_doc TEXT,
            is_lock INTEGER DEFAULT 0,
            subtitle_url TEXT,
            UNIQUE(bvid, subtitle_id)
        )
        """)

        # 相关视频信息表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS related_videos (
            id INTEGER PRIMARY KEY,
            bvid TEXT NOT NULL,
            related_bvid TEXT NOT NULL,
            related_aid INTEGER NOT NULL,
            related_title TEXT,
            related_pic TEXT,
            related_owner_mid INTEGER,
            related_owner_name TEXT,
            related_owner_face TEXT,
            UNIQUE(bvid, related_bvid)
        )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_base_info_owner_mid ON video_base_info (owner_mid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_base_info_fetch_time ON video_base_info (fetch_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_pages_bvid ON video_pages (bvid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_tags_bvid ON video_tags (bvid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_honors_bvid ON video_honors (bvid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_subtitles_bvid ON video_subtitles (bvid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_related_videos_bvid ON related_videos (bvid)")

        # 提交更改
        conn.commit()


async def get_video_detail(bvid: str) -> Dict[str, Any]:
    """
    获取视频超详细信息

    Args:
        bvid: 视频的BV号

    Returns:
        视频详细信息
    """
    config = load_config()
    cookies = config.get("cookies", {})

    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()]) if cookies else ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com",
        "Cookie": cookie_str
    }

    url = f"https://api.bilibili.com/x/web-interface/view/detail?bvid={bvid}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                raise HTTPException(status_code=400, detail=f"API错误: {data.get('message', '未知错误')}")

            return data
    except httpx.HTTPError as e:
        logger.error(f"请求视频详情API失败: {e}")
        raise HTTPException(status_code=500, detail=f"请求API失败: {str(e)}")


def get_video_detail_sync(bvid: str, cookie_str: str = "", use_sessdata: bool = True) -> Dict[str, Any]:
    """
    同步获取视频超详细信息（用于线程池）

    Args:
        bvid: 视频的BV号
        cookie_str: Cookie字符串
        use_sessdata: 是否使用SESSDATA

    Returns:
        视频详细信息
    """
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com"
    }

    if use_sessdata and cookie_str:
        headers["Cookie"] = cookie_str

    url = f"https://api.bilibili.com/x/web-interface/view/detail?bvid={bvid}"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            logger.warning(f"API错误 {bvid}: {data.get('message', '未知错误')}")
            return data  # 返回错误数据，让调用者处理

        return data
    except requests.RequestException as e:
        logger.error(f"请求视频详情API失败 {bvid}: {e}")
        return {"code": -1, "message": f"请求失败: {str(e)}"}


def save_video_detail_to_db(data: Dict[str, Any]) -> None:
    """
    将视频详细信息保存到数据库

    Args:
        data: 视频详细信息数据
    """
    # 确保数据库已初始化
    init_db()

    # 打印原始响应数据，方便调试
    logger.info(f"保存视频详情原始数据: {json.dumps(data, ensure_ascii=False)[:500]}...")

    # 保存完整的API响应到文件，方便排查错误
    try:
        os.makedirs(os.path.join("output", "api_responses"), exist_ok=True)
        response_file = os.path.join("output", "api_responses", f"video_detail_{int(time.time())}.json")
        with open(response_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存完整API响应到文件: {response_file}")
    except Exception as e:
        logger.error(f"保存API响应到文件时出错: {e}")

    now_timestamp = int(time.time())
    view_data = data.get("data", {}).get("View", {})
    card_data = data.get("data", {}).get("Card", {})
    tags_data = data.get("data", {}).get("Tags", [])
    related_data = data.get("data", {}).get("Related", [])
    honor_reply_data = view_data.get("honor_reply", {}).get("honor", []) if view_data.get("honor_reply") else []
    subtitle_data = view_data.get("subtitle", {}) if view_data.get("subtitle") else {}

    # 调试: 获取表中实际的列名和数量
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(video_base_info)")
            table_columns = cursor.fetchall()
            column_names = [column[1] for column in table_columns]
            logger.info(f"数据库video_base_info表中实际的列名: {column_names}")
            logger.info(f"数据库video_base_info表中实际的列数: {len(column_names)}")
    except Exception as e:
        logger.error(f"获取表结构时出错: {e}")

    # 调试: 计算并打印值的数量，检查SQL语句列数是否匹配
    debug_values_count = [
        "bvid", "aid", "videos", "tid", "tid_v2", "tname", "tname_v2", "copyright", "pic", "title",
        "pubdate", "ctime", "desc", "desc_v2", "state", "duration", "mission_id", "dynamic", "cid",
        "season_id", "premiere", "teenage_mode", "is_chargeable_season", "is_story",
        "is_upower_exclusive", "is_upower_play", "is_upower_preview",
        "is_upower_exclusive_with_qa", "no_cache", "is_season_display", "like_icon",
        "need_jump_bv", "disable_show_up_info", "is_story_play", "owner_mid", "owner_name",
        "owner_face", "stat_view", "stat_danmaku", "stat_reply", "stat_favorite", "stat_coin",
        "stat_share", "stat_like", "stat_dislike", "stat_his_rank", "stat_now_rank",
        "stat_evaluation", "dimension_width", "dimension_height", "dimension_rotate",
        "rights_bp", "rights_elec", "rights_download", "rights_movie", "rights_pay", "rights_hd5",
        "rights_no_reprint", "rights_autoplay", "rights_ugc_pay", "rights_is_cooperation",
        "rights_ugc_pay_preview", "rights_no_background", "rights_clean_mode",
        "rights_is_stein_gate", "rights_is_360", "rights_no_share", "rights_arc_pay",
        "rights_free_watch", "argue_msg", "argue_type", "argue_link", "fetch_time", "update_time"
    ]
    logger.info(f"调试: 插入表的列数量={len(debug_values_count)}, VALUES 参数数量应为: {len(debug_values_count)}")

    # 调试: 尝试找出我们定义的列和表中实际列之间的差异
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(video_base_info)")
            table_columns = cursor.fetchall()
            db_column_names = [column[1] for column in table_columns]

            # 比较列名
            our_columns = set(debug_values_count)
            db_columns = set(db_column_names)
            missing_in_our_def = db_columns - our_columns
            extra_in_our_def = our_columns - db_columns

            if missing_in_our_def:
                logger.warning(f"我们定义中缺少的列: {missing_in_our_def}")
            if extra_in_our_def:
                logger.warning(f"我们定义中多余的列: {extra_in_our_def}")

            # 检查顺序是否一致
            if len(debug_values_count) == len(db_column_names) - 1:  # 减1是因为id列是自增的
                for i, (ours, db) in enumerate(zip(debug_values_count, db_column_names[1:])):  # 跳过id列
                    if ours != db:
                        logger.warning(f"列顺序不匹配: 索引{i}，我们的定义是 '{ours}'，数据库是 '{db}'")
    except Exception as e:
        logger.error(f"比较列名时出错: {e}")

    if not view_data:
        logger.error("视频数据为空")
        return

    bvid = view_data.get("bvid")
    if not bvid:
        logger.error("视频BV号为空")
        return

    # 记录详细的数据结构信息
    logger.debug(f"保存视频 {bvid} 详情: view_data keys: {view_data.keys()}")
    logger.debug(f"rights keys: {view_data.get('rights', {}).keys()}")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()

            # 1. 保存视频基本信息
            owner = view_data.get("owner", {})
            stat = view_data.get("stat", {})
            dimension = view_data.get("dimension", {})
            rights = view_data.get("rights", {})
            argue_info = view_data.get("argue_info", {})

            # 检查视频是否已存在
            cursor.execute("SELECT bvid FROM video_base_info WHERE bvid = ?", (bvid,))
            existing = cursor.fetchone()

            if existing:
                # 更新现有数据
                cursor.execute("""
                UPDATE video_base_info SET
                    videos = ?, tid = ?, tid_v2 = ?, tname = ?, tname_v2 = ?,
                    copyright = ?, pic = ?, title = ?, pubdate = ?, ctime = ?,
                    desc = ?, desc_v2 = ?, state = ?, duration = ?, mission_id = ?,
                    dynamic = ?, cid = ?, season_id = ?, premiere = ?, teenage_mode = ?,
                    is_chargeable_season = ?, is_story = ?, is_upower_exclusive = ?,
                    is_upower_play = ?, is_upower_preview = ?,
                    is_upower_exclusive_with_qa = ?, no_cache = ?,
                    is_season_display = ?, like_icon = ?, need_jump_bv = ?,
                    disable_show_up_info = ?, is_story_play = ?,
                    owner_mid = ?, owner_name = ?, owner_face = ?,
                    stat_view = ?, stat_danmaku = ?, stat_reply = ?, stat_favorite = ?,
                    stat_coin = ?, stat_share = ?, stat_like = ?, stat_dislike = ?,
                    stat_his_rank = ?, stat_now_rank = ?, stat_evaluation = ?,
                    dimension_width = ?, dimension_height = ?, dimension_rotate = ?,
                    rights_bp = ?, rights_elec = ?, rights_download = ?, rights_movie = ?,
                    rights_pay = ?, rights_hd5 = ?, rights_no_reprint = ?, rights_autoplay = ?,
                    rights_ugc_pay = ?, rights_is_cooperation = ?, rights_ugc_pay_preview = ?,
                    rights_no_background = ?, rights_clean_mode = ?, rights_is_stein_gate = ?,
                    rights_is_360 = ?, rights_no_share = ?, rights_arc_pay = ?, rights_free_watch = ?,
                    argue_msg = ?, argue_type = ?, argue_link = ?,
                    update_time = ?
                WHERE bvid = ?
                """, (
                    view_data.get("videos", 1),
                    view_data.get("tid"),
                    view_data.get("tid_v2"),
                    view_data.get("tname"),
                    view_data.get("tname_v2"),
                    view_data.get("copyright"),
                    view_data.get("pic"),
                    view_data.get("title"),
                    view_data.get("pubdate"),
                    view_data.get("ctime"),
                    view_data.get("desc"),
                    # 对于desc_v2字段，如果是列表且有内容，只取第一项的raw_text值
                    (view_data.get("desc_v2")[0].get("raw_text") if isinstance(view_data.get("desc_v2"), list) and view_data.get("desc_v2") else ""),
                    view_data.get("state", 0),
                    view_data.get("duration"),
                    view_data.get("mission_id"),
                    view_data.get("dynamic"),
                    view_data.get("cid"),
                    view_data.get("season_id"),
                    1 if view_data.get("premiere") else 0,
                    view_data.get("teenage_mode", 0),
                    1 if view_data.get("is_chargeable_season") else 0,
                    1 if view_data.get("is_story") else 0,
                    1 if view_data.get("is_upower_exclusive") else 0,
                    1 if view_data.get("is_upower_play") else 0,
                    1 if view_data.get("is_upower_preview") else 0,
                    1 if view_data.get("is_upower_exclusive_with_qa") else 0,
                    1 if view_data.get("no_cache") else 0,
                    1 if view_data.get("is_season_display") else 0,
                    view_data.get("like_icon", ""),
                    1 if view_data.get("need_jump_bv") else 0,
                    1 if view_data.get("disable_show_up_info") else 0,
                    view_data.get("is_story_play", 0),
                    owner.get("mid"),
                    owner.get("name"),
                    owner.get("face"),
                    stat.get("view", 0),
                    stat.get("danmaku", 0),
                    stat.get("reply", 0),
                    stat.get("favorite", 0),
                    stat.get("coin", 0),
                    stat.get("share", 0),
                    stat.get("like", 0),
                    stat.get("dislike", 0),
                    stat.get("his_rank", 0),
                    stat.get("now_rank", 0),
                    stat.get("evaluation", ""),
                    dimension.get("width"),
                    dimension.get("height"),
                    dimension.get("rotate", 0),
                    rights.get("bp", 0),
                    rights.get("elec", 0),
                    rights.get("download", 0),
                    rights.get("movie", 0),
                    rights.get("pay", 0),
                    rights.get("hd5", 0),
                    rights.get("no_reprint", 0),
                    rights.get("autoplay", 0),
                    rights.get("ugc_pay", 0),
                    rights.get("is_cooperation", 0),
                    rights.get("ugc_pay_preview", 0),
                    rights.get("no_background", 0),
                    rights.get("clean_mode", 0),
                    rights.get("is_stein_gate", 0),
                    rights.get("is_360", 0),
                    rights.get("no_share", 0),
                    rights.get("arc_pay", 0),
                    rights.get("free_watch", 0),
                    argue_info.get("argue_msg", ""),
                    argue_info.get("argue_type", 0),
                    argue_info.get("argue_link", ""),
                    now_timestamp,
                    bvid
                ))
            else:
                # 插入新数据
                # 创建参数列表，先明确所有参数，便于调试
                insert_params = [
                    bvid,                                      # 1. bvid
                    view_data.get("aid"),                      # 2. aid
                    view_data.get("videos", 1),                # 3. videos
                    view_data.get("tid"),                      # 4. tid
                    view_data.get("tid_v2"),                   # 5. tid_v2
                    view_data.get("tname"),                    # 6. tname
                    view_data.get("tname_v2"),                 # 7. tname_v2
                    view_data.get("copyright"),                # 8. copyright
                    view_data.get("pic"),                      # 9. pic
                    view_data.get("title"),                    # 10. title
                    view_data.get("pubdate"),                  # 11. pubdate
                    view_data.get("ctime"),                    # 12. ctime
                    view_data.get("desc"),                     # 13. desc
                    # 对于desc_v2字段，如果是列表且有内容，只取第一项的raw_text值
                    (view_data.get("desc_v2")[0].get("raw_text") if isinstance(view_data.get("desc_v2"), list) and view_data.get("desc_v2") else ""),  # 14. desc_v2
                    view_data.get("state", 0),                 # 15. state
                    view_data.get("duration"),                 # 16. duration
                    view_data.get("mission_id"),               # 17. mission_id
                    view_data.get("dynamic"),                  # 18. dynamic
                    view_data.get("cid"),                      # 19. cid
                    view_data.get("season_id"),                # 20. season_id
                    1 if view_data.get("premiere") else 0,     # 21. premiere
                    view_data.get("teenage_mode", 0),          # 22. teenage_mode
                    1 if view_data.get("is_chargeable_season") else 0,  # 23. is_chargeable_season
                    1 if view_data.get("is_story") else 0,     # 24. is_story
                    1 if view_data.get("is_upower_exclusive") else 0,  # 25. is_upower_exclusive
                    1 if view_data.get("is_upower_play") else 0,  # 26. is_upower_play
                    1 if view_data.get("is_upower_preview") else 0,  # 27. is_upower_preview
                    1 if view_data.get("is_upower_exclusive_with_qa") else 0,  # 30. is_upower_exclusive_with_qa
                    1 if view_data.get("no_cache") else 0,     # 31. no_cache
                    1 if view_data.get("is_season_display") else 0,  # 32. is_season_display
                    view_data.get("like_icon", ""),            # 33. like_icon
                    1 if view_data.get("need_jump_bv") else 0, # 34. need_jump_bv
                    1 if view_data.get("disable_show_up_info") else 0,  # 35. disable_show_up_info
                    view_data.get("is_story_play", 0),         # 36. is_story_play
                    owner.get("mid"),                          # 37. owner_mid
                    owner.get("name"),                         # 38. owner_name
                    owner.get("face"),                         # 39. owner_face
                    stat.get("view", 0),                       # 40. stat_view
                    stat.get("danmaku", 0),                    # 41. stat_danmaku
                    stat.get("reply", 0),                      # 42. stat_reply
                    stat.get("favorite", 0),                   # 43. stat_favorite
                    stat.get("coin", 0),                       # 44. stat_coin
                    stat.get("share", 0),                      # 45. stat_share
                    stat.get("like", 0),                       # 46. stat_like
                    stat.get("dislike", 0),                    # 47. stat_dislike
                    stat.get("his_rank", 0),                   # 48. stat_his_rank
                    stat.get("now_rank", 0),                   # 49. stat_now_rank
                    stat.get("evaluation", ""),                # 50. stat_evaluation
                    dimension.get("width"),                    # 52. dimension_width
                    dimension.get("height"),                   # 53. dimension_height
                    dimension.get("rotate", 0),                # 54. dimension_rotate
                    rights.get("bp", 0),                       # 55. rights_bp
                    rights.get("elec", 0),                     # 56. rights_elec
                    rights.get("download", 0),                 # 57. rights_download
                    rights.get("movie", 0),                    # 58. rights_movie
                    rights.get("pay", 0),                      # 59. rights_pay
                    rights.get("hd5", 0),                      # 60. rights_hd5
                    rights.get("no_reprint", 0),               # 61. rights_no_reprint
                    rights.get("autoplay", 0),                 # 62. rights_autoplay
                    rights.get("ugc_pay", 0),                  # 63. rights_ugc_pay
                    rights.get("is_cooperation", 0),           # 64. rights_is_cooperation
                    rights.get("ugc_pay_preview", 0),          # 65. rights_ugc_pay_preview
                    rights.get("no_background", 0),            # 66. rights_no_background
                    rights.get("clean_mode", 0),               # 67. rights_clean_mode
                    rights.get("is_stein_gate", 0),            # 68. rights_is_stein_gate
                    rights.get("is_360", 0),                   # 69. rights_is_360
                    rights.get("no_share", 0),                 # 70. rights_no_share
                    rights.get("arc_pay", 0),                  # 71. rights_arc_pay
                    rights.get("free_watch", 0),               # 72. rights_free_watch
                    argue_info.get("argue_msg", ""),           # 73. argue_msg
                    argue_info.get("argue_type", 0),           # 74. argue_type
                    argue_info.get("argue_link", ""),          # 75. argue_link
                    now_timestamp,                             # 76. fetch_time
                    now_timestamp                              # 77. update_time
                ]

                # 打印参数数量以便调试
                logger.info(f"实际准备插入的参数数量: {len(insert_params)}")

                # 计算VALUES子句中的问号数量
                values_clause = """(
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,   /* 1-20 */
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,   /* 21-40 */
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,   /* 41-60 */
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?                     /* 61-74 */
                )"""
                question_marks_count = values_clause.count('?')
                logger.info(f"VALUES子句中的问号数量: {question_marks_count}")

                # 确保问号数量和参数数量匹配
                if question_marks_count != len(insert_params):
                    logger.error(f"问号数量({question_marks_count})和参数数量({len(insert_params)})不匹配!")
                    for i, param in enumerate(insert_params):
                        logger.debug(f"参数 {i+1}: {param}")
                    raise ValueError(f"SQL绑定参数不匹配: 需要 {question_marks_count} 个值，但提供了 {len(insert_params)} 个")

                # 检查所有参数的类型，确保它们是SQLite支持的类型
                for i, param in enumerate(insert_params):
                    if isinstance(param, (list, dict)):
                        logger.warning(f"参数 {i+1} 是不支持的类型: {type(param)}, 值: {param}")
                        # 将不支持的类型转换为JSON字符串
                        insert_params[i] = json.dumps(param, ensure_ascii=False)
                        logger.info(f"已将参数 {i+1} 转换为字符串: {insert_params[i]}")

                # 我们已经在上面的代码中处理了所有参数的类型转换，包括desc_v2

                # 确保列和值的数量匹配 - 使用明确的格式确保77个问号
                cursor.execute("""
                INSERT INTO video_base_info (
                    bvid, aid, videos, tid, tid_v2, tname, tname_v2, copyright, pic, title,
                    pubdate, ctime, desc, desc_v2, state, duration, mission_id, dynamic, cid,
                    season_id, premiere, teenage_mode, is_chargeable_season, is_story,
                    is_upower_exclusive, is_upower_play, is_upower_preview,
                    is_upower_exclusive_with_qa, no_cache, is_season_display, like_icon,
                    need_jump_bv, disable_show_up_info, is_story_play, owner_mid, owner_name,
                    owner_face, stat_view, stat_danmaku, stat_reply, stat_favorite, stat_coin,
                    stat_share, stat_like, stat_dislike, stat_his_rank, stat_now_rank,
                    stat_evaluation, dimension_width, dimension_height, dimension_rotate,
                    rights_bp, rights_elec, rights_download, rights_movie, rights_pay, rights_hd5,
                    rights_no_reprint, rights_autoplay, rights_ugc_pay, rights_is_cooperation,
                    rights_ugc_pay_preview, rights_no_background, rights_clean_mode,
                    rights_is_stein_gate, rights_is_360, rights_no_share, rights_arc_pay,
                    rights_free_watch, argue_msg, argue_type, argue_link, fetch_time, update_time
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,   /* 1-20 */
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,   /* 21-40 */
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,   /* 41-60 */
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?                     /* 61-74 */
                )
                """, insert_params)

            # 2. 保存视频分P信息
            # 先删除旧的分P信息
            cursor.execute("DELETE FROM video_pages WHERE bvid = ?", (bvid,))

            # 插入新的分P信息
            pages = view_data.get("pages", [])
            if pages:
                for page in pages:
                    page_dimension = page.get("dimension", {})
                    cursor.execute("""
                    INSERT INTO video_pages (
                        bvid, cid, page, part, duration, from_source, vid, weblink,
                        dimension_width, dimension_height, dimension_rotate, first_frame, ctime
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        bvid,
                        page.get("cid"),
                        page.get("page"),
                        page.get("part"),
                        page.get("duration"),
                        page.get("from"),
                        page.get("vid", ""),
                        page.get("weblink", ""),
                        page_dimension.get("width"),
                        page_dimension.get("height"),
                        page_dimension.get("rotate", 0),
                        page.get("first_frame"),
                        page.get("ctime", 0)
                    ))

            # 3. 保存视频标签信息
            # 先删除旧的标签信息
            cursor.execute("DELETE FROM video_tags WHERE bvid = ?", (bvid,))

            # 插入新的标签信息
            if tags_data:
                for tag in tags_data:
                    cursor.execute("""
                    INSERT INTO video_tags (
                        bvid, tag_id, tag_name, music_id, tag_type, jump_url,
                        cover, content, short_content, type, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        bvid,
                        tag.get("tag_id"),
                        tag.get("tag_name"),
                        tag.get("music_id", ""),
                        tag.get("tag_type", ""),
                        tag.get("jump_url", ""),
                        tag.get("cover"),
                        tag.get("content"),
                        tag.get("short_content"),
                        tag.get("type"),
                        tag.get("state")
                    ))

            # 4. 保存UP主信息
            if card_data and "card" in card_data:
                up_info = card_data["card"]
                mid = up_info.get("mid")
                if mid:
                    # 检查UP主表结构，打印列信息用于调试
                    cursor.execute("PRAGMA table_info(uploader_info)")
                    up_table_columns = cursor.fetchall()
                    up_column_names = [column[1] for column in up_table_columns]
                    logger.info(f"uploader_info表中的列数: {len(up_column_names)}")
                    logger.info(f"uploader_info表的列名: {up_column_names}")

                    # 检查UP主是否已存在
                    cursor.execute("SELECT mid FROM uploader_info WHERE mid = ?", (mid,))
                    existing_up = cursor.fetchone()

                    official = up_info.get("Official", {})
                    level_info = up_info.get("level_info", {})
                    vip = up_info.get("vip", {})
                    pendant = up_info.get("pendant", {})
                    nameplate = up_info.get("nameplate", {})

                    if existing_up:
                        # 更新UP主信息
                        cursor.execute("""
                        UPDATE uploader_info SET
                            name = ?, sex = ?, face = ?, face_nft = ?, face_nft_type = ?,
                            sign = ?, rank = ?, level = ?, regtime = ?, spacesta = ?,
                            birthday = ?, place = ?, description = ?, article = ?,
                            fans = ?, friend = ?, attention = ?,
                            official_role = ?, official_title = ?, official_desc = ?, official_type = ?,
                            vip_type = ?, vip_status = ?, vip_due_date = ?, vip_pay_type = ?,
                            vip_theme_type = ?, vip_avatar_subscript = ?,
                            vip_nickname_color = ?, vip_role = ?, vip_avatar_subscript_url = ?,
                            pendant_pid = ?, pendant_name = ?, pendant_image = ?, pendant_expire = ?,
                            nameplate_nid = ?, nameplate_name = ?, nameplate_image = ?,
                            nameplate_image_small = ?, nameplate_level = ?, nameplate_condition = ?,
                            is_senior_member = ?,
                            following = ?, archive_count = ?, article_count = ?, like_num = ?,
                            update_time = ?
                        WHERE mid = ?
                        """, (
                            up_info.get("name"),
                            up_info.get("sex"),
                            up_info.get("face"),
                            up_info.get("face_nft", 0),
                            up_info.get("face_nft_type", 0),
                            up_info.get("sign"),
                            up_info.get("rank"),
                            level_info.get("current_level", 0),
                            up_info.get("regtime", 0),
                            up_info.get("spacesta", 0),
                            up_info.get("birthday", ""),
                            up_info.get("place", ""),
                            up_info.get("description", ""),
                            up_info.get("article", 0),
                            up_info.get("fans", 0),
                            up_info.get("friend", 0),
                            up_info.get("attention", 0),
                            official.get("role", 0),
                            official.get("title", ""),
                            official.get("desc", ""),
                            official.get("type", 0),
                            vip.get("type", 0),
                            vip.get("status", 0),
                            vip.get("due_date", 0),
                            vip.get("vip_pay_type", 0),
                            vip.get("theme_type", 0),
                            vip.get("avatar_subscript", 0),
                            vip.get("nickname_color", ""),
                            vip.get("role", 0),
                            vip.get("avatar_subscript_url", ""),
                            pendant.get("pid", 0),
                            pendant.get("name", ""),
                            pendant.get("image", ""),
                            pendant.get("expire", 0),
                            nameplate.get("nid", 0),
                            nameplate.get("name", ""),
                            nameplate.get("image", ""),
                            nameplate.get("image_small", ""),
                            nameplate.get("level", ""),
                            nameplate.get("condition", ""),
                            up_info.get("is_senior_member", 0),
                            card_data.get("following", 0),
                            card_data.get("archive_count", 0),
                            card_data.get("article_count", 0),
                            card_data.get("like_num", 0),
                            now_timestamp,
                            mid
                        ))
                    else:
                        # 创建插入参数列表，便于调试
                        uploader_params = [
                            mid,                                       # 1. mid
                            up_info.get("name"),                       # 2. name
                            up_info.get("sex"),                        # 3. sex
                            up_info.get("face"),                       # 4. face
                            up_info.get("face_nft", 0),                # 5. face_nft
                            up_info.get("face_nft_type", 0),           # 6. face_nft_type
                            up_info.get("sign"),                       # 7. sign
                            up_info.get("rank"),                       # 8. rank
                            level_info.get("current_level", 0),        # 9. level
                            up_info.get("regtime", 0),                 # 10. regtime
                            up_info.get("spacesta", 0),                # 11. spacesta
                            up_info.get("birthday", ""),               # 12. birthday
                            up_info.get("place", ""),                  # 13. place
                            up_info.get("description", ""),            # 14. description
                            up_info.get("article", 0),                 # 15. article
                            up_info.get("fans", 0),                    # 16. fans
                            up_info.get("friend", 0),                  # 17. friend
                            up_info.get("attention", 0),               # 18. attention
                            official.get("role", 0),                   # 19. official_role
                            official.get("title", ""),                 # 20. official_title
                            official.get("desc", ""),                  # 21. official_desc
                            official.get("type", 0),                   # 22. official_type
                            vip.get("type", 0),                        # 23. vip_type
                            vip.get("status", 0),                      # 24. vip_status
                            vip.get("due_date", 0),                    # 25. vip_due_date
                            vip.get("vip_pay_type", 0),                # 26. vip_pay_type
                            vip.get("theme_type", 0),                  # 27. vip_theme_type
                            vip.get("avatar_subscript", 0),            # 28. vip_avatar_subscript
                            vip.get("nickname_color", ""),             # 29. vip_nickname_color
                            vip.get("role", 0),                        # 30. vip_role
                            vip.get("avatar_subscript_url", ""),       # 31. vip_avatar_subscript_url
                            pendant.get("pid", 0),                     # 32. pendant_pid
                            pendant.get("name", ""),                   # 33. pendant_name
                            pendant.get("image", ""),                  # 34. pendant_image
                            pendant.get("expire", 0),                  # 35. pendant_expire
                            nameplate.get("nid", 0),                   # 36. nameplate_nid
                            nameplate.get("name", ""),                 # 37. nameplate_name
                            nameplate.get("image", ""),                # 38. nameplate_image
                            nameplate.get("image_small", ""),          # 39. nameplate_image_small
                            nameplate.get("level", ""),                # 40. nameplate_level
                            nameplate.get("condition", ""),            # 41. nameplate_condition
                            up_info.get("is_senior_member", 0),        # 42. is_senior_member
                            card_data.get("following", 0),             # 43. following
                            card_data.get("archive_count", 0),         # 44. archive_count
                            card_data.get("article_count", 0),         # 45. article_count
                            card_data.get("like_num", 0),              # 46. like_num
                            now_timestamp,                             # 47. fetch_time
                            now_timestamp                              # 48. update_time
                        ]

                        # 打印参数数量和列数量
                        logger.info(f"准备插入的UP主参数数量: {len(uploader_params)}")

                        # 确保参数数量和问号一致
                        # 插入新的UP主信息
                        cursor.execute("""
                        INSERT INTO uploader_info (
                            mid, name, sex, face, face_nft, face_nft_type,
                            sign, rank, level, regtime, spacesta,
                            birthday, place, description, article,
                            fans, friend, attention,
                            official_role, official_title, official_desc, official_type,
                            vip_type, vip_status, vip_due_date, vip_pay_type,
                            vip_theme_type, vip_avatar_subscript,
                            vip_nickname_color, vip_role, vip_avatar_subscript_url,
                            pendant_pid, pendant_name, pendant_image, pendant_expire,
                            nameplate_nid, nameplate_name, nameplate_image,
                            nameplate_image_small, nameplate_level, nameplate_condition,
                            is_senior_member,
                            following, archive_count, article_count, like_num,
                            fetch_time, update_time
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,  /* 1-10 */
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,  /* 11-20 */
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,  /* 21-30 */
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,  /* 31-40 */
                            ?, ?, ?, ?, ?, ?, ?, ?         /* 41-48 */
                        )
                        """, uploader_params)

            # 5. 保存视频荣誉信息
            if honor_reply_data:
                # 先删除旧的荣誉信息
                cursor.execute("DELETE FROM video_honors WHERE bvid = ?", (bvid,))

                # 插入新的荣誉信息
                for honor in honor_reply_data:
                    cursor.execute("""
                    INSERT INTO video_honors (
                        bvid, aid, type, desc, weekly_recommend_num
                    ) VALUES (?, ?, ?, ?, ?)
                    """, (
                        bvid,
                        honor.get("aid", view_data.get("aid")),
                        honor.get("type", 0),
                        honor.get("desc", ""),
                        honor.get("weekly_recommend_num", 0)
                    ))

            # 6. 保存视频字幕信息
            if subtitle_data:
                # 先删除旧的字幕信息
                cursor.execute("DELETE FROM video_subtitles WHERE bvid = ?", (bvid,))

                # 插入字幕允许提交状态
                allow_submit = 1 if subtitle_data.get("allow_submit") else 0

                # 插入字幕列表
                subtitle_list = subtitle_data.get("list", [])
                if subtitle_list:
                    for subtitle in subtitle_list:
                        cursor.execute("""
                        INSERT INTO video_subtitles (
                            bvid, allow_submit, subtitle_id, lan, lan_doc, is_lock, subtitle_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            bvid,
                            allow_submit,
                            subtitle.get("id", 0),
                            subtitle.get("lan", ""),
                            subtitle.get("lan_doc", ""),
                            1 if subtitle.get("is_lock") else 0,
                            subtitle.get("subtitle_url", "")
                        ))
                else:
                    # 如果没有字幕，但有allow_submit信息，也插入一条记录
                    cursor.execute("""
                    INSERT INTO video_subtitles (
                        bvid, allow_submit, subtitle_id, lan, lan_doc, is_lock, subtitle_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        bvid,
                        allow_submit,
                        0,
                        "",
                        "",
                        0,
                        ""
                    ))

            # 7. 保存相关视频信息
            if related_data:
                # 先删除旧的相关视频信息
                cursor.execute("DELETE FROM related_videos WHERE bvid = ?", (bvid,))

                # 插入新的相关视频信息
                for related in related_data:
                    related_owner = related.get("owner", {})
                    cursor.execute("""
                    INSERT INTO related_videos (
                        bvid, related_bvid, related_aid, related_title, related_pic,
                        related_owner_mid, related_owner_name, related_owner_face
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        bvid,
                        related.get("bvid", ""),
                        related.get("aid", 0),
                        related.get("title", ""),
                        related.get("pic", ""),
                        related_owner.get("mid", 0),
                        related_owner.get("name", ""),
                        related_owner.get("face", "")
                    ))

            conn.commit()

        logger.info(f"已保存视频 {bvid} 的超详细信息到数据库")

    except sqlite3.Error as e:
        logger.error(f"保存视频详情到数据库时出错: {e}")
        logger.debug(f"视频详情数据: {json.dumps(data, ensure_ascii=False)}")
        raise


@router.get("/fetch/{bvid}", summary="获取单个视频详情")
async def fetch_video_detail(bvid: str):
    """获取并保存视频超详细信息"""
    try:
        logger.info(f"开始获取视频 {bvid} 的超详细信息")
        # 已知失效预检查，避免重复请求
        try:
            create_invalid_videos_table()
        except Exception:
            pass
        invalid_info = check_invalid_video(bvid)
        if invalid_info.get("is_invalid"):
            logger.info(f"视频 {bvid} 已知失效(type={invalid_info.get('error_type')}), 跳过请求")
            return {
                "status": "skipped",
                "message": f"视频 {bvid} 已知失效，已跳过",
                "data": {"bvid": bvid, "error_type": invalid_info.get("error_type")}
            }
        data = await get_video_detail(bvid)
        logger.info(f"成功获取视频 {bvid} 的API响应，准备保存到数据库")

        # 检查关键数据是否存在
        view_data = data.get("data", {}).get("View", {})
        if not view_data:
            logger.error(f"视频 {bvid} 的View数据不存在: {json.dumps(data, ensure_ascii=False)[:500]}")
            raise HTTPException(status_code=400, detail=f"视频 {bvid} 的详情数据不完整")

        # 检查权限数据是否存在
        rights = view_data.get("rights", {})
        if not rights:
            logger.warning(f"视频 {bvid} 的rights数据不存在，将使用空字典")

        # 打印权限字段列表，确认完整性
        logger.info(f"视频 {bvid} 的rights字段: {list(rights.keys())}")

        # 打印统计字段列表
        stat = view_data.get("stat", {})
        logger.info(f"视频 {bvid} 的stat字段: {list(stat.keys())}")

        save_video_detail_to_db(data)
        logger.info(f"成功保存视频 {bvid} 的超详细信息到数据库")
        return {"status": "success", "message": f"成功获取并保存视频 {bvid} 的超详细信息"}
    except Exception as e:
        logger.exception(f"处理视频详情时出错: {e}")
        # 打印详细的错误堆栈
        import traceback
        error_stack = traceback.format_exc()
        logger.error(f"错误堆栈: {error_stack}")
        raise HTTPException(status_code=500, detail=f"处理视频详情时出错: {str(e)}")


@router.get("/info/{bvid}", summary="从数据库获取视频信息")
async def get_video_info_from_db(bvid: str):
    """从数据库获取视频信息"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 获取视频基本信息
            cursor.execute("""
            SELECT * FROM video_base_info WHERE bvid = ?
            """, (bvid,))
            video_info = cursor.fetchone()

            if not video_info:
                raise HTTPException(status_code=404, detail=f"未找到视频 {bvid} 的信息")

            # 转换为字典
            video_info_dict = dict(video_info)
            video_info_dict["original_url"] = _build_video_original_url(video_info_dict)

            # 获取视频分P信息
            cursor.execute("""
            SELECT * FROM video_pages WHERE bvid = ? ORDER BY page
            """, (bvid,))
            pages = [dict(page) for page in cursor.fetchall()]
            video_info_dict["pages"] = pages

            # 获取视频标签信息
            cursor.execute("""
            SELECT * FROM video_tags WHERE bvid = ?
            """, (bvid,))
            tags = [dict(tag) for tag in cursor.fetchall()]
            video_info_dict["tags"] = tags

            # 获取UP主信息
            if "owner_mid" in video_info_dict and video_info_dict["owner_mid"]:
                cursor.execute("""
                SELECT * FROM uploader_info WHERE mid = ?
                """, (video_info_dict["owner_mid"],))
                up_info = cursor.fetchone()
                if up_info:
                    video_info_dict["owner_info"] = dict(up_info)

            # 获取视频荣誉信息
            cursor.execute("""
            SELECT * FROM video_honors WHERE bvid = ?
            """, (bvid,))
            honors = [dict(honor) for honor in cursor.fetchall()]
            if honors:
                video_info_dict["honors"] = honors

            # 获取视频字幕信息
            cursor.execute("""
            SELECT * FROM video_subtitles WHERE bvid = ?
            """, (bvid,))
            subtitles = [dict(subtitle) for subtitle in cursor.fetchall()]
            if subtitles:
                video_info_dict["subtitles"] = subtitles

            # 获取相关视频信息
            cursor.execute("""
            SELECT * FROM related_videos WHERE bvid = ?
            """, (bvid,))
            related_videos = [dict(related) for related in cursor.fetchall()]
            if related_videos:
                video_info_dict["related_videos"] = related_videos

            return video_info_dict
    except sqlite3.Error as e:
        logger.exception(f"从数据库获取视频信息时出错: {e}")
        raise HTTPException(status_code=500, detail=f"从数据库获取视频信息时出错: {str(e)}")


@router.get("/search", summary="搜索视频")
async def search_videos(
    keyword: str = Query(None, description="关键词"),
    uploader_mid: int = Query(None, description="UP主ID"),
    page: int = Query(1, description="页码"),
    per_page: int = Query(20, description="每页数量")
):
    """搜索视频"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            params = []
            where_clauses = []

            if keyword:
                where_clauses.append("(title LIKE ? OR desc LIKE ?)")
                keyword_pattern = f"%{keyword}%"
                params.extend([keyword_pattern, keyword_pattern])

            if uploader_mid:
                where_clauses.append("owner_mid = ?")
                params.append(uploader_mid)

            # 构建WHERE子句
            where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

            # 计算总数
            cursor.execute(f"SELECT COUNT(*) as total FROM video_base_info WHERE {where_clause}", params)
            total = cursor.fetchone()["total"]

            # 查询数据
            offset = (page - 1) * per_page
            query = f"""
            SELECT * FROM video_base_info
            WHERE {where_clause}
            ORDER BY pubdate DESC
            LIMIT ? OFFSET ?
            """
            params.extend([per_page, offset])

            cursor.execute(query, params)
            videos = []
            for video in cursor.fetchall():
                video_dict = dict(video)
                video_dict["original_url"] = _build_video_original_url(video_dict)
                videos.append(video_dict)

            return {
                "total": total,
                "page": page,
                "per_page": per_page,
                "videos": videos
            }
    except sqlite3.Error as e:
        logger.exception(f"搜索视频时出错: {e}")
        raise HTTPException(status_code=500, detail=f"搜索视频时出错: {str(e)}")


@router.post("/batch_fetch", summary="批量获取视频详情")
async def batch_fetch_video_details(bvids: List[str]):
    """批量获取多个视频的超详细信息"""
    results = []
    errors = []

    for bvid in bvids:
        try:
            data = await get_video_detail(bvid)
            save_video_detail_to_db(data)
            results.append({"bvid": bvid, "status": "success"})
        except Exception as e:
            logger.error(f"处理视频 {bvid} 详情时出错: {e}")
            errors.append({"bvid": bvid, "error": str(e)})

    return {
        "success_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors
    }


@router.get("/batch_fetch_from_history", summary="从历史记录批量获取视频详情")
async def batch_fetch_video_details_from_history(
    background_tasks: BackgroundTasks,
    max_videos: int = Query(100, description="本次最多处理的视频数量，0表示不限制"),
    specific_videos: Optional[str] = Query(None, description="要获取的特定视频ID列表，用逗号分隔"),
    use_sessdata: bool = Query(True, description="是否使用SESSDATA获取详情，某些视频需要登录才能查看"),
    batch_size: int = Query(20, description="批次大小，每批处理的视频数量")
):
    """从历史记录中获取视频ID，批量获取视频超详细信息"""
    try:
        # 获取数据库路径
        db_path = os.path.join("output", "bilibili_history.db")

        if not os.path.exists(db_path):
            raise HTTPException(status_code=404, detail="历史记录数据库不存在，请先获取历史记录")

        # 连接数据库获取视频列表
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # 获取所有历史记录表名
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'bilibili_history_%'
            """)
            table_names = [row[0] for row in cursor.fetchall()]

            if not table_names:
                raise HTTPException(status_code=404, detail="未找到任何历史记录表")

            if specific_videos:
                # 处理特定视频列表
                video_list = [v.strip() for v in specific_videos.split(',') if v.strip()]
                if not video_list:
                    raise HTTPException(status_code=400, detail="特定视频列表为空")

                # 验证这些视频是否在历史记录中
                placeholders = ','.join(['?' for _ in video_list])
                union_queries = []
                for table_name in table_names:
                    union_queries.append(f"SELECT DISTINCT bvid FROM {table_name} WHERE bvid IN ({placeholders}) AND bvid IS NOT NULL AND bvid != ''")

                if union_queries:
                    union_query = " UNION ".join(union_queries)
                    # 为每个表的查询准备参数
                    all_params = video_list * len(table_names)
                    cursor.execute(union_query, all_params)

            else:
                # 获取所有历史记录中的视频
                union_queries = []
                for table_name in table_names:
                    if max_videos > 0:
                        union_queries.append(f"SELECT DISTINCT bvid, view_at FROM {table_name} WHERE bvid IS NOT NULL AND bvid != ''")
                    else:
                        union_queries.append(f"SELECT DISTINCT bvid, view_at FROM {table_name} WHERE bvid IS NOT NULL AND bvid != ''")

                if union_queries:
                    union_query = " UNION ".join(union_queries)
                    final_query = f"SELECT DISTINCT bvid FROM ({union_query}) ORDER BY view_at DESC"
                    if max_videos > 0:
                        final_query += f" LIMIT {max_videos}"
                    cursor.execute(final_query)

            video_rows = cursor.fetchall()
            all_video_list = [row[0] for row in video_rows]

            if not all_video_list:
                return {
                    "status": "success",
                    "message": "没有找到需要获取详情的视频",
                    "data": {
                        "total_videos": 0,
                        "success_count": 0,
                        "error_count": 0,
                        "results": [],
                        "errors": []
                    }
                }

        # 过滤掉已存在的视频和已知失效的视频，只获取需要处理的视频
        video_list = []
        existing_count = 0
        invalid_known_count = 0

        # 确保失效视频表存在
        try:
            create_invalid_videos_table()
        except Exception as _:
            pass

        if os.path.exists(DB_PATH):
            with sqlite3.connect(DB_PATH) as details_conn:
                details_cursor = details_conn.cursor()

                for bvid in all_video_list:
                    # 检查视频是否已存在于详情数据库
                    details_cursor.execute("SELECT 1 FROM video_base_info WHERE bvid = ? LIMIT 1", (bvid,))
                    if details_cursor.fetchone() is not None:
                        existing_count += 1
                        continue

                    # 检查是否为已知失效视频（保存在 video_library.db 的 invalid_videos 表）
                    invalid_info = check_invalid_video(bvid)
                    if invalid_info.get("is_invalid"):
                        invalid_known_count += 1
                        continue

                    video_list.append(bvid)
        else:
            # 如果详情数据库不存在，则过滤掉已知失效视频
            for bvid in all_video_list:
                invalid_info = check_invalid_video(bvid)
                if invalid_info.get("is_invalid"):
                    invalid_known_count += 1
                    continue
                video_list.append(bvid)

        logger.info(
            f"历史记录中共有 {len(all_video_list)} 个视频，已存在: {existing_count} 个，已知失效: {invalid_known_count} 个，需要获取: {len(video_list)} 个"
        )

        if not video_list:
            return {
                "status": "success",
                "message": (
                    f"所有视频详情都已存在或已知失效，无需重复获取。"
                    f"历史记录总数: {len(all_video_list)}，已存在: {existing_count}，已知失效: {invalid_known_count}"
                ),
                "data": {
                    "total_videos": 0,
                    "success_count": 0,
                    "error_count": 0,
                    "results": [],
                    "errors": [],
                    "existing_count": existing_count,
                    "invalid_known_count": invalid_known_count,
                    "total_history_videos": len(all_video_list)
                }
            }

        # 检查是否已有任务在运行
        if video_details_progress["is_processing"]:
            raise HTTPException(status_code=400, detail="已有视频详情获取任务在运行中")

        # 重置并初始化进度状态
        reset_video_details_progress()
        video_details_progress.update({
            "is_processing": True,
            "total_videos": len(video_list),
            "start_time": time.time(),
            "last_update_time": time.time()
        })

        # 使用后台任务异步执行详情获取
        background_tasks.add_task(
            fetch_video_details_background_task,
            video_list,
            batch_size,
            use_sessdata
        )

        # 立即返回响应，让用户看到任务已启动
        return {
            "status": "success",
            "message": (
                f"视频详情获取已在后台启动。历史记录总数: {len(all_video_list)}，"
                f"已存在: {existing_count}，已知失效: {invalid_known_count}，需要获取: {len(video_list)}"
            ),
            "data": {
                "is_processing": True,
                "total_videos": len(video_list),
                "processed_videos": 0,
                "success_count": 0,
                "failed_count": 0,
                "progress_percentage": 0,
                "elapsed_time": "0.00秒",
                "existing_count": existing_count,
                "invalid_known_count": invalid_known_count,
                "total_history_videos": len(all_video_list)
            }
        }

    except Exception as e:
        logger.error(f"批量获取视频详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量获取视频详情失败: {str(e)}")


@router.get("/stats", summary="获取视频详情统计信息")
async def get_video_details_database_stats():
    """获取视频详情数据库统计信息"""
    try:
        # 确保数据库已初始化
        init_db()
        # 获取历史记录数据库路径
        history_db_path = os.path.join("output", "bilibili_history.db")
        # 获取视频详情数据库路径
        details_db_path = DB_PATH

        if not os.path.exists(history_db_path):
            raise HTTPException(status_code=404, detail="历史记录数据库不存在")

        stats = {}

        # 连接历史记录数据库
        with sqlite3.connect(history_db_path) as history_conn:
            history_cursor = history_conn.cursor()

            # 获取所有历史记录表名
            history_cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'bilibili_history_%'
            """)
            table_names = [row[0] for row in history_cursor.fetchall()]

            total_videos = 0
            if table_names:
                # 构建联合查询来获取所有年份的视频总数
                union_queries = []
                for table_name in table_names:
                    union_queries.append(f"SELECT DISTINCT bvid FROM {table_name} WHERE bvid IS NOT NULL AND bvid != ''")

                if union_queries:
                    union_query = " UNION ".join(union_queries)
                    final_query = f"SELECT COUNT(*) FROM ({union_query})"
                    history_cursor.execute(final_query)
                    total_videos = history_cursor.fetchone()[0]

            stats["total_videos"] = total_videos

        # 如果视频详情数据库存在，获取详情统计
        if os.path.exists(details_db_path):
            with sqlite3.connect(details_db_path) as details_conn:
                details_cursor = details_conn.cursor()

                try:
                    # 获取已获取详情的视频数
                    details_cursor.execute("SELECT COUNT(DISTINCT bvid) FROM video_base_info")
                    videos_with_details = details_cursor.fetchone()[0]
                    stats["videos_with_details"] = videos_with_details

                    # 获取UP主信息数量
                    details_cursor.execute("SELECT COUNT(*) FROM uploader_info")
                    uploader_count = details_cursor.fetchone()[0]
                    stats["uploader_count"] = uploader_count

                    # 获取视频标签数量
                    details_cursor.execute("SELECT COUNT(*) FROM video_tags")
                    tag_count = details_cursor.fetchone()[0]
                    stats["tag_count"] = tag_count

                    # 获取视频分P数量
                    details_cursor.execute("SELECT COUNT(*) FROM video_pages")
                    page_count = details_cursor.fetchone()[0]
                    stats["page_count"] = page_count
                except sqlite3.OperationalError as e:
                    # 如果表不存在，设置为0
                    logger.warning(f"视频详情数据库表不存在: {e}")
                    stats["videos_with_details"] = 0
                    stats["uploader_count"] = 0
                    stats["tag_count"] = 0
                    stats["page_count"] = 0

        else:
            stats["videos_with_details"] = 0
            stats["uploader_count"] = 0
            stats["tag_count"] = 0
            stats["page_count"] = 0

        # 重新统计：区分失效与待获取（排除失效）
        try:
            create_invalid_videos_table()
        except Exception:
            pass

        # 收集历史记录中的全部 bvid
        history_bvids: set = set()
        with sqlite3.connect(history_db_path) as history_conn2:
            history_cursor2 = history_conn2.cursor()
            history_cursor2.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'bilibili_history_%'
            """)
            table_names2 = [row[0] for row in history_cursor2.fetchall()]
            if table_names2:
                union_query2 = " UNION ".join(
                    [f"SELECT DISTINCT bvid FROM {t} WHERE bvid IS NOT NULL AND bvid != ''" for t in table_names2]
                )
                history_cursor2.execute(union_query2)
                history_bvids = {row[0] for row in history_cursor2.fetchall()}

        # 已有详情的视频集合
        details_bvids: set = set()
        if os.path.exists(details_db_path):
            with sqlite3.connect(details_db_path) as details_conn2:
                details_cursor2 = details_conn2.cursor()
                try:
                    details_cursor2.execute("SELECT DISTINCT bvid FROM video_base_info")
                    details_bvids = {row[0] for row in details_cursor2.fetchall()}
                except sqlite3.OperationalError:
                    details_bvids = set()

        # 已知失效的视频集合（来自 video_library.db/invalid_videos）
        invalid_bvids: set = set()
        error_type_stats = {}
        invalid_db_path = get_output_path("video_library.db")
        if os.path.exists(invalid_db_path):
            with sqlite3.connect(invalid_db_path) as inv_conn:
                inv_cursor = inv_conn.cursor()
                try:
                    inv_cursor.execute("SELECT DISTINCT bvid FROM invalid_videos")
                    invalid_all = {row[0] for row in inv_cursor.fetchall()}
                    invalid_bvids = invalid_all & history_bvids

                    if invalid_bvids:
                        placeholders = ",".join(["?"] * len(invalid_bvids))
                        inv_cursor.execute(
                            f"SELECT error_type, COUNT(*) FROM invalid_videos WHERE bvid IN ({placeholders}) GROUP BY error_type",
                            tuple(invalid_bvids)
                        )
                        error_type_stats = {row[0]: row[1] for row in inv_cursor.fetchall()}
                except sqlite3.OperationalError:
                    invalid_bvids = set()

        # 精确计数（仅针对历史记录中的视频）
        videos_with_details_exact = len(details_bvids & history_bvids)
        stats["videos_with_details"] = videos_with_details_exact

        invalid_videos_count = len(invalid_bvids)
        stats["invalid_videos_count"] = invalid_videos_count

        pending_videos_count = max(stats["total_videos"] - videos_with_details_exact - invalid_videos_count, 0)
        stats["pending_videos_count"] = pending_videos_count

        # 将 videos_without_details 调整为“未获取且非失效”的真实待获取数
        stats["videos_without_details"] = pending_videos_count

        # 计算两种完成百分比
        if stats["total_videos"] > 0:
            stats["completion_percentage"] = round((videos_with_details_exact / stats["total_videos"]) * 100, 2)
            stats["overall_completion_percentage"] = round(((videos_with_details_exact + invalid_videos_count) / stats["total_videos"]) * 100, 2)
        else:
            stats["completion_percentage"] = 0
            stats["overall_completion_percentage"] = 0

        if error_type_stats:
            stats["invalid_error_type_stats"] = error_type_stats

        return {
            "status": "success",
            "message": "成功获取视频详情统计数据",
            "data": stats
        }

    except Exception as e:
        logger.error(f"获取视频详情统计数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计数据失败: {str(e)}")


@router.get("/database_stats", summary="获取数据库详细统计")
async def get_database_stats():
    """获取数据库统计信息"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 获取视频总数
            cursor.execute("SELECT COUNT(*) as total FROM video_base_info")
            total_videos = cursor.fetchone()["total"]

            # 获取UP主总数
            cursor.execute("SELECT COUNT(*) as total FROM uploader_info")
            total_uploaders = cursor.fetchone()["total"]

            # 获取标签总数
            cursor.execute("SELECT COUNT(DISTINCT tag_id) as total FROM video_tags")
            total_tags = cursor.fetchone()["total"]

            # 获取最近添加的10个视频
            cursor.execute("""
            SELECT bvid, title, owner_name, fetch_time
            FROM video_base_info
            ORDER BY fetch_time DESC
            LIMIT 10
            """)
            recent_videos = [dict(video) for video in cursor.fetchall()]

            return {
                "total_videos": total_videos,
                "total_uploaders": total_uploaders,
                "total_tags": total_tags,
                "recent_videos": recent_videos,
                "database_path": DB_PATH
            }
    except sqlite3.Error as e:
        logger.exception(f"获取数据库统计信息时出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取数据库统计信息时出错: {str(e)}")


@router.get("/uploaders", summary="获取UP主列表")
async def list_uploaders(
    page: int = Query(1, description="页码"),
    per_page: int = Query(20, description="每页数量"),
    order_by: str = Query("fans", description="排序字段")
):
    """获取UP主列表"""
    valid_order_fields = ["mid", "name", "fans", "archive_count", "like_num", "fetch_time"]
    if order_by not in valid_order_fields:
        order_by = "fans"

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 计算总数
            cursor.execute("SELECT COUNT(*) as total FROM uploader_info")
            total = cursor.fetchone()["total"]

            # 查询数据
            offset = (page - 1) * per_page
            query = f"""
            SELECT * FROM uploader_info
            ORDER BY {order_by} DESC
            LIMIT ? OFFSET ?
            """

            cursor.execute(query, (per_page, offset))
            uploaders = [dict(uploader) for uploader in cursor.fetchall()]

            return {
                "total": total,
                "page": page,
                "per_page": per_page,
                "uploaders": uploaders
            }
    except sqlite3.Error as e:
        logger.exception(f"获取UP主列表时出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取UP主列表时出错: {str(e)}")


@router.get("/tags", summary="获取视频标签列表")
async def list_tags(
    page: int = Query(1, description="页码"),
    per_page: int = Query(100, description="每页数量")
):
    """获取标签列表"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 计算总数
            cursor.execute("SELECT COUNT(DISTINCT tag_id) as total FROM video_tags")
            total = cursor.fetchone()["total"]

            # 查询数据
            offset = (page - 1) * per_page
            query = """
            SELECT tag_id, tag_name, COUNT(*) as video_count
            FROM video_tags
            GROUP BY tag_id, tag_name
            ORDER BY video_count DESC
            LIMIT ? OFFSET ?
            """

            cursor.execute(query, (per_page, offset))
            tags = [dict(tag) for tag in cursor.fetchall()]

            return {
                "total": total,
                "page": page,
                "per_page": per_page,
                "tags": tags
            }
    except sqlite3.Error as e:
        logger.exception(f"获取标签列表时出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取标签列表时出错: {str(e)}")


@router.get("/uploader/{mid}", summary="获取UP主详细信息")
async def get_uploader_details(mid: int):
    """获取UP主详细信息及其视频列表"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 获取UP主基本信息
            cursor.execute("SELECT * FROM uploader_info WHERE mid = ?", (mid,))
            uploader = cursor.fetchone()

            if not uploader:
                raise HTTPException(status_code=404, detail=f"未找到UP主 {mid} 的信息")

            uploader_dict = dict(uploader)

            # 获取UP主的视频列表
            cursor.execute("""
            SELECT * FROM video_base_info WHERE owner_mid = ? ORDER BY pubdate DESC LIMIT 50
            """, (mid,))
            videos = [dict(video) for video in cursor.fetchall()]
            uploader_dict["videos"] = videos

            return uploader_dict
    except sqlite3.Error as e:
        logger.exception(f"获取UP主 {mid} 详情时出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取UP主详情时出错: {str(e)}")


async def fetch_video_details_background_task(video_list: List[str], batch_size: int, use_sessdata: bool):
    """后台任务：批量获取视频详情，支持秒级进度更新和停止功能"""
    try:
        logger.info(f"开始后台批量获取 {len(video_list)} 个视频的超详细信息")

        # 初始化数据库（确保表结构存在）和失效视频表
        try:
            init_db()
            logger.info("数据库初始化完成")
            # 确保失效视频表准备就绪（位于 video_library.db）
            try:
                create_invalid_videos_table()
                logger.info("失效视频表已准备就绪")
            except Exception as ie:
                logger.warning(f"初始化失效视频表失败: {ie}")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise

        # 随机打乱视频顺序，避免按顺序请求被检测
        random.shuffle(video_list)

        # 降低并发线程数，避免过高并发导致412错误
        max_workers = min(8, batch_size)  # 进一步降低并发数

        # 获取配置和cookie
        config = load_config()
        cookies = config.get("cookies", {})
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()]) if cookies else ""
        cookie_to_use = cookie_str if use_sessdata else ""

        # 分批处理视频，每批之间有延迟
        total_videos = len(video_list)

        # 按批次处理视频
        for i in range(0, total_videos, batch_size):
            batch_videos = video_list[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_videos + batch_size - 1) // batch_size

            logger.info(f"开始处理第 {batch_num}/{total_batches} 批，包含 {len(batch_videos)} 个视频")

            # 检查是否被用户停止
            if video_details_progress["is_stopped"]:
                logger.info("用户停止了视频详情获取任务")
                break

            # 使用线程池处理当前批次的视频
            # 先过滤已知失效视频，避免无效请求
            work_bvids = []
            for b in batch_videos:
                inv = check_invalid_video(b)
                if inv.get("is_invalid"):
                    logger.info(f"已知失效视频，跳过: {b} ({inv.get('error_type')})")
                    video_details_progress["skipped_invalid_count"] += 1
                    video_details_progress["processed_videos"] += 1
                    video_details_progress["last_update_time"] = time.time()
                else:
                    work_bvids.append(b)

            if not work_bvids:
                logger.info(f"第 {batch_num} 批全部为已知失效视频，跳过执行")
                continue

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交当前批次的任务（过滤后的列表）
                future_to_bvid = {
                    executor.submit(get_video_detail_sync, bvid, cookie_to_use, use_sessdata): bvid
                    for bvid in work_bvids
                }

                # 逐个处理完成的任务，实现秒级更新
                for future in concurrent.futures.as_completed(future_to_bvid):
                    # 检查是否被用户停止
                    if video_details_progress["is_stopped"]:
                        logger.info("用户停止了视频详情获取任务")
                        # 取消剩余的任务
                        for remaining_future in future_to_bvid:
                            if not remaining_future.done():
                                remaining_future.cancel()
                        break

                    bvid = future_to_bvid[future]
                    try:
                        # 在处理前再次检查是否已存在（防止并发情况下的重复）
                        with sqlite3.connect(DB_PATH) as check_conn:
                            check_cursor = check_conn.cursor()
                            check_cursor.execute("SELECT 1 FROM video_base_info WHERE bvid = ? LIMIT 1", (bvid,))
                            if check_cursor.fetchone() is not None:
                                logger.info(f"视频 {bvid} 已存在于数据库中，跳过")
                                video_details_progress["skipped_invalid_count"] += 1
                                video_details_progress["processed_videos"] += 1
                                video_details_progress["last_update_time"] = time.time()
                                continue

                        result = future.result()
                        if result and result.get("code") == 0:
                            # 保存到数据库
                            try:
                                save_video_detail_to_db(result)
                                video_details_progress["success_count"] += 1
                                logger.info(f"成功获取并保存视频 {bvid} 的详情")
                            except Exception as e:
                                logger.error(f"保存视频 {bvid} 详情到数据库失败: {e}")
                                video_details_progress["failed_count"] += 1
                                video_details_progress["error_videos"].append(bvid)
                        else:
                            video_details_progress["failed_count"] += 1
                            video_details_progress["error_videos"].append(bvid)
                            error_msg = result.get("message", "未知错误") if result else "请求失败"
                            logger.warning(f"获取视频 {bvid} 详情失败: {error_msg}")
                            # 对永久性错误进行失效标记，避免下次重复获取
                            try:
                                code = result.get("code") if result else None
                                if code in (-404, 62002):
                                    err_type = "not_found" if code == -404 else "invisible"
                                    err_obj = type("ErrorResponse", (), {
                                        "status": "error",
                                        "message": error_msg,
                                        "data": None,
                                        "bvid": bvid,
                                        "error_type": err_type,
                                        "error_code": code,
                                        "raw_response": result
                                    })
                                    save_invalid_video(err_obj)
                                    logger.info(f"已记录失效视频 {bvid} 到 invalid_videos，类型: {err_type}")
                            except Exception as se:
                                logger.warning(f"记录失效视频 {bvid} 时异常: {se}")
                    except Exception as e:
                        logger.error(f"获取视频 {bvid} 详情失败: {e}")
                        video_details_progress["failed_count"] += 1
                        video_details_progress["error_videos"].append(bvid)

                    # 更新进度（每个视频完成后立即更新）
                    video_details_progress["processed_videos"] += 1
                    video_details_progress["last_update_time"] = time.time()

                    # 添加小延迟，避免请求过快
                    await asyncio.sleep(0.1 + random.random() * 0.2)  # 0.1-0.3秒随机延迟

            # 批次间延迟（除了最后一批）
            if batch_num < total_batches and not video_details_progress["is_stopped"]:
                delay_time = 3 + random.random() * 2  # 3-5秒随机延迟
                logger.info(f"第 {batch_num} 批处理完成，等待 {delay_time:.1f} 秒后处理下一批")
                await asyncio.sleep(delay_time)

        # 任务完成或被停止
        video_details_progress["is_processing"] = False
        video_details_progress["is_complete"] = True
        video_details_progress["last_update_time"] = time.time()

        if video_details_progress["is_stopped"]:
            logger.info(f"视频详情获取被用户停止，已处理: {video_details_progress['processed_videos']}/{len(video_list)}")
        else:
            logger.info(f"批量获取视频详情完成，成功: {video_details_progress['success_count']}, 失败: {video_details_progress['failed_count']}")

    except Exception as e:
        logger.error(f"后台获取视频详情任务失败: {e}")
        video_details_progress["is_processing"] = False
        video_details_progress["is_complete"] = True
        video_details_progress["last_update_time"] = time.time()


def reset_video_details_progress():
    """重置视频详情进度状态到初始状态"""
    global video_details_progress
    video_details_progress.update({
        "is_processing": False,
        "is_complete": False,
        "is_stopped": False,
        "total_videos": 0,
        "processed_videos": 0,
        "success_count": 0,
        "failed_count": 0,
        "error_videos": [],
        "skipped_invalid_count": 0,
        "start_time": 0,
        "last_update_time": 0
    })


@router.post("/stop", summary="停止视频详情获取任务")
async def stop_video_details_fetch():
    """停止视频详情获取任务"""
    try:
        if not video_details_progress["is_processing"]:
            # 如果没有正在运行的任务，直接重置状态
            reset_video_details_progress()
            return {
                "status": "success",
                "message": "当前没有正在运行的任务，已重置状态"
            }

        # 设置停止标志
        video_details_progress["is_stopped"] = True
        video_details_progress["last_update_time"] = time.time()

        logger.info("用户请求停止视频详情获取任务")

        # 等待一小段时间让后台任务处理停止信号
        await asyncio.sleep(0.5)

        # 强制重置状态到初始状态
        reset_video_details_progress()

        return {
            "status": "success",
            "message": "任务已停止，状态已重置",
            "data": {
                "is_processing": False,
                "is_complete": False,
                "is_stopped": False
            }
        }
    except Exception as e:
        logger.error(f"停止视频详情获取任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"停止任务失败: {str(e)}")


@router.post("/reset", summary="重置视频详情获取状态")
async def reset_video_details_status():
    """重置视频详情获取状态到初始状态"""
    try:
        reset_video_details_progress()
        logger.info("用户手动重置了视频详情获取状态")

        return {
            "status": "success",
            "message": "状态已重置到初始状态",
            "data": {
                "is_processing": False,
                "is_complete": False,
                "is_stopped": False,
                "total_videos": 0,
                "processed_videos": 0,
                "success_count": 0,
                "failed_count": 0
            }
        }
    except Exception as e:
        logger.error(f"重置视频详情状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"重置状态失败: {str(e)}")


@router.get("/progress", summary="获取视频详情获取进度")
async def get_video_details_progress(
    update_interval: float = Query(0.1, description="更新间隔，单位秒")
):
    """获取视频详情获取进度的SSE流"""
    async def generate_progress():
        while True:
            # 计算进度百分比
            progress_percentage = 0
            if video_details_progress["total_videos"] > 0:
                progress_percentage = (video_details_progress["processed_videos"] / video_details_progress["total_videos"]) * 100

            # 计算已用时间
            elapsed_time = "0.00秒"
            if video_details_progress["start_time"] > 0:
                elapsed_seconds = time.time() - video_details_progress["start_time"]
                elapsed_time = f"{elapsed_seconds:.2f}秒"

            # 构建进度数据
            progress_data = {
                "is_processing": video_details_progress["is_processing"],
                "is_complete": video_details_progress["is_complete"],
                "is_stopped": video_details_progress["is_stopped"],
                "total_videos": video_details_progress["total_videos"],
                "processed_videos": video_details_progress["processed_videos"],
                "success_count": video_details_progress["success_count"],
                "failed_count": video_details_progress["failed_count"],
                "error_videos": video_details_progress["error_videos"],
                "skipped_invalid_count": video_details_progress["skipped_invalid_count"],
                "progress_percentage": progress_percentage,
                "elapsed_time": elapsed_time,
                "last_update_time": video_details_progress["last_update_time"]
            }

            # 发送数据
            yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

            # 如果任务完成或停止，发送最后一次数据后退出
            if video_details_progress["is_complete"] or video_details_progress["is_stopped"]:
                break

            # 等待指定的更新间隔
            await asyncio.sleep(update_interval)

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*"
        }
    )
