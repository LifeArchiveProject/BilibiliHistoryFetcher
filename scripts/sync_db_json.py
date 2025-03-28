import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime

# 配置日志
# 确保输出目录存在
os.makedirs("output/check", exist_ok=True)

# 设置自定义的日志格式化器，以正确处理中文字符
class EncodingFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        # 确保返回的是原始字符串，不会被转义
        if isinstance(msg, str):
            return msg
        else:
            return str(msg)

# 配置日志处理程序
formatter = EncodingFormatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler("output/check/sync_db_json.log", mode='a', encoding='utf-8')
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.handlers = []  # 清除可能存在的处理程序
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.propagate = False  # 防止日志消息传播到根日志器


def get_json_files(json_root_path):
    """获取所有JSON文件的路径"""
    json_files = []
    
    for year_dir in os.listdir(json_root_path):
        year_path = os.path.join(json_root_path, year_dir)
        if not os.path.isdir(year_path) or not year_dir.isdigit():
            continue
            
        for month_dir in os.listdir(year_path):
            month_path = os.path.join(year_path, month_dir)
            if not os.path.isdir(month_path) or not month_dir.isdigit():
                continue
                
            for day_file in os.listdir(month_path):
                if not day_file.endswith('.json'):
                    continue
                    
                day_path = os.path.join(month_path, day_file)
                json_files.append({
                    'path': day_path,
                    'year': int(year_dir),
                    'month': int(month_dir),
                    'day': int(day_file.split('.')[0])
                })
    
    return json_files


def get_db_tables(db_path):
    """获取数据库中的所有表名"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables
    except Exception as e:
        logger.error(f"获取数据库表时出错: {e}")
        return []


def load_json_file(file_path):
    """读取JSON文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"读取JSON文件 {file_path} 时出错: {e}")
        return []


