import json
import logging
import os
import time
import sqlite3
import asyncio
import concurrent.futures
import random
import string
from datetime import datetime, timedelta
import requests
from scripts.utils import load_config, get_base_path, get_output_path

# 导入获取视频详情的函数
from routers.download import get_video_info

config = load_config()

def load_cookie():
    """从配置文件读取 SESSDATA"""
    print("\n=== 读取 Cookie 配置 ===")
    # 重新加载配置文件，确保获取最新的SESSDATA
    current_config = load_config()
    print(f"配置内容: {current_config}")
    sessdata = current_config.get('SESSDATA', '')
    if not sessdata:
        print("警告: 配置文件中未找到 SESSDATA")
        return ''
    
    # 移除可能存在的引号
    sessdata = sessdata.strip('"')
    if not sessdata:
        print("警告: SESSDATA 为空")
        return ''
        
    print(f"获取到的 SESSDATA: {sessdata}")
    return sessdata

def find_latest_local_history(base_folder='history_by_date'):
    """查找本地最新的历史记录"""
    print("正在查找本地最新的历史记录...")
    full_base_folder = get_output_path(base_folder)  # 使用 get_output_path
    
    print(f"\n=== 查找历史记录 ===")
    print(f"查找路径: {full_base_folder}")
    print(f"路径存在: {os.path.exists(full_base_folder)}")
    
    if not os.path.exists(full_base_folder):
        print("本地历史记录文件夹不存在，将从头开始同步。")
        return None

    latest_date = None
    try:
        latest_year = max([int(year) for year in os.listdir(full_base_folder) if year.isdigit()], default=None)
        if latest_year:
            latest_month = max(
                [int(month) for month in os.listdir(os.path.join(full_base_folder, str(latest_year))) if month.isdigit()],
                default=None
            )
            if latest_month:
                latest_day = max([
                    int(day.split('.')[0]) for day in
                    os.listdir(os.path.join(full_base_folder, str(latest_year), f"{latest_month:02}"))
                    if day.endswith('.json')
                ], default=None)
                if latest_day:
                    latest_file = os.path.join(full_base_folder, str(latest_year), f"{latest_month:02}",
                                             f"{latest_day:02}.json")
                    print(f"找到最新历史记录文件: {latest_file}")
                    with open(latest_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        latest_date = datetime.fromtimestamp(data[-1]['view_at']).date()
    except ValueError:
        print("历史记录目录格式不正确，可能尚未创建任何文件。")

    if latest_date:
        print(f"本地最新的观看日期: {latest_date}")
    return latest_date

def save_history(history_data, base_folder='history_by_date'):
    """保存历史记录"""
    logging.info(f"开始保存{len(history_data)}条新历史记录...")
    full_base_folder = get_output_path(base_folder)
    saved_count = 0

    print(f"\n=== 保存历史记录 ===")
    print(f"保存路径: {full_base_folder}")
    
    for entry in history_data:
        timestamp = entry['view_at']
        dt_object = datetime.fromtimestamp(timestamp)
        year = dt_object.strftime('%Y')
        month = dt_object.strftime('%m')
        day = dt_object.strftime('%d')

        folder_path = os.path.join(full_base_folder, year, month)
        os.makedirs(folder_path, exist_ok=True)

        file_path = os.path.join(folder_path, f"{day}.json")

        existing_records = set()  # 使用集合存储bvid和view_at的组合
        if os.path.exists(file_path):
            try:
                # 尝试不同的编码方式读取
                for encoding in ['utf-8', 'gbk', 'utf-8-sig']:
                    try:
                        with open(file_path, 'r', encoding=encoding) as f:
                            daily_data = json.load(f)
                            # 将bvid和view_at组合作为唯一标识
                            existing_records = {
                                (item['history']['bvid'], item['view_at']) 
                                for item in daily_data
                            }
                            break
                    except UnicodeDecodeError:
                        continue
                    except json.JSONDecodeError:
                        continue
            except Exception as e:
                logging.warning(f"警告: 读取文件 {file_path} 失败: {e}，将创建新文件")
                daily_data = []
        else:
            daily_data = []

        # 检查当前记录的bvid和view_at组合是否已存在
        current_record = (entry['history']['bvid'], entry['view_at'])
        if current_record not in existing_records:
            daily_data.append(entry)
            existing_records.add(current_record)
            saved_count += 1

        # 保存时使用 utf-8 编码
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(daily_data, f, ensure_ascii=False, indent=4)
            
    logging.info(f"历史记录保存完成，共保存了{saved_count}条新记录。")
    return {"status": "success", "message": f"历史记录获取成功", "data": history_data}

def save_video_details(video_data):
    """将视频详细信息保存到新数据库"""
    try:
        # 设置数据库路径
        db_path = get_output_path("video_library.db")
        print(f"视频库数据库路径: {db_path}")
        
        # 创建连接
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 如果不存在，创建主表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_details (
            id INTEGER PRIMARY KEY,
            bvid TEXT UNIQUE,
            aid INTEGER,
            videos INTEGER,
            tid INTEGER,
            tid_v2 INTEGER,
            tname TEXT,
            tname_v2 TEXT,
            copyright INTEGER,
            pic TEXT,
            title TEXT,
            pubdate INTEGER,
            ctime INTEGER,
            desc TEXT,
            state INTEGER,
            duration INTEGER,
            
            -- rights信息
            rights_bp INTEGER,
            rights_elec INTEGER,
            rights_download INTEGER,
            rights_movie INTEGER,
            rights_pay INTEGER,
            rights_hd5 INTEGER,
            rights_no_reprint INTEGER,
            rights_autoplay INTEGER,
            rights_ugc_pay INTEGER,
            rights_is_cooperation INTEGER,
            rights_ugc_pay_preview INTEGER,
            rights_no_background INTEGER,
            rights_clean_mode INTEGER,
            rights_is_stein_gate INTEGER,
            rights_is_360 INTEGER,
            rights_no_share INTEGER,
            rights_arc_pay INTEGER,
            rights_free_watch INTEGER,
            
            -- owner信息
            owner_mid INTEGER,
            owner_name TEXT,
            owner_face TEXT,
            
            -- stat信息
            stat_view INTEGER,
            stat_danmaku INTEGER,
            stat_reply INTEGER,
            stat_favorite INTEGER,
            stat_coin INTEGER,
            stat_share INTEGER,
            stat_now_rank INTEGER,
            stat_his_rank INTEGER,
            stat_like INTEGER,
            stat_dislike INTEGER,
            
            -- argue_info
            argue_msg TEXT,
            argue_type INTEGER,
            argue_link TEXT,
            
            -- 其他信息
            dynamic TEXT,
            cid INTEGER,
            dimension_width INTEGER,
            dimension_height INTEGER,
            dimension_rotate INTEGER,
            teenage_mode INTEGER,
            is_chargeable_season INTEGER,
            is_story INTEGER,
            is_upower_exclusive INTEGER,
            is_upower_play INTEGER,
            is_upower_preview INTEGER,
            enable_vt INTEGER,
            vt_display TEXT,
            is_upower_exclusive_with_qa INTEGER,
            no_cache INTEGER,
            
            -- 字幕信息
            subtitle_allow_submit INTEGER,
            
            -- 标签信息
            label_type INTEGER,
            
            -- 季节信息
            is_season_display INTEGER,
            
            -- 点赞信息
            like_icon TEXT,
            
            -- 其他布尔信息
            need_jump_bv INTEGER,
            disable_show_up_info INTEGER,
            is_story_play INTEGER,
            is_view_self INTEGER,
            
            -- 添加时间
            add_time INTEGER
        )
        ''')
        
        # 创建视频分P表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_pages (
            id INTEGER PRIMARY KEY,
            video_bvid TEXT,
            cid INTEGER,
            page INTEGER,
            from_source TEXT,
            part TEXT,
            duration INTEGER,
            vid TEXT,
            weblink TEXT,
            dimension_width INTEGER,
            dimension_height INTEGER,
            dimension_rotate INTEGER,
            first_frame TEXT,
            ctime INTEGER,
            FOREIGN KEY (video_bvid) REFERENCES video_details (bvid)
        )
        ''')
        
        # 创建视频staff表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_staff (
            id INTEGER PRIMARY KEY,
            video_bvid TEXT,
            mid INTEGER,
            title TEXT,
            name TEXT,
            face TEXT,
            vip_type INTEGER,
            vip_status INTEGER,
            official_role INTEGER,
            official_title TEXT,
            official_desc TEXT,
            follower INTEGER,
            FOREIGN KEY (video_bvid) REFERENCES video_details (bvid)
        )
        ''')
        
        # 创建字幕表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_subtitles (
            id INTEGER PRIMARY KEY,
            video_bvid TEXT,
            subtitle_id TEXT,
            lan TEXT,
            lan_doc TEXT,
            is_lock INTEGER,
            subtitle_url TEXT,
            type INTEGER,
            ai_type INTEGER,
            ai_status INTEGER,
            FOREIGN KEY (video_bvid) REFERENCES video_details (bvid)
        )
        ''')
        
        # 创建荣誉列表表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_honors (
            id INTEGER PRIMARY KEY,
            video_bvid TEXT,
            aid INTEGER,
            type INTEGER,
            desc TEXT,
            weekly_recommend_num INTEGER,
            FOREIGN KEY (video_bvid) REFERENCES video_details (bvid)
        )
        ''')
        
        # 检查是否已存在相同的视频
        cursor.execute("SELECT id FROM video_details WHERE bvid = ?", (video_data['bvid'],))
        existing = cursor.fetchone()
        
        current_time = int(time.time())
        bvid = video_data.get('bvid', '')
        
        # 准备数据
        video_info = {}
        
        # 基本信息
        video_info['bvid'] = bvid
        video_info['aid'] = video_data.get('aid', 0)
        video_info['videos'] = video_data.get('videos', 0)
        video_info['tid'] = video_data.get('tid', 0)
        video_info['tid_v2'] = video_data.get('tid_v2', 0)
        video_info['tname'] = video_data.get('tname', '')
        video_info['tname_v2'] = video_data.get('tname_v2', '')
        video_info['copyright'] = video_data.get('copyright', 0)
        video_info['pic'] = video_data.get('pic', '')
        video_info['title'] = video_data.get('title', '')
        video_info['pubdate'] = video_data.get('pubdate', 0)
        video_info['ctime'] = video_data.get('ctime', 0)
        video_info['desc'] = video_data.get('desc', '')
        video_info['state'] = video_data.get('state', 0)
        video_info['duration'] = video_data.get('duration', 0)
        
        # rights信息
        rights = video_data.get('rights', {})
        video_info['rights_bp'] = rights.get('bp', 0)
        video_info['rights_elec'] = rights.get('elec', 0)
        video_info['rights_download'] = rights.get('download', 0)
        video_info['rights_movie'] = rights.get('movie', 0)
        video_info['rights_pay'] = rights.get('pay', 0)
        video_info['rights_hd5'] = rights.get('hd5', 0)
        video_info['rights_no_reprint'] = rights.get('no_reprint', 0)
        video_info['rights_autoplay'] = rights.get('autoplay', 0)
        video_info['rights_ugc_pay'] = rights.get('ugc_pay', 0)
        video_info['rights_is_cooperation'] = rights.get('is_cooperation', 0)
        video_info['rights_ugc_pay_preview'] = rights.get('ugc_pay_preview', 0)
        video_info['rights_no_background'] = rights.get('no_background', 0)
        video_info['rights_clean_mode'] = rights.get('clean_mode', 0)
        video_info['rights_is_stein_gate'] = rights.get('is_stein_gate', 0)
        video_info['rights_is_360'] = rights.get('is_360', 0)
        video_info['rights_no_share'] = rights.get('no_share', 0)
        video_info['rights_arc_pay'] = rights.get('arc_pay', 0)
        video_info['rights_free_watch'] = rights.get('free_watch', 0)
        
        # owner信息
        owner = video_data.get('owner', {})
        video_info['owner_mid'] = owner.get('mid', 0)
        video_info['owner_name'] = owner.get('name', '')
        video_info['owner_face'] = owner.get('face', '')
        
        # stat信息
        stat = video_data.get('stat', {})
        video_info['stat_view'] = stat.get('view', 0)
        video_info['stat_danmaku'] = stat.get('danmaku', 0)
        video_info['stat_reply'] = stat.get('reply', 0)
        video_info['stat_favorite'] = stat.get('favorite', 0)
        video_info['stat_coin'] = stat.get('coin', 0)
        video_info['stat_share'] = stat.get('share', 0)
        video_info['stat_now_rank'] = stat.get('now_rank', 0)
        video_info['stat_his_rank'] = stat.get('his_rank', 0)
        video_info['stat_like'] = stat.get('like', 0)
        video_info['stat_dislike'] = stat.get('dislike', 0)
        
        # argue_info
        argue_info = video_data.get('argue_info', {})
        video_info['argue_msg'] = argue_info.get('argue_msg', '')
        video_info['argue_type'] = argue_info.get('argue_type', 0)
        video_info['argue_link'] = argue_info.get('argue_link', '')
        
        # dynamic
        video_info['dynamic'] = video_data.get('dynamic', '')
        video_info['cid'] = video_data.get('cid', 0)
        
        # dimension
        dimension = video_data.get('dimension', {})
        video_info['dimension_width'] = dimension.get('width', 0)
        video_info['dimension_height'] = dimension.get('height', 0)
        video_info['dimension_rotate'] = dimension.get('rotate', 0)
        
        # 其他标志位
        video_info['teenage_mode'] = video_data.get('teenage_mode', 0)
        video_info['is_chargeable_season'] = 1 if video_data.get('is_chargeable_season', False) else 0
        video_info['is_story'] = 1 if video_data.get('is_story', False) else 0
        video_info['is_upower_exclusive'] = 1 if video_data.get('is_upower_exclusive', False) else 0
        video_info['is_upower_play'] = 1 if video_data.get('is_upower_play', False) else 0
        video_info['is_upower_preview'] = 1 if video_data.get('is_upower_preview', False) else 0
        video_info['enable_vt'] = video_data.get('enable_vt', 0)
        video_info['vt_display'] = video_data.get('vt_display', '')
        video_info['is_upower_exclusive_with_qa'] = 1 if video_data.get('is_upower_exclusive_with_qa', False) else 0
        video_info['no_cache'] = 1 if video_data.get('no_cache', False) else 0
        
        # 字幕信息
        subtitle = video_data.get('subtitle', {})
        video_info['subtitle_allow_submit'] = 1 if subtitle.get('allow_submit', False) else 0
        
        # 标签信息
        label = video_data.get('label', {})
        video_info['label_type'] = label.get('type', 0)
        
        # 季节信息
        video_info['is_season_display'] = 1 if video_data.get('is_season_display', False) else 0
        
        # 点赞信息
        video_info['like_icon'] = video_data.get('like_icon', '')
        
        # 其他布尔信息
        video_info['need_jump_bv'] = 1 if video_data.get('need_jump_bv', False) else 0
        video_info['disable_show_up_info'] = 1 if video_data.get('disable_show_up_info', False) else 0
        video_info['is_story_play'] = video_data.get('is_story_play', 0)
        video_info['is_view_self'] = 1 if video_data.get('is_view_self', False) else 0
        
        # 添加时间
        video_info['add_time'] = current_time
        
        if existing:
            # 构建更新语句
            update_fields = []
            update_values = []
            
            for key, value in video_info.items():
                if key != 'bvid':  # 不更新主键bvid
                    update_fields.append(f"{key} = ?")
                    update_values.append(value)
            
            # 添加WHERE条件的值
            update_values.append(video_info['bvid'])
            
            # 执行更新
            cursor.execute(
                f"UPDATE video_details SET {', '.join(update_fields)} WHERE bvid = ?",
                update_values
            )
            print(f"已更新视频信息: {video_info['title']} (BV号: {video_info['bvid']})")
            
            # 删除相关的子表数据，以便重新插入
            cursor.execute("DELETE FROM video_pages WHERE video_bvid = ?", (bvid,))
            cursor.execute("DELETE FROM video_staff WHERE video_bvid = ?", (bvid,))
            cursor.execute("DELETE FROM video_subtitles WHERE video_bvid = ?", (bvid,))
            cursor.execute("DELETE FROM video_honors WHERE video_bvid = ?", (bvid,))
        else:
            # 构建插入语句
            columns = list(video_info.keys())
            placeholders = ['?'] * len(columns)
            values = [video_info[key] for key in columns]
            
            # 执行插入
            cursor.execute(
                f"INSERT INTO video_details ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                values
            )
            print(f"已添加新视频到库: {video_info['title']} (BV号: {video_info['bvid']})")
        
        # 插入分P信息
        pages = video_data.get('pages', [])
        for page in pages:
            page_dimension = page.get('dimension', {})
            cursor.execute('''
            INSERT INTO video_pages (
                video_bvid, cid, page, from_source, part, duration, vid, weblink,
                dimension_width, dimension_height, dimension_rotate, first_frame, ctime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bvid, 
                page.get('cid', 0),
                page.get('page', 0),
                page.get('from', ''),
                page.get('part', ''),
                page.get('duration', 0),
                page.get('vid', ''),
                page.get('weblink', ''),
                page_dimension.get('width', 0),
                page_dimension.get('height', 0),
                page_dimension.get('rotate', 0),
                page.get('first_frame', ''),
                page.get('ctime', 0)
            ))
        
        # 插入staff信息
        staff_list = video_data.get('staff', [])
        for staff in staff_list:
            vip = staff.get('vip', {})
            official = staff.get('official', {})
            cursor.execute('''
            INSERT INTO video_staff (
                video_bvid, mid, title, name, face, 
                vip_type, vip_status, official_role, official_title, official_desc, follower
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bvid,
                staff.get('mid', 0),
                staff.get('title', ''),
                staff.get('name', ''),
                staff.get('face', ''),
                vip.get('type', 0),
                vip.get('status', 0),
                official.get('role', 0),
                official.get('title', ''),
                official.get('desc', ''),
                staff.get('follower', 0)
            ))
        
        # 插入字幕信息
        subtitle_list = subtitle.get('list', [])
        for sub in subtitle_list:
            cursor.execute('''
            INSERT INTO video_subtitles (
                video_bvid, subtitle_id, lan, lan_doc, is_lock, 
                subtitle_url, type, ai_type, ai_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bvid,
                sub.get('id_str', ''),
                sub.get('lan', ''),
                sub.get('lan_doc', ''),
                1 if sub.get('is_lock', False) else 0,
                sub.get('subtitle_url', ''),
                sub.get('type', 0),
                sub.get('ai_type', 0),
                sub.get('ai_status', 0)
            ))
        
        # 插入荣誉信息
        honor_reply = video_data.get('honor_reply', {})
        honor_list = honor_reply.get('honor', [])
        for honor in honor_list:
            cursor.execute('''
            INSERT INTO video_honors (
                video_bvid, aid, type, desc, weekly_recommend_num
            ) VALUES (?, ?, ?, ?, ?)
            ''', (
                bvid,
                honor.get('aid', 0),
                honor.get('type', 0),
                honor.get('desc', ''),
                honor.get('weekly_recommend_num', 0)
            ))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"保存视频详情时出错: {e}")
        import traceback
        print(traceback.format_exc())
        if 'conn' in locals() and conn:
            conn.rollback()
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# 添加一个函数，用于检查视频是否已经存在于视频库中
def is_video_exists(bvid):
    """检查视频是否已经存在于视频库中"""
    try:
        db_path = get_output_path("video_library.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM video_details WHERE bvid = ?", (bvid,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    except Exception as e:
        print(f"检查视频是否存在时出错: {e}")
        return False

def create_invalid_videos_table():
    """创建记录失效视频的数据库表"""
    try:
        db_path = get_output_path("video_library.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 创建失效视频表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS invalid_videos (
            id INTEGER PRIMARY KEY,
            bvid TEXT UNIQUE,
            error_type TEXT,
            error_code INTEGER,
            error_message TEXT,
            raw_response TEXT,
            first_check_time INTEGER,
            last_check_time INTEGER,
            check_count INTEGER DEFAULT 1
        )
        ''')
        
        conn.commit()
        conn.close()
        print("成功创建或更新失效视频表")
        return True
    except Exception as e:
        print(f"创建失效视频表时出错: {e}")
        return False

def save_invalid_video(video_result):
    """保存失效视频记录到数据库"""
    try:
        # 获取视频信息
        bvid = getattr(video_result, 'bvid', None)
        if not bvid:
            print("无法保存失效视频记录：缺少BV号")
            return False
        
        error_type = getattr(video_result, 'error_type', 'unknown')
        error_code = getattr(video_result, 'error_code', None)
        error_message = getattr(video_result, 'message', '')
        raw_response = getattr(video_result, 'raw_response', None)
        
        # 如果raw_response是字典，转换为JSON字符串
        if isinstance(raw_response, dict):
            raw_response = json.dumps(raw_response, ensure_ascii=False)
        elif raw_response is None:
            raw_response = ""
            
        current_time = int(time.time())
        
        # 连接数据库
        db_path = get_output_path("video_library.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 确保表存在
        create_invalid_videos_table()
        
        # 检查是否已存在记录
        cursor.execute("SELECT check_count, first_check_time FROM invalid_videos WHERE bvid = ?", (bvid,))
        existing = cursor.fetchone()
        
        if existing:
            # 更新现有记录
            check_count = existing[0] + 1
            first_check_time = existing[1]
            
            cursor.execute('''
                UPDATE invalid_videos 
                SET error_type = ?, 
                    error_code = ?, 
                    error_message = ?, 
                    raw_response = ?, 
                    last_check_time = ?, 
                    check_count = ?
                WHERE bvid = ?
            ''', (error_type, error_code, error_message, raw_response, current_time, check_count, bvid))
            
            print(f"更新失效视频记录: {bvid}, 错误类型: {error_type}, 检查次数: {check_count}")
        else:
            # 插入新记录
            cursor.execute('''
                INSERT INTO invalid_videos 
                (bvid, error_type, error_code, error_message, raw_response, first_check_time, last_check_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (bvid, error_type, error_code, error_message, raw_response, current_time, current_time))
            
            print(f"添加新失效视频记录: {bvid}, 错误类型: {error_type}")
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"保存失效视频记录时出错: {e}")
        import traceback
        print(traceback.format_exc())
        return False

def check_invalid_video(bvid):
    """检查视频是否已在失效视频表中"""
    try:
        db_path = get_output_path("video_library.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, error_type, last_check_time FROM invalid_videos WHERE bvid = ?", (bvid,))
        result = cursor.fetchone()
        
        conn.close()
        
        if result:
            # 如果在失效表中找到，返回错误类型和最后检查时间
            return {
                "is_invalid": True,
                "error_type": result[1],
                "last_check_time": result[2]
            }
        return {"is_invalid": False}
    except Exception as e:
        print(f"检查失效视频时出错: {e}")
        return {"is_invalid": False}

# 修改get_video_info_sync函数，在JSON解析错误时保存并打印原始响应内容，并确保将这类错误也添加到失效表中
def get_video_info_sync(bvid, sessdata, skip_exists=False):
    """同步版本的获取视频详情函数，供多线程使用"""
    # 如果需要跳过已存在的视频，则先检查
    if skip_exists and is_video_exists(bvid):
        print(f"视频 {bvid} 已存在于数据库中，跳过获取")
        return None
    
    # 检查是否已知失效视频
    invalid_check = check_invalid_video(bvid)
    if invalid_check["is_invalid"]:
        print(f"视频 {bvid} 已知失效，类型: {invalid_check['error_type']}，最后检查时间: {datetime.fromtimestamp(invalid_check['last_check_time'])}")
        return type('ErrorResponse', (), {
            'status': 'error',
            'message': f"已知失效视频 (类型: {invalid_check['error_type']})",
            'data': None,
            'bvid': bvid,
            'error_type': invalid_check['error_type'],
            'error_code': None,
            'raw_response': None,
            'is_known_invalid': True
        })
    
    # 随机延迟0.5-2秒，使请求看起来更像人类行为
    delay = 0.5 + random.random() * 1.5
    time.sleep(delay)
    
    # 生成随机的buvid和其他cookie值
    buvid3 = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    buvid4 = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    b_nut = str(int(time.time() * 1000))
    
    # 随机化User-Agent
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
    ]
    user_agent = random.choice(user_agents)
    
    # 构建更完整的请求头
    headers = {
        'User-Agent': user_agent,
        'Referer': f'https://www.bilibili.com/video/{bvid}',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Origin': 'https://www.bilibili.com',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Ch-Ua': '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Cookie': f'SESSDATA={sessdata}; buvid3={buvid3}; buvid4={buvid4}; b_nut={b_nut}; bsource=search_google; _uuid=D{buvid3}-{b_nut}-{buvid4}'
    }
    
    # 使用指数退避策略进行重试
    max_retries = 3
    last_response_text = None
    last_error = None
    
    for retry in range(max_retries):
        try:
            # 直接使用同步请求，避免事件循环嵌套问题
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            response = requests.get(url, headers=headers, timeout=20)
            
            # 保存原始响应文本，以便错误时打印
            last_response_text = response.text
            
            # 检查响应状态码
            if response.status_code == 412:
                print(f"获取视频 {bvid} 的详情被服务器拒绝(412)，等待后重试...")
                print(f"原始响应: {last_response_text[:500]}...")  # 打印部分响应内容
                # 412错误时使用更长的指数退避延迟
                retry_delay = (4 ** retry) + random.uniform(1, 5)
                time.sleep(retry_delay)
                continue
                
            # 如果是其他错误状态码
            if response.status_code != 200:
                print(f"获取视频 {bvid} 的详情失败，HTTP状态码: {response.status_code}")
                print(f"原始响应: {last_response_text[:500]}...")  # 打印部分响应内容
                return type('ErrorResponse', (), {
                    'status': 'error',
                    'message': f'HTTP错误 {response.status_code}: {response.reason}',
                    'data': None,
                    'bvid': bvid,
                    'error_type': 'http_error',
                    'error_code': response.status_code,
                    'raw_response': last_response_text
                })
            
            # 尝试解析JSON响应
            try:
                data = response.json()
            except json.JSONDecodeError as json_err:
                print(f"获取视频 {bvid} 时出现JSON解析错误: {str(json_err)}")
                print(f"原始响应内容: {last_response_text[:500]}...")  # 打印部分响应以便分析
                
                # 将解析错误作为失效视频处理
                error_response = type('ErrorResponse', (), {
                    'status': 'error',
                    'message': f'JSON解析错误: {str(json_err)}',
                    'data': None,
                    'bvid': bvid,
                    'error_type': 'parse_error',
                    'error_code': None,
                    'raw_response': last_response_text
                })
                
                # 保存到失效视频表
                save_invalid_video(error_response)
                
                return error_response
            
            # 打印失效视频的响应数据，用于分析
            if data.get('code') != 0:
                print(f"视频 {bvid} 失效，B站返回数据: {json.dumps(data, ensure_ascii=False)}")
            
            # 检查API错误码
            if data.get('code') != 0:
                error_code = data.get('code')
                error_msg = data.get('message', '未知错误')
                
                # 特定错误码的处理
                if error_code == -404:
                    print(f"获取视频 {bvid} 的详情失败: 视频不存在或已被删除")
                    return type('ErrorResponse', (), {
                        'status': 'error',
                        'message': f'视频不存在或已被删除 (错误码: -404)',
                        'data': None,
                        'bvid': bvid,
                        'error_type': 'not_found',
                        'error_code': error_code,
                        'raw_response': data
                    })
                elif error_code == 62002:
                    print(f"获取视频 {bvid} 的详情失败: 视频已设为私有或被隐藏") 
                    return type('ErrorResponse', (), {
                        'status': 'error',
                        'message': f'视频已设为私有或被隐藏 (错误码: 62002)',
                        'data': None,
                        'bvid': bvid,
                        'error_type': 'invisible',
                        'error_code': error_code,
                        'raw_response': data
                    })
                else:
                    print(f"获取视频 {bvid} 的详情失败: API错误 {error_code}: {error_msg}")
                    return type('ErrorResponse', (), {
                        'status': 'error',
                        'message': f'API错误 {error_code}: {error_msg}',
                        'data': None,
                        'bvid': bvid,
                        'error_type': 'api_error',
                        'error_code': error_code,
                        'raw_response': data
                    })
            
            # 成功获取数据
            return type('SuccessResponse', (), {
                'status': 'success',
                'message': '获取视频信息成功',
                'data': data.get('data', {}),
                'bvid': bvid
            })
            
        except requests.exceptions.RequestException as e:
            # 请求异常，使用指数退避策略
            last_error = str(e)
            retry_delay = (2 ** retry) + random.uniform(0.5, 2)
            print(f"获取视频 {bvid} 时出错: {e}，{retry+1}/{max_retries}次重试，等待{retry_delay:.2f}秒")
            if last_response_text:
                print(f"上次响应内容: {last_response_text[:500]}...")
            time.sleep(retry_delay)
        except Exception as e:
            # 其他异常
            last_error = str(e)
            retry_delay = (2 ** retry) + random.uniform(0.5, 2)
            print(f"处理视频 {bvid} 时出错: {e}，{retry+1}/{max_retries}次重试，等待{retry_delay:.2f}秒")
            if last_response_text:
                print(f"上次响应内容: {last_response_text[:500]}...")
            time.sleep(retry_delay)
    
    # 所有重试都失败后，创建通用错误响应
    error_response = type('ErrorResponse', (), {
        'status': 'error',
        'message': f'获取视频 {bvid} 详情失败，已重试 {max_retries} 次: {last_error}',
        'data': None,
        'bvid': bvid,
        'error_type': 'retry_exceeded',
        'error_code': None,
        'raw_response': last_response_text
    })
    
    # 将重试失败的也加入失效表，但标记为临时错误类型
    if 'Expecting value' in str(last_error):
        error_response.error_type = 'parse_error'
        # 保存到失效视频表
        save_invalid_video(error_response)
        
    return error_response

