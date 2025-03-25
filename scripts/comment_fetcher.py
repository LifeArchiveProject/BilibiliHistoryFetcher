import json
import os
import sqlite3
import time
from datetime import datetime
from typing import Dict, List

import requests


def create_comments_table(connection):
    """创建评论表"""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS comments (
        rpid TEXT PRIMARY KEY,
        uid TEXT NOT NULL,
        message TEXT NOT NULL,
        time INTEGER NOT NULL,
        rank INTEGER NOT NULL,
        rootid TEXT,
        parentid TEXT,
        oid TEXT NOT NULL,
        type INTEGER NOT NULL,
        fetch_time INTEGER NOT NULL
    );
    """
    
    create_indexes = [
        "CREATE INDEX IF NOT EXISTS idx_comments_uid ON comments (uid);",
        "CREATE INDEX IF NOT EXISTS idx_comments_time ON comments (time);",
        "CREATE INDEX IF NOT EXISTS idx_comments_fetch_time ON comments (fetch_time);"
    ]
    
    # 创建用户表
    create_users_table_sql = """
    CREATE TABLE IF NOT EXISTS comment_users (
        uid TEXT PRIMARY KEY,
        first_fetch_time INTEGER NOT NULL,
        last_fetch_time INTEGER NOT NULL
    );
    """
    
    try:
        cursor = connection.cursor()
        cursor.execute(create_table_sql)
        
        # 创建索引
        for index_sql in create_indexes:
            cursor.execute(index_sql)
            
        # 创建用户表
        cursor.execute(create_users_table_sql)
            
        connection.commit()
        print("评论表和用户表创建成功")
    except Exception as e:
        print(f"创建表时发生错误: {e}")
        raise

def check_user_exists(connection, uid: str) -> bool:
    """检查用户是否存在于用户表中"""
    query = "SELECT 1 FROM comment_users WHERE uid = ?"
    cursor = connection.cursor()
    cursor.execute(query, (uid,))
    return cursor.fetchone() is not None

def update_user_record(connection, uid: str):
    """更新或插入用户记录"""
    current_time = int(time.time())
    
    # 先检查用户是否存在
    if check_user_exists(connection, uid):
        # 更新最后获取时间
        update_sql = """
        UPDATE comment_users 
        SET last_fetch_time = ? 
        WHERE uid = ?
        """
        connection.cursor().execute(update_sql, (current_time, uid))
    else:
        # 插入新用户记录
        insert_sql = """
        INSERT INTO comment_users (uid, first_fetch_time, last_fetch_time) 
        VALUES (?, ?, ?)
        """
        connection.cursor().execute(insert_sql, (uid, current_time, current_time))
    
    connection.commit()
    print(f"用户记录 {uid} 已更新")

def fetch_comments(uid: str, mode: str = "0", keyword: str = "") -> List[Dict]:
    """获取用户评论数据"""
    base_url = "https://api.aicu.cc/api/v3/search/getreply"
    all_replies = []
    page = 1
    page_size = 500  # 使用最大页面大小
    
    while True:
        params = {
            "uid": uid,
            "pn": str(page),
            "ps": str(page_size),
            "mode": mode,
            "keyword": keyword
        }
        
        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data["code"] != 0:
                print(f"API返回错误: {data['message']}")
                break
                
            replies = data["data"]["replies"]
            if not replies:
                break
                
            all_replies.extend(replies)
            
            if data["data"]["cursor"]["is_end"]:
                break
                
            page += 1
            time.sleep(1)  # 添加延迟避免请求过快
            
        except Exception as e:
            print(f"获取评论数据时发生错误: {e}")
            break
    
    return all_replies

def save_comments_to_file(uid: str, comments: List[Dict]):
    """保存评论数据到JSON文件"""
    timestamp = int(time.time())
    output_dir = os.path.join("output", "comment", uid)
    os.makedirs(output_dir, exist_ok=True)
    
    file_path = os.path.join(output_dir, f"{timestamp}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(comments, f, ensure_ascii=False, indent=2)
    print(f"评论数据已保存到: {file_path}")
    
    return file_path

def create_connection():
    """创建SQLite数据库连接"""
    try:
        db_path = os.path.join("output", "database")
        os.makedirs(db_path, exist_ok=True)
        db_file = os.path.join(db_path, "bilibili_comments.db")
        
        conn = sqlite3.connect(db_file)
        print(f"成功连接到评论数据库: {db_file}")
        return conn
    except sqlite3.Error as e:
        print(f"连接数据库时发生错误: {e}")
        raise

def insert_comments_to_db(connection, comments: List[Dict], uid: str):
    """将评论数据插入到数据库"""
    insert_sql = """
    INSERT OR REPLACE INTO comments (
        rpid, uid, message, time, rank, rootid, parentid, oid, type, fetch_time
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    fetch_time = int(time.time())
    data_to_insert = []
    
    for comment in comments:
        parent = comment.get("parent", {})
        dyn = comment.get("dyn", {})
        
        record = (
            comment["rpid"],
            uid,
            comment["message"],
            comment["time"],
            comment["rank"],
            parent.get("rootid"),
            parent.get("parentid"),
            str(dyn.get("oid", 0)),  # 转换为字符串
            dyn.get("type", 0),
            fetch_time
        )
        data_to_insert.append(record)
    
    if data_to_insert:
        cursor = connection.cursor()
        try:
            cursor.executemany(insert_sql, data_to_insert)
            connection.commit()
            print(f"成功插入 {len(data_to_insert)} 条评论数据")
        except sqlite3.Error as e:
            connection.rollback()
            print(f"插入数据时发生错误: {e}")

def fetch_and_save_comments(uid: str, mode: str = "0", keyword: str = ""):
    """获取并保存用户评论数据"""
    # 获取评论数据
    comments = fetch_comments(uid, mode, keyword)
    
    # 创建数据库连接
    connection = create_connection()
    try:
        create_comments_table(connection)
        
        # 无论是否获取到评论，都更新用户记录
        update_user_record(connection, uid)
        
        if not comments:
            print("未获取到评论数据")
            return {
                "message": "未获取到评论数据",
                "total_count": 0,
                "latest_comment_time": None
            }
        
        # 保存到文件
        save_comments_to_file(uid, comments)
        
        # 保存到数据库
        insert_comments_to_db(connection, comments, uid)
    finally:
        connection.close()
    
    # 获取最新评论时间（第一条数据的时间）
    latest_time = comments[0]["time"]
    # 转换为北京时间
    latest_time_str = datetime.fromtimestamp(latest_time).strftime("%Y-%m-%d %H:%M:%S")
    
    return {
        "message": "评论数据获取成功",
        "total_count": len(comments),
        "latest_comment_time": latest_time_str
    }

def query_comments(connection, uid: str, page: int = 1, page_size: int = 20, 
                  comment_type: str = "all", keyword: str = "", comment_type_filter: int = None) -> Dict:
    """
    查询用户评论数据
    
    Args:
        connection: 数据库连接
        uid: 用户ID
        page: 页码，从1开始
        page_size: 每页数量
        comment_type: 评论类型，可选值：all（全部）, root（一级评论）, reply（二级评论）
        keyword: 关键词，用于模糊匹配评论内容
        comment_type_filter: 评论类型筛选(type字段)，例如：1(视频评论)，17(动态评论)等
        
    Returns:
        dict: 包含评论列表和总数的字典
    """
    # 构建基础查询条件
    conditions = ["uid = ?"]
    params = [uid]
    
    # 添加评论类型条件
    if comment_type == "root":
        conditions.append("parentid IS NULL")
    elif comment_type == "reply":
        conditions.append("parentid IS NOT NULL")
    
    # 添加评论类型筛选条件
    if comment_type_filter is not None:
        conditions.append("type = ?")
        params.append(comment_type_filter)
    
    # 添加关键词条件
    if keyword:
        conditions.append("message LIKE ?")
        params.append(f"%{keyword}%")
    
    # 构建WHERE子句
    where_clause = " AND ".join(conditions)
    
    # 计算总数
    count_sql = f"""
    SELECT COUNT(*) FROM comments WHERE {where_clause}
    """
    cursor = connection.cursor()
    cursor.execute(count_sql, params)
    total_count = cursor.fetchone()[0]
    
    # 计算偏移量
    offset = (page - 1) * page_size
    
    # 构建查询SQL
    query_sql = f"""
    SELECT rpid, uid, message, time, rank, rootid, parentid, oid, type, fetch_time
    FROM comments 
    WHERE {where_clause}
    ORDER BY time DESC
    LIMIT ? OFFSET ?
    """
    
    # 添加分页参数
    params.extend([page_size, offset])
    
    # 执行查询
    cursor.execute(query_sql, params)
    rows = cursor.fetchall()
    
    # 转换结果为字典列表
    comments = []
    for row in rows:
        comment = {
            "rpid": row[0],
            "uid": row[1],
            "message": row[2],
            "time": row[3],
            "rank": row[4],
            "rootid": row[5],
            "parentid": row[6],
            "oid": row[7],  # 已经是字符串了
            "type": row[8],
            "fetch_time": row[9]
        }
        # 转换时间戳为可读时间（直接转换，不需要加8小时）
        comment["time_str"] = datetime.fromtimestamp(comment["time"]).strftime("%Y-%m-%d %H:%M:%S")
        comment["fetch_time_str"] = datetime.fromtimestamp(comment["fetch_time"]).strftime("%Y-%m-%d %H:%M:%S")
        comments.append(comment)
    
    return {
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size,
        "comments": comments
    }

def get_user_comments(uid: str, page: int = 1, page_size: int = 20, 
                      comment_type: str = "all", keyword: str = "", comment_type_filter: int = None) -> Dict:
    """
    获取用户评论，如果用户不存在则先获取数据
    
    Args:
        uid: 用户ID
        page: 页码，从1开始
        page_size: 每页数量
        comment_type: 评论类型，可选值：all（全部）, root（一级评论）, reply（二级评论）
        keyword: 关键词，用于模糊匹配评论内容
        comment_type_filter: 评论类型筛选(type字段)，例如：1(视频评论)，17(动态评论)等
        
    Returns:
        dict: 包含评论列表和总数的字典
    """
    connection = create_connection()
    try:
        create_comments_table(connection)
        
        # 检查用户是否存在
        if not check_user_exists(connection, uid):
            print(f"用户 {uid} 不存在，先获取数据")
            connection.close()  # 先关闭当前连接
            
            # 获取用户评论数据
            fetch_and_save_comments(uid)
            
            # 重新连接数据库
            connection = create_connection()
        
        # 查询评论数据
        result = query_comments(
            connection=connection,
            uid=uid,
            page=page,
            page_size=page_size,
            comment_type=comment_type,
            keyword=keyword,
            comment_type_filter=comment_type_filter
        )
        return result
    finally:
        connection.close()

if __name__ == "__main__":
    # 示例使用
    uid = "17497789"  # 替换为实际的用户ID
    result = get_user_comments(uid)
    print(f"获取结果: {result}") 