def save_json_file(file_path, data):
    """保存JSON文件"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # 备份原文件（如果存在）
        if os.path.exists(file_path):
            backup_dir = os.path.join('output', 'check', 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            
            file_name = os.path.basename(file_path)
            backup_path = os.path.join(backup_dir, f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_name}")
            shutil.copy2(file_path, backup_path)
            logger.info(f"原文件已备份到 {backup_path}")
        
        # 保存新文件
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"数据已保存到 {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存JSON文件 {file_path} 时出错: {e}")
        return False


def get_records_from_db(db_path, year, month, day):
    """从db中获取某天的所有记录并转换成JSON格式"""
    try:
        # 计算目标日期的时间戳范围
        start_date = datetime(year, month, day).timestamp()
        end_date = datetime(year, month, day, 23, 59, 59).timestamp()
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # 将结果转换为字典格式
        cursor = conn.cursor()
        
        # 获取当天所有记录
        table_name = f"bilibili_history_{year}"
        cursor.execute(f"""
            SELECT * FROM {table_name} 
            WHERE view_at >= ? AND view_at <= ?
            ORDER BY view_at DESC
        """, (start_date, end_date))
        
        records = cursor.fetchall()
        records_list = [dict(record) for record in records]
        conn.close()
        
        # 将数据库记录转换为JSON格式
        json_records = []
        for record in records_list:
            json_record = {
                "title": record["title"],
                "long_title": record["long_title"],
                "cover": record["cover"],
                "covers": json.loads(record["covers"]) if record["covers"] else None,
                "uri": record["uri"],
                "history": {
                    "oid": record["oid"],
                    "epid": record["epid"],
                    "bvid": record["bvid"],
                    "page": record["page"],
                    "cid": record["cid"],
                    "part": record["part"],
                    "business": record["business"],
                    "dt": record["dt"]
                },
                "videos": record["videos"],
                "author_name": record["author_name"],
                "author_face": record["author_face"],
                "author_mid": record["author_mid"],
                "view_at": record["view_at"],
                "progress": record["progress"],
                "badge": record["badge"],
                "show_title": record["show_title"],
                "duration": record["duration"],
                "current": record["current"],
                "total": record["total"],
                "new_desc": record["new_desc"],
                "is_finish": record["is_finish"],
                "is_fav": record["is_fav"],
                "kid": record["kid"],
                "tag_name": record["tag_name"],
                "live_status": record["live_status"]
            }
            json_records.append(json_record)
            
        logger.info(f"从数据库中获取了 {len(json_records)} 条 {year}年{month}月{day}日的记录")
        return json_records
    
    except Exception as e:
        logger.error(f"从数据库获取记录时出错: {e}")
        return []


def import_records_to_db(db_path, records, year):
    """将记录导入到数据库"""
    if not records:
        return 0
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查表是否存在
        table_name = f"bilibili_history_{year}"
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not cursor.fetchone():
            logger.error(f"数据库表 {table_name} 不存在")
            conn.close()
            return 0
        
        # 获取表结构
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [column[1] for column in cursor.fetchall()]
        
        imported_count = 0
        for record in records:
            # 检查记录是否已存在
            view_at = record.get('view_at', 0)
            bvid = record.get('history', {}).get('bvid', '')
            
            cursor.execute(f"SELECT id FROM {table_name} WHERE view_at = ? AND bvid = ?", (view_at, bvid))
            if cursor.fetchone():
                logger.debug(f"记录已存在: {record.get('title')} ({bvid}, {view_at})")
                continue
            
            # 构建导入数据
            data = {
                "id": None,  # 自增字段
                "title": record.get('title', ''),
                "long_title": record.get('long_title', ''),
                "cover": record.get('cover', ''),
                "covers": json.dumps(record.get('covers', [])),
                "uri": record.get('uri', ''),
                "oid": record.get('history', {}).get('oid', 0),
                "epid": record.get('history', {}).get('epid', 0),
                "bvid": record.get('history', {}).get('bvid', ''),
                "page": record.get('history', {}).get('page', 1),
                "cid": record.get('history', {}).get('cid', 0),
                "part": record.get('history', {}).get('part', ''),
                "business": record.get('history', {}).get('business', ''),
                "dt": record.get('history', {}).get('dt', 0),
                "videos": record.get('videos', 1),
                "author_name": record.get('author_name', ''),
                "author_face": record.get('author_face', ''),
                "author_mid": record.get('author_mid', 0),
                "view_at": view_at,
                "progress": record.get('progress', 0),
                "badge": record.get('badge', ''),
                "show_title": record.get('show_title', ''),
                "duration": record.get('duration', 0),
                "current": record.get('current', ''),
                "total": record.get('total', 0),
                "new_desc": record.get('new_desc', ''),
                "is_finish": record.get('is_finish', 0),
                "is_fav": record.get('is_fav', 0),
                "kid": record.get('kid', 0),
                "tag_name": record.get('tag_name', ''),
                "live_status": record.get('live_status', 0),
                "main_category": None  # 默认为Null
            }
            
            # 生成SQL语句
            valid_columns = [col for col in data.keys() if col in columns]
            placeholders = ', '.join(['?' for _ in valid_columns])
            sql = f"INSERT INTO {table_name} ({', '.join(valid_columns)}) VALUES ({placeholders})"
            
            # 导入数据
            values = [data[col] for col in valid_columns]
            cursor.execute(sql, values)
            imported_count += 1
        
        conn.commit()
        conn.close()
        logger.info(f"成功导入 {imported_count} 条记录到表 {table_name}")
        return imported_count
        
    except Exception as e:
        logger.error(f"导入记录到数据库时出错: {e}")
        return 0


def sync_json_to_db(db_path, json_root_path):
    """将JSON文件中的记录导入到数据库"""
    json_files = get_json_files(json_root_path)
    total_imported = 0
    synced_days = []
    
    for json_file in json_files:
        year, month, day = json_file['year'], json_file['month'], json_file['day']
        file_path = json_file['path']
        
        # 读取JSON文件
        json_records = load_json_file(file_path)
        if not json_records:
            continue
            
        # 导入记录到数据库
        imported_count = import_records_to_db(db_path, json_records, year)
        total_imported += imported_count
        
        if imported_count > 0:
            # 记录已导入的日期和标题信息
            imported_titles = [record.get('title', '未知标题') for record in json_records[:10]]  # 最多记录10个标题
            synced_days.append({
                "date": f"{year}-{month:02d}-{day:02d}",
                "imported_count": imported_count,
                "source": "json_to_db",
                "titles": imported_titles if len(imported_titles) <= 10 else imported_titles[:10]
            })
            logger.info(f"从 {file_path} 导入了 {imported_count} 条记录到数据库")
    
    return total_imported, synced_days


def sync_db_to_json(db_path, json_root_path):
    """将数据库中的记录导入到JSON文件"""
    # 获取数据库中的表名
    db_tables = get_db_tables(db_path)
    history_tables = [table for table in db_tables if table.startswith('bilibili_history_')]
    
    total_restored = 0
    synced_days = []
    
    # 获取JSON文件列表
    json_files = get_json_files(json_root_path)
    json_file_dict = {}
    
    # 构建日期的路径到文件的映射制式
    for file_info in json_files:
        key = f"{file_info['year']}-{file_info['month']}-{file_info['day']}"
        json_file_dict[key] = file_info['path']
    
    # 遍历数据库中的表
    for table in history_tables:
        year = int(table.split('_')[-1])
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 获取表中的不同日期的记录
            cursor.execute(f"""
                SELECT strftime('%Y-%m-%d', datetime(view_at, 'unixepoch')) as date_str,
                       strftime('%Y', datetime(view_at, 'unixepoch')) as year,
                       strftime('%m', datetime(view_at, 'unixepoch')) as month,
                       strftime('%d', datetime(view_at, 'unixepoch')) as day
                FROM {table}
                GROUP BY date_str
                ORDER BY date_str
            """)
            dates = cursor.fetchall()
            conn.close()
            
            for date in dates:
                date_str, db_year, db_month, db_day = date
                db_year, db_month, db_day = int(db_year), int(db_month), int(db_day)
                
                # 构建日期的路径
                json_path = json_file_dict.get(date_str)
                if not json_path:
                    # 如果日期的路径不存在，创建JSON文件
                    json_path = os.path.join(json_root_path, str(db_year), f"{db_month:02d}", f"{db_day:02d}.json")
                
                # 从数据库中获取日期的记录
                db_records = get_records_from_db(db_path, db_year, db_month, db_day)
                
                # 如果日期的JSON文件存在，合成记录
                if os.path.exists(json_path):
                    json_records = load_json_file(json_path)
                    
                    # 判除重复的记录
                    existing_keys = set((record.get('view_at', 0), record.get('history', {}).get('bvid', '')) 
                                       for record in json_records)
                    
                    # 获取数据库中的新记录
                    new_records = []
                    for db_record in db_records:
                        key = (db_record.get('view_at', 0), db_record.get('history', {}).get('bvid', ''))
                        if key not in existing_keys:
                            new_records.append(db_record)
                            existing_keys.add(key)
                    
                    # 合成记录
                    if new_records:
                        combined_records = json_records + new_records
                        # 按时间进行排列
                        combined_records.sort(key=lambda x: x.get('view_at', 0), reverse=True)
                        if save_json_file(json_path, combined_records):
                            # 记录同步信息
                            titles = [record.get('title', '未知标题') for record in new_records[:10]]
                            synced_days.append({
                                "date": f"{db_year}-{db_month:02d}-{db_day:02d}",
                                "imported_count": len(new_records),
                                "source": "db_to_json",
                                "titles": titles if len(titles) <= 10 else titles[:10]
                            })
                            logger.info(f"已新增 {json_path} 了 {len(new_records)} 条记录")
                            total_restored += len(new_records)
                else:
                    # 日期的JSON文件不存在，创建JSON文件
                    if db_records and save_json_file(json_path, db_records):
                        # 记录同步信息
                        titles = [record.get('title', '未知标题') for record in db_records[:10]]
                        synced_days.append({
                            "date": f"{db_year}-{db_month:02d}-{db_day:02d}",
                            "imported_count": len(db_records),
                            "source": "db_to_json",
                            "titles": titles if len(titles) <= 10 else titles[:10]
                        })
                        logger.info(f"已创建 {json_path} 了 {len(db_records)} 条记录")
                        total_restored += len(db_records)
        
        except Exception as e:
            logger.error(f"将 {year} 年的数据库中的记录导入JSON文件时出错: {e}")
    
    return total_restored, synced_days


def sync_data(db_path=None, json_root_path=None):
    """同步数据库和JSON文件的接口函数"""
    # 配置路径
    if db_path is None:
        db_path = os.path.join('output', 'bilibili_history.db')
    if json_root_path is None:
        json_root_path = os.path.join('output', 'history_by_date')
    
    # 创建，计算路径
    output_dir = os.path.join('output', 'check')
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("===== 开始同步数据库和不同的JSON文件 =====")
    logger.info(f"数据库路径: {db_path}")
    logger.info(f"JSON文件路径: {json_root_path}")
    
    # 1. 将JSON文件中的记录导入到数据库
    json_to_db_count, json_to_db_days = sync_json_to_db(db_path, json_root_path)
    logger.info(f"从JSON文件中获取了 {json_to_db_count} 条记录导入到数据库")
    
    # 2. 将数据库中的记录导入到JSON文件
    db_to_json_count, db_to_json_days = sync_db_to_json(db_path, json_root_path)
    logger.info(f"从数据库中获取了 {db_to_json_count} 条记录导入到JSON文件")
    
    # 合并同步天数信息
    all_synced_days = json_to_db_days + db_to_json_days
    
    # 按日期排序
    all_synced_days.sort(key=lambda x: x['date'], reverse=True)
    
    logger.info("===== 同步成功。 =====")
    logger.info(f"总条记录: 从JSON文件导入到数据库 {json_to_db_count} 条，从数据库导入到JSON文件 {db_to_json_count} 条")
    
    # 保存同步结果到JSON文件
    sync_result_file = os.path.join(output_dir, "sync_result.json")
    sync_result = {
        "success": True,
        "json_to_db_count": json_to_db_count,
        "db_to_json_count": db_to_json_count,
        "total_synced": json_to_db_count + db_to_json_count,
        "synced_days": all_synced_days,
        "timestamp": datetime.now().isoformat()
    }
    
    with open(sync_result_file, 'w', encoding='utf-8') as f:
        json.dump(sync_result, f, ensure_ascii=False, indent=4)
    
    logger.info(f"同步结果已保存到 {sync_result_file}")
    
    return sync_result


def main():
    # 配置路径
    db_path = os.path.join('output', 'bilibili_history.db')
    json_root_path = os.path.join('output', 'history_by_date')
    
    sync_result = sync_data(db_path, json_root_path)
    print(f"同步完成，总共同步 {sync_result['total_synced']} 条记录")


if __name__ == '__main__':
    main()