# 批量保存视频详情，修改以处理失效视频
def batch_save_video_details(video_details_list):
    """批量保存多个视频的详情"""
    success_count = 0
    fail_count = 0
    skipped_count = 0
    invalid_count = 0
    
    # 错误类型统计
    error_stats = {
        "404_not_found": 0,      # 视频不存在或已删除
        "62002_invisible": 0,    # 视频已设为私有或被隐藏
        "412_banned": 0,         # 请求被禁止/拒绝
        "decode_error": 0,       # 解码错误
        "parse_error": 0,        # JSON解析错误
        "empty_data": 0,         # 数据为空
        "save_error": 0,         # 保存过程出错
        "other_error": 0         # 其他错误
    }
    
    # 确保失效视频表已创建
    create_invalid_videos_table()
    
    for video_data in video_details_list:
        if video_data is None:
            # 跳过的视频，不计入成功或失败
            skipped_count += 1
            continue
        
        # 处理各种失败情况
        if not hasattr(video_data, 'status') or video_data.status != "success":
            fail_count += 1
            
            # 获取错误信息
            error_msg = getattr(video_data, 'message', '未知错误') if hasattr(video_data, 'message') else '未知错误'
            
            # 错误类型统计
            if '404' in error_msg or '视频不存在' in error_msg:
                error_stats["404_not_found"] += 1
            elif '62002' in error_msg or '稿件不可见' in error_msg:
                error_stats["62002_invisible"] += 1
            elif '412' in error_msg or 'request was banned' in error_msg:
                error_stats["412_banned"] += 1
            elif 'decode' in error_msg or '解码' in error_msg:
                error_stats["decode_error"] += 1
            elif 'parse_error' in error_msg or 'JSON解析错误' in error_msg:
                error_stats["parse_error"] += 1
            else:
                error_stats["other_error"] += 1
            
            # 对于失效视频，保存到失效表中
            if hasattr(video_data, 'error_type'):
                error_type = getattr(video_data, 'error_type')
                # 永久性错误类型，应保存到失效表
                permanent_error_types = ['not_found', 'invisible', 'api_error', 'parse_error']
                
                if error_type in permanent_error_types:
                    # 视频的永久性错误，将其保存到失效视频表
                    saved = save_invalid_video(video_data)
                    if saved:
                        invalid_count += 1
                        print(f"已将视频 {getattr(video_data, 'bvid', '未知')} 的错误信息保存到失效表，错误类型: {error_type}")
                
            print(f"跳过保存视频详情：获取数据失败 - {error_msg}")
            continue
            
        if not hasattr(video_data, 'data') or not video_data.data:
            fail_count += 1
            error_stats["empty_data"] += 1
            print("跳过保存视频详情：数据为空")
            continue
        
        # 尝试保存视频详情
        try:
            bvid = video_data.data.get('bvid', '未知BV号')
            title = video_data.data.get('title', '未知标题')
            
            result = save_video_details(video_data.data)
            if result:
                success_count += 1
                print(f"成功保存视频: {title} ({bvid})")
            else:
                fail_count += 1
                error_stats["save_error"] += 1
                print(f"保存视频详情失败: {bvid}")
        except Exception as e:
            fail_count += 1
            error_stats["save_error"] += 1
            print(f"保存视频详情时发生异常: {str(e)}")
    
    # 打印统计信息
    print(f"\n=== 批量保存完成 ===")
    print(f"成功：{success_count}，失败：{fail_count}，失效视频：{invalid_count}，跳过：{skipped_count}")
    
    # 输出错误类型统计
    if fail_count > 0:
        print("\n错误类型统计:")
        for error_type, count in error_stats.items():
            if count > 0:
                print(f"- {error_type}: {count}次")
    
    return {
        "success": success_count, 
        "fail": fail_count, 
        "invalid": invalid_count,
        "skipped": skipped_count,
        "error_stats": error_stats
    }

