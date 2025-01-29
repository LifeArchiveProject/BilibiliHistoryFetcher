import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime

from scripts.utils import load_config, get_base_path, get_output_path

config = load_config()

# 配置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IS_SCRIPT_RUN = True

def get_base_path():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if IS_SCRIPT_RUN else os.getcwd()

# 定义读取分类信息的函数
def load_categories(config_path=None):
    if config_path is None:
        base_path = get_base_path()
        config_path = os.path.join(base_path, 'config', 'categories.json')
    """从 categories.json 文件中加载分类信息"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            categories = json.load(f)
            duplicated_tags = set(categories.get('duplicated_tags', []))
            unique_tag_to_main = categories.get('unique_tag_to_main', {})
            logger.info(f"成功加载分类信息：{config_path}")
            return duplicated_tags, unique_tag_to_main
    except Exception as e:
        logger.error(f"加载分类信息时发生错误: {e}")
        return set(), {}

# 加载分类信息
duplicated_tags, unique_tag_to_main = load_categories()

class SnowflakeIDGenerator:
    def __init__(self, machine_id=1, datacenter_id=1):
        self.lock = threading.Lock()
        self.machine_id = machine_id & 0x3FF
        self.datacenter_id = datacenter_id & 0x3FF
        self.sequence = 0
        self.last_timestamp = -1
        self.epoch = 1609459200000

    def _current_millis(self):
        return int(time.time() * 1000)

    def get_id(self):
        with self.lock:
            timestamp = self._current_millis()

            if timestamp < self.last_timestamp:
                raise Exception("时钟向后移动。拒绝生成 id。")

            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 0xFFF
                if self.sequence == 0:
                    while timestamp <= self.last_timestamp:
                        timestamp = self._current_millis()
            else:
                self.sequence = 0

            self.last_timestamp = timestamp

            id = ((timestamp - self.epoch) << 22) | (self.datacenter_id << 12) | self.sequence
            return id

id_generator = SnowflakeIDGenerator(machine_id=1, datacenter_id=1)

def get_years():
    current_year = datetime.now().year
    previous_year = current_year - 1
    return current_year, previous_year

def create_connection(db_file):
    """创建数据库连接"""
    try:
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        conn = sqlite3.connect(db_file)
        logger.info(f"成功连接到SQLite数据库: {db_file}")
        return conn
    except sqlite3.Error as e:
        logger.error(f"连接数据库时发生错误: {e}")
        return None

def table_exists(conn, table_name):
    """检查表是否存在"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT count(name) FROM sqlite_master 
        WHERE type='table' AND name=?
    """, (table_name,))
    return cursor.fetchone()[0] > 0

def create_table(conn, table_name):
    """创建数据表"""
    cursor = conn.cursor()
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY,
        title TEXT,
        long_title TEXT,
        cover TEXT,
        covers TEXT,
        uri TEXT,
        oid INTEGER,
        epid INTEGER,
        bvid TEXT,
        page INTEGER,
        cid INTEGER,
        part TEXT,
        business TEXT,
        dt INTEGER,
        videos INTEGER,
        author_name TEXT,
        author_face TEXT,
        author_mid INTEGER,
        view_at INTEGER,
        progress INTEGER,
        badge TEXT,
        show_title TEXT,
        duration INTEGER,
        current TEXT,
        total INTEGER,
        new_desc TEXT,
        is_finish INTEGER,
        is_fav INTEGER,
        kid INTEGER,
        tag_name TEXT,
        live_status INTEGER,
        main_category TEXT
    )
    """)
    
    # 创建索引
    cursor.execute(f"""
    CREATE INDEX IF NOT EXISTS idx_{table_name}_view_at 
    ON {table_name} (view_at)
    """)
    
    conn.commit()
    logger.info(f"成功为表 {table_name} 创建索引")