async def fetch_and_compare_history(cookie, latest_date, skip_exists=False, process_video_details=False):
    """
    获取历史记录并与本地最新记录对比
    
    Args:
        cookie: 用户cookie中的SESSDATA
        latest_date: 本地最新的记录日期，格式为YYYY-MM-DD
        skip_exists: 是否跳过已存在的记录
        process_video_details: 是否同时获取视频详情，默认为False
    
    Returns:
        dict: 新的历史记录，按日期分组
    """
    api_url = "https://api.bilibili.com/x/v2/history"
    
    print("\n=== API 请求信息 ===")
    print(f"使用的 Cookie: {cookie}")
    
    url = 'https://api.bilibili.com/x/web-interface/history/cursor'
    
    # 添加更多必要的 cookie 字段
    headers = {
        'Cookie': f"SESSDATA={cookie}; buvid3=random_string; b_nut=1234567890; buvid4=random_string",
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://www.bilibili.com',
        'Origin': 'https://www.bilibili.com',
        'Accept': 'application/json, text/plain, */*',
        'Connection': 'keep-alive'
    }
    print(f"请求头: {headers}")
    
    params = {
        'ps': 30,
        'max': '',
        'view_at': '',
        'business': '',
    }
    
    # 测试 API 连接
    response = requests.get(url, headers=headers, params=params)
    print(f"\n=== API 响应信息 ===")
    print(f"状态码: {response.status_code}")
    try:
        response_data = response.json()
        if response_data.get('code') == -101:
            print("Cookie 已失效，请更新 SESSDATA")
            return []
    except:
        print(f"响应内容: {response.text}")
    
    all_new_data = []
    all_video_ids = []  # 存储所有需要获取详情的视频ID
    page_count = 0
    last_view_at = None  # 记录最后一条数据的时间
    empty_page_count = 0  # 记录连续空页面的次数
    max_empty_pages = 3   # 最大允许的连续空页面次数

    if latest_date:
        # 直接使用最新日期的时间戳作为停止条件
        cutoff_timestamp = int(datetime.combine(latest_date, datetime.min.time()).timestamp())
        print(f"设置停止条件：view_at <= {cutoff_timestamp} ({latest_date})")
    else:
        cutoff_timestamp = 0
        print("没有本地数据，抓取所有可用的历史记录。")

    while True:
        page_count += 1
        print(f"发送请求获取数据... (第{page_count}页)")
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            try:
                data = response.json()
                if data['code'] != 0:
                    print(f"API请求失败，错误码: {data['code']}, 错误信息: {data['message']}")
                    break

                if 'data' in data and 'list' in data['data']:
                    fetched_list = data['data']['list']
                    print(f"获取到{len(fetched_list)}条记录，进行对比...")

                    # 如果获取到0条记录，检查是否是因为到达了最后一页
                    if len(fetched_list) == 0:
                        empty_page_count += 1
                        print(f"连续获取到空页面 {empty_page_count}/{max_empty_pages}")
                        
                        if empty_page_count >= max_empty_pages:
                            print(f"连续{max_empty_pages}次获取到空页面，停止请求。")
                            break
                            
                        if 'cursor' in data['data']:
                            # 检查新的游标时间是否大于最后一条记录的时间
                            new_view_at = data['data']['cursor']['view_at']
                            current_max = data['data']['cursor']['max']
                            
                            # 如果游标被重置（max变为0或很小的值），说明已经到达末尾
                            if current_max == 0 or (last_view_at and current_max < 1000000):
                                print(f"检测到游标重置（max={current_max}），停止请求。")
                                break
                                
                            if last_view_at and new_view_at >= last_view_at:
                                print(f"检测到重复数据（当前游标时间 {new_view_at} >= 最后记录时间 {last_view_at}），停止请求。")
                                break
                                
                            params['max'] = current_max
                            params['view_at'] = new_view_at
                            print(f"获取到空页，尝试继续请求。游标更新：max={params['max']}, view_at={params['view_at']}")
                            continue
                        else:
                            print("没有更多数据，停止请求。")
                            break
                    else:
                        # 重置空页面计数
                        empty_page_count = 0

                    # 更新最后一条记录的时间
                    if fetched_list:
                        last_view_at = fetched_list[-1]['view_at']
                        print(f"更新最后记录时间: {last_view_at}")

                    # 收集所有视频ID，先不进行API调用
                    for entry in fetched_list:
                        print(f"标题: {entry['title']}, 观看时间: {datetime.fromtimestamp(entry['view_at'])}")
                        
                        # 从历史记录获取 bvid
                        bvid = entry['history'].get('bvid', '')
                        if bvid:
                            all_video_ids.append(bvid)

                    new_entries = []
                    should_stop = False

                    for entry in fetched_list:
                        view_at = entry['view_at']
                        if view_at > cutoff_timestamp:
                            new_entries.append(entry)
                        else:
                            should_stop = True

                    if new_entries:
                        all_new_data.extend(new_entries)
                        print(f"找到{len(new_entries)}条新记录。")

                    if should_stop:
                        print("达到停止条件，停止请求。")
                        break

                    if 'cursor' in data['data']:
                        current_max = data['data']['cursor']['max']
                        params['max'] = current_max
                        params['view_at'] = data['data']['cursor']['view_at']
                        print(f"请求游标更新：max={params['max']}, view_at={params['view_at']}")
                    else:
                        print("未能获取游标信息，停止请求。")
                        break

                    await asyncio.sleep(1)
                else:
                    print("没有更多的数据或数据结构错误。")
                    break

            except json.JSONDecodeError:
                print("JSON Decode Error: 无法解析服务器响应")
                break
        else:
            print(f"请求失败，状态码: {response.status_code}")
            break

    # 完成历史记录获取后，使用多线程获取视频详情
    if all_video_ids and process_video_details:
        print(f"\n=== 多线程获取视频详情 ===")
        print(f"总共有 {len(all_video_ids)} 个视频需要获取详情")
        
        # 去重
        unique_video_ids = list(set(all_video_ids))
        print(f"去重后有 {len(unique_video_ids)} 个不同的视频")
        
        # 使用线程池并行获取视频详情 - 增加最大线程数到30
        max_workers = min(30, len(unique_video_ids))  # 最多30个线程
        print(f"使用 {max_workers} 个线程并行获取视频详情")
        
        # 分批处理，避免一次性创建太多线程
        batch_size = 30  # 增加批处理数量
        results = []
        
        for i in range(0, len(unique_video_ids), batch_size):
            batch = unique_video_ids[i:i+batch_size]
            print(f"处理第 {i//batch_size + 1} 批，共 {len(batch)} 个视频")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 将每个视频ID分配给线程池，添加skip_exists参数
                future_to_bvid = {
                    executor.submit(get_video_info_sync, bvid, cookie, skip_exists): bvid
                    for bvid in batch
                }
                
                for future in concurrent.futures.as_completed(future_to_bvid):
                    bvid = future_to_bvid[future]
                    try:
                        result = future.result()
                        if result is None:  # 跳过的视频
                            continue
                        if result.status == "success":
                            results.append(result)
                            print(f"成功获取视频 {bvid} 的详情: {result.data.get('title', '')}")
                        else:
                            print(f"获取视频 {bvid} 的详情失败: {result.message}")
                    except Exception as e:
                        print(f"处理视频 {bvid} 时出错: {e}")
            
            # 每批处理完后，批量保存到数据库
            if results:
                print(f"开始批量保存第 {i//batch_size + 1} 批视频详情...")
                batch_result = batch_save_video_details(results)
                total_success = batch_result["success"]
                total_fail = batch_result["fail"]
                
                # 合并错误统计
                if "error_stats" in batch_result:
                    for error_type, count in batch_result["error_stats"].items():
                        if error_type not in error_stats:
                            error_stats[error_type] = 0
                        error_stats[error_type] += count
                
                print(f"批次完成: 成功 {batch_result['success']}，失败 {batch_result['fail']}")
                results = []  # 清空结果列表，准备下一批
                
            # 批次之间稍微暂停，减轻服务器压力
            time.sleep(1)  # 减少暂停时间
    elif all_video_ids:
        print(f"\n跳过视频详情获取 (process_video_details={process_video_details})")
        print(f"如需获取视频详情，请使用/fetch/video-details-stats和/fetch/fetch-video-details接口")

    return all_new_data

async def fetch_history(output_dir: str = "history_by_date", skip_exists: bool = False, process_video_details: bool = False) -> dict:
    """主函数：获取B站历史记录并同时获取视频详细信息存入视频库"""
    try:
        # 重新加载配置文件，确保获取最新的SESSDATA
        current_config = load_config()
        
        # 修改这里：直接使用 output_dir 而不是拼接 output 路径
        full_output_dir = get_output_path(output_dir)  # 这里 get_output_path 已经会添加 output 前缀
        
        print("\n=== 路径信息 ===")
        print(f"输出目录: {full_output_dir}")
        print(f"目录存在: {os.path.exists(full_output_dir)}")
        
        cookie = current_config.get('SESSDATA', '')
        if not cookie:
            return {"status": "error", "message": "未找到SESSDATA配置"}

        latest_date = find_latest_local_history(output_dir)  # 传入相对路径
        # 由于fetch_and_compare_history现在是异步函数，需要使用await调用
        new_history = await fetch_and_compare_history(cookie, latest_date, skip_exists, process_video_details)

        result = {"status": "success", "message": "没有新记录需要更新", "data": {}}
        if new_history:
            save_result = save_history(new_history, output_dir)  # 传入相对路径
            result = save_result
            
            # 如果需要处理视频详情
            if process_video_details and save_result["status"] == "success":
                print("\n=== 开始处理新记录的视频详情 ===")
                
                # 获取所有新记录的bvid
                new_bvids = []
                for date, records in new_history.items():
                    for record in records:
                        if record.get("bvid"):
                            new_bvids.append(record["bvid"])
                
                print(f"新记录中包含 {len(new_bvids)} 个视频ID")
                
                # 调用获取视频详情的函数
                if new_bvids:
                    video_details_result = await fetch_video_details_only(specific_videos=new_bvids)
                    result["video_details_result"] = video_details_result
                    
                    if video_details_result["status"] == "success":
                        print("成功获取新记录的视频详情")
        else:
                        print(f"获取新记录的视频详情时出错: {video_details_result['message']}")
        
        return result

    except Exception as e:
        logging.error(f"获取历史记录时发生错误: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}

# 新增: 批量获取历史记录中的视频详情但不重新获取历史记录
async def fetch_video_details_only(max_videos: int = 0, specific_videos: list = None) -> dict:
    """
    从历史记录中获取视频ID，批量获取视频详情
    
    Args:
        max_videos: 本次最多处理的视频数量，0表示不限制
        specific_videos: 指定要获取的视频ID列表，如果提供则优先使用这个列表
    """
    try:
        # 确保参数是合法整数
        if max_videos is None:
            max_videos = 0
            
        print("\n=== 开始批量获取视频详情 ===")
        
        # 获取cookie
        current_config = load_config()
        cookie = current_config.get('SESSDATA', '')
        if not cookie:
            return {"status": "error", "message": "未找到SESSDATA配置"}
            
        # 如果没有指定视频列表，则自动获取待处理视频
        if not specific_videos:
            # 获取统计数据，包含待获取视频列表
            stats = await get_video_details_stats()
            if stats["status"] != "success":
                return stats
                
            # 获取待处理视频列表
            videos_to_fetch = stats["data"]["pending_videos"]
            total_videos_to_fetch = len(videos_to_fetch)
            
            if total_videos_to_fetch == 0:
                return {"status": "success", "message": "所有历史记录的视频详情都已获取", "data": {"skipped": True, "processed": 0}}
        else:
            # 使用指定的视频列表
            videos_to_fetch = specific_videos
            total_videos_to_fetch = len(videos_to_fetch)
            print(f"使用指定的视频列表，共 {total_videos_to_fetch} 个视频")
        
        # 限制每次处理的视频数量
        if max_videos > 0 and len(videos_to_fetch) > max_videos:
            print(f"限制处理的视频数量为 {max_videos} 个(总共 {total_videos_to_fetch} 个待处理)")
            videos_to_fetch = videos_to_fetch[:max_videos]
            
        print(f"本次将处理 {len(videos_to_fetch)} 个视频")
        
        # 降低并发线程数，避免过高并发导致412错误
        max_workers = min(15, len(videos_to_fetch))  # 最大15个线程
        total_success = 0
        total_fail = 0
        skipped_invalid_count = 0
        
        # 初始化错误统计
        error_stats = {
            "404_not_found": 0,      # 视频不存在或已删除
            "62002_invisible": 0,    # 视频已设为私有或被隐藏
            "412_banned": 0,         # 请求被禁止/拒绝
            "decode_error": 0,       # 解码错误
            "parse_error": 0,        # JSON解析错误
            "empty_data": 0,         # 数据为空
            "save_error": 0,         # 保存过程出错
            "other_error": 0         # 其他错误
        }
        
        # 存储错误视频信息
        error_videos = []
        
        # 分批处理，进一步减小每批的大小
        batch_size = 20  # 确保每批最多20个
        
        # 随机打乱视频顺序，避免按顺序请求被检测
        random.shuffle(videos_to_fetch)
        
        start_time = time.time()
        
        for i in range(0, len(videos_to_fetch), batch_size):
            batch = videos_to_fetch[i:i+batch_size]
            batch_num = i//batch_size + 1
            total_batches = (len(videos_to_fetch)-1)//batch_size + 1
            print(f"处理第 {batch_num}/{total_batches} 批，共 {len(batch)} 个视频")
            
            results = []
            batch_success = 0
            batch_fail = 0
            batch_skipped = 0
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_bvid = {
                    executor.submit(get_video_info_sync, bvid, cookie, False): bvid
                    for bvid in batch
                }
                
                for future in concurrent.futures.as_completed(future_to_bvid):
                    bvid = future_to_bvid[future]
                    try:
                        result = future.result()
                        
                        # 检查是否为已知失效视频
                        if result and hasattr(result, 'is_known_invalid') and result.is_known_invalid:
                            batch_skipped += 1
                            skipped_invalid_count += 1
                            print(f"跳过已知失效视频 {bvid}")
                            continue
                            
                        if result and result.status == "success":
                            results.append(result)
                            batch_success += 1
                            print(f"成功获取视频 {bvid} 的详情: {result.data.get('title', '')}")
                        else:
                            batch_fail += 1
                            error_msg = result.message if result and hasattr(result, 'message') else "未知错误"
                            error_type = result.error_type if result and hasattr(result, 'error_type') else "unknown"
                            print(f"获取视频 {bvid} 的详情失败: {error_msg}, 类型: {error_type}")
                            
                            # 添加到错误视频列表
                            error_videos.append({
                                "bvid": bvid,
                                "error_type": error_type,
                                "error_message": error_msg
                            })
                    except Exception as e:
                        batch_fail += 1
                        print(f"处理视频 {bvid} 时出错: {e}")
                        # 添加到错误视频列表
                        error_videos.append({
                            "bvid": bvid,
                            "error_type": "exception",
                            "error_message": str(e)
                        })
            
            # 批量保存结果
            if results:
                batch_result = batch_save_video_details(results)
                total_success += batch_result["success"]
                total_fail += batch_result["fail"] + (batch_fail - batch_result.get("invalid", 0))
                
                # 合并错误统计
                if "error_stats" in batch_result:
                    for error_type, count in batch_result["error_stats"].items():
                        if error_type in error_stats:
                            error_stats[error_type] += count
                
                print(f"批次完成: 成功 {batch_result['success']}，失败 {batch_result['fail']}，跳过 {batch_skipped}")
            else:
                print(f"批次完成: 没有成功获取的视频，跳过 {batch_skipped}")
                total_fail += batch_fail
            
            # 计算进度
            processed_videos = i + len(batch)
            progress_percentage = (processed_videos / len(videos_to_fetch)) * 100
            elapsed_time = time.time() - start_time
            
            print(f"进度: {processed_videos}/{len(videos_to_fetch)} ({progress_percentage:.2f}%)，耗时: {elapsed_time:.2f}秒")
            
            # 批次之间暂停时间增加并随机化
            batch_delay = 3 + random.random() * 4  # 3-7秒随机延迟
            print(f"批次间暂停 {batch_delay:.2f} 秒...")
            time.sleep(batch_delay)
            
            # 如果失败太多，提前停止
            if total_fail > 5 * total_success and total_fail > 10:
                print(f"失败过多 (成功:{total_success}，失败:{total_fail})，提前停止任务")
                break
        
        # 计算总耗时
        total_elapsed_time = time.time() - start_time
        
        # 打印最终错误统计
        if total_fail > 0:
            print("\n=== 错误类型统计 ===")
            for error_type, count in error_stats.items():
                if count > 0:
                    percentage = (count/total_fail*100) if total_fail > 0 else 0
                    print(f"- {error_type}: {count}次 ({percentage:.1f}%)")
        
        # 获取剩余未处理的视频数量
        remaining_videos = total_videos_to_fetch - len(videos_to_fetch)
        
        # 如果使用的是指定视频列表，则不考虑剩余视频
        if specific_videos:
            remaining_videos = 0
            
        # 返回处理结果
        return {
            "status": "success", 
            "message": f"批量获取视频详情完成，成功: {total_success}，失败: {total_fail}，跳过: {skipped_invalid_count}",
            "data": {
                "total_videos": total_videos_to_fetch,
                "processed_videos": len(videos_to_fetch),
                "success_count": total_success,
                "fail_count": total_fail,
                "skipped_invalid_count": skipped_invalid_count,
                "remaining_videos": remaining_videos,
                "elapsed_time": total_elapsed_time,
                "error_stats": error_stats,
                "error_videos": error_videos[:20]  # 只返回前20个错误，避免响应过大
            }
        }
        
    except Exception as e:
        error_msg = f"批量获取视频详情时出错: {str(e)}"
        print(error_msg)
        import traceback
        print(traceback.format_exc())
        return {"status": "error", "message": error_msg}

async def get_invalid_videos_from_db(page=1, limit=50, error_type=None):
    """从数据库中获取失效视频列表"""
    try:
        # 连接数据库
        db_path = get_output_path("video_library.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # 启用字典游标
        cursor = conn.cursor()
        
        # 构建查询条件
        query_params = []
        where_clause = ""
        
        if error_type:
            where_clause = "WHERE error_type = ?"
            query_params.append(error_type)
        
        # 获取总数
        count_sql = f"""
            SELECT COUNT(*) as total FROM invalid_videos {where_clause}
        """
        cursor.execute(count_sql, query_params)
        total = cursor.fetchone()["total"]
        
        # 计算分页
        offset = (page - 1) * limit
        
        # 查询当前页数据
        select_sql = f"""
            SELECT 
                id, bvid, error_type, error_code, error_message, 
                first_check_time, last_check_time, check_count
            FROM invalid_videos
            {where_clause}
            ORDER BY last_check_time DESC
            LIMIT ? OFFSET ?
        """
        
        query_params.extend([limit, offset])
        cursor.execute(select_sql, query_params)
        
        rows = cursor.fetchall()
        
        # 转换为列表
        items = []
        for row in rows:
            items.append(dict(row))
            
        conn.close()
        
        # 返回分页结果
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": total > page * limit,
            "items": items
        }
    except Exception as e:
        print(f"获取失效视频列表失败: {e}")
        import traceback
        print(traceback.format_exc())
        raise e

## 新增: 获取视频详情统计数据
async def get_video_details_stats() -> dict:
    """
    获取视频详情的统计数据
    返回历史记录总数、已获取视频数、失效视频数、未获取视频数等信息
    """
    try:
        print("\n=== 获取视频详情统计数据 ===")
        
        # 查询数据库中已有的历史记录，但尚未获取详情的视频
        history_db_path = get_output_path("bilibili_history.db")
        video_db_path = get_output_path("video_library.db")
        
        # 查询历史记录数据库中的所有bvid
        conn_history = sqlite3.connect(history_db_path)
        cursor_history = conn_history.cursor()
        
        print("查询历史记录数据库中的视频ID...")
        
        # 首先获取所有年份的表
        cursor_history.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name LIKE 'bilibili_history_%'
        """)
        
        history_tables = cursor_history.fetchall()
        
        if not history_tables:
            return {"status": "error", "message": "未找到历史记录表", "data": None}
            
        print(f"找到以下历史记录表: {[table[0] for table in history_tables]}")
        
        # 构建查询所有年份表的UNION查询
        all_bvids = []
        for table in history_tables:
            table_name = table[0]
            cursor_history.execute(f"""
                SELECT DISTINCT bvid FROM {table_name} 
                WHERE bvid IS NOT NULL AND bvid != ''
            """)
            bvids = [row[0] for row in cursor_history.fetchall()]
            all_bvids = list(set(all_bvids + bvids))
            print(f"从表 {table_name} 中找到 {len(bvids)} 个视频ID")
        
        conn_history.close()
        
        total_history_videos = len(all_bvids)
        print(f"历史记录数据库中总共找到 {total_history_videos} 个不同的视频ID")
        
        # 查询视频库中已有的bvid
        conn_video = sqlite3.connect(video_db_path)
        cursor_video = conn_video.cursor()
        
        # 获取已存储详情的视频ID
        try:
            cursor_video.execute("SELECT bvid FROM video_details")
            existing_bvids = {row[0] for row in cursor_video.fetchall()}
            existing_videos_count = len(existing_bvids)
        except sqlite3.OperationalError:
            # 如果表不存在
            existing_bvids = set()
            existing_videos_count = 0
        
        # 获取失效视频ID
        try:
            cursor_video.execute("SELECT bvid FROM invalid_videos")
            invalid_bvids = {row[0] for row in cursor_video.fetchall()}
            invalid_videos_count = len(invalid_bvids)
        except sqlite3.OperationalError:
            # 如果表不存在
            invalid_bvids = set()
            invalid_videos_count = 0
            
        # 按错误类型统计失效视频
        error_type_stats = {}
        try:
            cursor_video.execute("""
                SELECT error_type, COUNT(*) as count 
                FROM invalid_videos 
                GROUP BY error_type
            """)
            for row in cursor_video.fetchall():
                error_type_stats[row[0]] = row[1]
        except sqlite3.OperationalError:
            # 如果表不存在
            pass
            
        conn_video.close()
        
        # 找出需要获取详情的视频ID (排除已获取和已知失效的)
        videos_to_fetch = [bvid for bvid in all_bvids if bvid not in existing_bvids and bvid not in invalid_bvids]
        pending_videos_count = len(videos_to_fetch)
        
        print(f"\n=== 视频详情统计 ===")
        print(f"历史记录总视频数: {total_history_videos}")
        print(f"已获取详情视频数: {existing_videos_count}")
        print(f"已知失效视频数: {invalid_videos_count}")
        print(f"待获取视频数: {pending_videos_count}")
        
        completion_percentage = ((existing_videos_count + invalid_videos_count) / total_history_videos) * 100 if total_history_videos > 0 else 0
        
        # 返回统计结果
        return {
            "status": "success",
            "message": "成功获取视频详情统计数据",
            "data": {
                "total_history_videos": total_history_videos,       # 历史记录总视频数
                "existing_videos_count": existing_videos_count,     # 已获取详情的视频数
                "invalid_videos_count": invalid_videos_count,       # 已知失效的视频数
                "pending_videos_count": pending_videos_count,       # 待获取的视频数
                "completion_percentage": round(completion_percentage, 2),  # 完成百分比
                "error_type_stats": error_type_stats,               # 失效视频类型统计
                "pending_videos": videos_to_fetch                   # 待获取的视频ID列表
            }
        }
        
    except Exception as e:
        error_msg = f"获取视频详情统计数据时出错: {str(e)}"
        print(error_msg)
        import traceback
        print(traceback.format_exc())
        return {"status": "error", "message": error_msg, "data": None}