def batch_insert_data(conn, table_name, data_batch):
    """批量插入数据"""
    cursor = conn.cursor()
    insert_sql = f"""
    INSERT OR REPLACE INTO {table_name} (
        id, title, long_title, cover, covers, uri, oid, epid, bvid, page, 
        cid, part, business, dt, videos, author_name, author_face, author_mid, 
        view_at, progress, badge, show_title, duration, current, total, 
        new_desc, is_finish, is_fav, kid, tag_name, live_status, main_category
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    try:
        cursor.executemany(insert_sql, data_batch)
        conn.commit()
        return len(data_batch)
    except sqlite3.Error as e:
        logger.error(f"插入数据时发生错误: {e}")
        conn.rollback()
        return 0

def get_last_import_time():
    """获取上次导入时间"""
    try:
        last_import_file = os.path.join(get_output_path(), 'last_import.json')
        if os.path.exists(last_import_file):
            with open(last_import_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('last_import_time', 0)
        logger.info("未找到last_import.json文件，将导入所有数据")
        return 0
    except Exception as e:
        logger.error(f"读取上次导入时间失败: {e}")
        return 0

def import_data_from_json(conn, table_name, file_path, last_import_time=0, batch_size=1000):
    """从JSON文件导入数据"""
    try:
        # 尝试不同的编码方式读取
        data = None
        for encoding in ['utf-8', 'gbk', 'utf-8-sig']:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    data = json.load(f)
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        
        if data is None:
            logger.error(f"无法读取文件 {file_path}：所有编码尝试都失败")
            return 0
            
        total_inserted = 0
        # 按年份分组数据
        data_by_year = {}
        has_new_records = False

        # 获取现有记录的bvid和view_at组合
        cursor = conn.cursor()
        existing_records = set()
        for year in range(datetime.now().year - 1, datetime.now().year + 1):
            table = f"bilibili_history_{year}"
            if table_exists(conn, table):
                cursor.execute(f"SELECT bvid, view_at FROM {table}")
                existing_records.update((bvid, view_at) for bvid, view_at in cursor.fetchall())

        # 遍历所有记录，检查每条记录的时间
        for item in data:
            # 获取观看时间
            view_at = item.get('view_at', 0)
            if view_at == 0:
                continue
            
            # 如果有上次导入时间，则只处理更新的记录
            if last_import_time > 0 and view_at <= last_import_time:
                logger.debug(f"跳过旧记录: {item.get('title')} - {datetime.fromtimestamp(view_at)}")
                continue

            # 检查bvid和view_at组合是否已存在
            history = item.get('history', {})
            bvid = history.get('bvid', '')
            if (bvid, view_at) in existing_records:
                logger.debug(f"跳过重复记录: {item.get('title')} - {datetime.fromtimestamp(view_at)}")
                continue
                
            has_new_records = True
            year = datetime.fromtimestamp(view_at).year
            if year not in data_by_year:
                data_by_year[year] = []
                
            main_category = None
            business = history.get('business', '')
            tag_name = item.get('tag_name', '').strip()

            if business == 'archive':
                if tag_name in unique_tag_to_main:
                    main_category = unique_tag_to_main[tag_name]
                elif tag_name in duplicated_tags:
                    main_category = '待定'
                else:
                    main_category = '待定'

            # 从正确的位置获取duration和progress
            duration = item.get('duration', 0)  # 从item对象获取视频总时长
            progress = item.get('progress', 0)  # 从item对象获取观看进度

            record = (
                id_generator.get_id(),
                item.get('title', ''),
                item.get('long_title', ''),
                item.get('cover', ''),
                json.dumps(item.get('covers', [])),
                item.get('uri', ''),
                history.get('oid', 0),
                history.get('epid', 0),
                bvid,
                history.get('page', 1),
                history.get('cid', 0),
                history.get('part', ''),
                business,
                history.get('dt', 0),
                history.get('videos', 0),
                item.get('author_name', ''),
                item.get('author_face', ''),
                item.get('author_mid', 0),
                view_at,
                progress,  # 使用从item对象获取的观看进度
                item.get('badge', ''),
                item.get('show_title', ''),
                duration,  # 使用从item对象获取的视频总时长
                item.get('current', ''),
                item.get('total', 0),
                item.get('new_desc', ''),
                item.get('is_finish', 0),
                item.get('is_fav', 0),
                history.get('kid', 0),
                tag_name,
                item.get('live_status', 0),
                main_category
            )
            
            data_by_year[year].append(record)
            existing_records.add((bvid, view_at))  # 添加到已存在记录集合中
            
            # 当达到批量大小时，执行插入
            if len(data_by_year[year]) >= batch_size:
                year_table = f"{table_name}_{year}"
                if not table_exists(conn, year_table):
                    create_table(conn, year_table)
                inserted = batch_insert_data(conn, year_table, data_by_year[year])
                total_inserted += inserted
                data_by_year[year] = []
                
        # 处理剩余的数据
        for year, records in data_by_year.items():
            if records:
                year_table = f"{table_name}_{year}"
                if not table_exists(conn, year_table):
                    create_table(conn, year_table)
                inserted = batch_insert_data(conn, year_table, records)
                total_inserted += inserted
                
        return total_inserted
        
    except sqlite3.Error as e:
        logger.error(f"导入数据时发生错误: {e}")
        return 0

def save_last_import_record(file_path, timestamp):
    """保存最后导入记录"""
    record = {
        "last_import_file": file_path,
        "last_import_time": timestamp,
        "last_import_date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    }
    
    record_file = get_output_path('last_import.json')
    with open(record_file, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=4)
    logger.debug(f"已更新导入记录: {record}")

def get_last_import_record():
    """获取最后导入记录"""
    record_file = get_output_path('last_import.json')
    if os.path.exists(record_file):
        with open(record_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def import_all_history_files():
    """导入所有历史记录文件"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"========== 运行时间: {current_time} ==========")
    logger.info(f"当前工作目录: {os.getcwd()}")
    
    # 使用 get_output_path 获取路径
    full_data_folder = get_output_path('history_by_date')
    full_db_file = get_output_path(config['db_file'])

    logger.info(f"\n=== 路径信息 ===")
    logger.info(f"数据文件夹: {full_data_folder}")
    logger.info(f"数据库文件: {full_db_file}")
    
    if not os.path.exists(full_data_folder):
        message = f"本地文件夹 '{full_data_folder}' 不存在，无法加载数据。"
        logger.error(message)
        return {"status": "error", "message": message}

    # 获取最后导入记录
    last_record = get_last_import_record()
    last_import_time = last_record['last_import_time'] if last_record else 0
    
    if last_record:
        logger.info(f"上次导入记录:")
        logger.info(f"- 文件: {last_record['last_import_file']}")
        logger.info(f"- 时间: {last_import_time}")
        logger.info(f"- 日期: {last_record['last_import_date']}")
    else:
        logger.info("未找到导入记录，将导入所有数据")

    file_insert_counts = {}

    logger.info(f"开始遍历并导入文件夹 '{full_data_folder}' 中的数据...")

    conn = create_connection(full_db_file)
    if conn is None:
        message = f"无法连接到数据库 {full_db_file}。"
        logger.error(message)
        return {"status": "error", "message": message}

    try:
        # 遍历文件并导入
        total_files = 0
        total_records = 0
        latest_timestamp = 0  # 记录最新的时间戳
        latest_file = None  # 记录最新的文件
        
        # 获取所有JSON文件并按日期排序
        all_json_files = []
        for year in sorted(os.listdir(full_data_folder), reverse=True):  # 从最新的年份开始
            year_path = os.path.join(full_data_folder, year)
            if os.path.isdir(year_path) and year.isdigit():
                for month in sorted(os.listdir(year_path), reverse=True):  # 从最新的月份开始
                    month_path = os.path.join(year_path, month)
                    if os.path.isdir(month_path) and month.isdigit():
                        for day_file in sorted(os.listdir(month_path), reverse=True):  # 从最新的日期开始
                            if day_file.endswith('.json'):
                                day_path = os.path.join(month_path, day_file)
                                all_json_files.append(day_path)
        
        for day_path in all_json_files:
            logger.info(f"\n处理文件: {day_path}")
            
            # 读取文件中最新的记录时间
            try:
                with open(day_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data:
                        newest_view_at = max(item.get('view_at', 0) for item in data)
                        logger.info(f"文件中最新记录时间: {datetime.fromtimestamp(newest_view_at)}")
                        
                        # 更新最新的时间戳
                        if newest_view_at > latest_timestamp:
                            latest_timestamp = newest_view_at
                            latest_file = day_path
                        
                        # 只有当存在上次导入记录时才进行时间判断
                        if last_import_time > 0 and newest_view_at <= last_import_time:
                            logger.info(f"跳过文件 {day_path} 及后续文件: 所有记录都早于上次导入时间")
                            break
            except Exception as e:
                logger.error(f"读取文件 {day_path} 时出错: {e}")
                continue
            
            inserted_count = import_data_from_json(conn, "bilibili_history", day_path, last_import_time)
            if inserted_count > 0:
                total_files += 1
                total_records += inserted_count
                file_insert_counts[day_path] = inserted_count
                logger.info(f"成功插入 {inserted_count} 条记录")
        
        # 在所有文件处理完成后，使用最新的时间戳更新导入记录
        if total_records > 0 and latest_timestamp > 0:
            save_last_import_record(latest_file, latest_timestamp)
            logger.info(f"更新导入记录为最新时间戳: {datetime.fromtimestamp(latest_timestamp)}")
        
        # 打印导入统计
        logger.info("\n=== 导入统计 ===")
        logger.info(f"处理文件总数: {total_files}")
        logger.info(f"插入记录总数: {total_records}")
        if file_insert_counts:
            logger.info("\n各文件插入详情:")
            for file_path, count in file_insert_counts.items():
                logger.info(f"- {os.path.basename(file_path)}: {count} 条记录")
        else:
            logger.info("\n没有新记录需要插入")
        logger.info("================\n")

        message = f"数据导入完成，共插入 {total_records} 条记录。"
        return {"status": "success", "message": message, "inserted_count": total_records}

    except sqlite3.Error as e:
        error_msg = f"数据库错误: {str(e)}"
        logger.error(f"=== 错误 ===\n{error_msg}\n===========")
        return {"status": "error", "message": error_msg}
    finally:
        if conn:
            conn.close()

# 允许脚本独立运行
if __name__ == '__main__':
    result = import_all_history_files()
    if result["status"] == "success":
        print(result["message"])
    else:
        print(f"错误: {result['message']}")
