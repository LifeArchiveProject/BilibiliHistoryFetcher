import json
import os
from collections import defaultdict
from datetime import datetime
import sqlite3

from scripts.utils import load_config, get_output_path

config = load_config()

def get_db():
    """获取数据库连接"""
    db_path = get_output_path(config['db_file'])
    return sqlite3.connect(db_path)

def get_current_year():
    """获取当前年份"""
    return datetime.now().year

def load_history_from_db():
    """从数据库加载历史记录数据"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        current_year = get_current_year()
        table_name = f"bilibili_history_{current_year}"
        
        # 检查表是否存在
        cursor.execute(f"""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """, (table_name,))
        
        if not cursor.fetchone():
            print(f"表 {table_name} 不存在")
            return []
        
        # 查询所有记录
        cursor.execute(f"SELECT view_at FROM {table_name}")
        return cursor.fetchall()
        
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return []
    finally:
        conn.close()

def calculate_video_counts(history_data):
    """统计每天和每月的视频观看数量"""
    current_year = datetime.now().year
    daily_count = defaultdict(int)
    monthly_count = defaultdict(int)

    for (view_at,) in history_data:
        view_time = datetime.fromtimestamp(view_at)
        if view_time.year != current_year:
            continue

        date_str = view_time.strftime('%Y-%m-%d')
        month_str = view_time.strftime('%Y-%m')
        daily_count[date_str] += 1
        monthly_count[month_str] += 1

    return daily_count, monthly_count

def save_daily_count_to_json(daily_count, year):
    """保存每天的观看数量到 JSON 文件"""
    output_file = get_output_path(f'daily_count_{year}.json')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(daily_count, f, ensure_ascii=False, indent=4)
    print(f"每天观看数量已保存到 {output_file}")
    return output_file

def analyze_history_by_params(date_str=None, start_date=None, end_date=None):
    """根据参数分析历史数据
    
    Args:
        date_str: 指定日期，格式为YYYY-MM-DD
        start_date: 起始日期，格式为YYYY-MM-DD
        end_date: 结束日期，格式为YYYY-MM-DD
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        current_year = get_current_year()
        table_name = f"bilibili_history_{current_year}"
        
        # 构建基础查询
        query = f"SELECT view_at FROM {table_name} WHERE 1=1"
        params = []
        
        # 处理日期条件
        if date_str:
            start_timestamp = int(datetime.strptime(date_str, '%Y-%m-%d').timestamp())
            end_timestamp = start_timestamp + 86400  # 加一天
            query += " AND view_at >= ? AND view_at < ?"
            params.extend([start_timestamp, end_timestamp])
        elif start_date or end_date:
            if start_date:
                start_timestamp = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp())
                query += " AND view_at >= ?"
                params.append(start_timestamp)
            if end_date:
                end_timestamp = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp()) + 86400
                query += " AND view_at < ?"
                params.append(end_timestamp)
        
        # 执行查询
        cursor.execute(query, params)
        history_data = cursor.fetchall()
        
        # 计算统计数据
        daily_count = defaultdict(int)
        monthly_count = defaultdict(int)
        
        for (view_at,) in history_data:
            view_time = datetime.fromtimestamp(view_at)
            current_date = view_time.strftime('%Y-%m-%d')
            month_str = view_time.strftime('%Y-%m')
            daily_count[current_date] += 1
            monthly_count[month_str] += 1
        
        result = {}
        
        # 如果指定了具体日期，返回该日期的观看数量
        if date_str:
            count = daily_count.get(date_str, 0)
            result["date_count"] = {
                "date": date_str,
                "count": count
            }
        
        # 如果指定了日期范围，返回该范围内的数据
        if start_date or end_date:
            total_count = sum(daily_count.values())
            result["date_range"] = {
                "start_date": start_date or "无限制",
                "end_date": end_date or "无限制",
                "total_count": total_count,
                "daily_counts": dict(daily_count)
            }
        
        return result
        
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return {"error": f"数据库错误: {e}"}
    finally:
        conn.close()

def get_daily_counts(year=None):
    """获取每日观看数量"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        table_name = f"bilibili_history_{year}" if year else None
        
        if not table_name:
            # 获取所有年份的表
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name LIKE 'bilibili_history_%'
            """)
            tables = cursor.fetchall()
            if not tables:
                return {"error": "未找到任何历史记录数据"}
            
            # 合并所有年份的数据
            daily_count = {}
            for (table,) in tables:
                # 按日期统计观看数量
                cursor.execute(f"""
                    SELECT 
                        strftime('%Y-%m-%d', datetime(view_at, 'unixepoch')) as date,
                        COUNT(*) as count
                    FROM {table}
                    GROUP BY date
                    ORDER BY date
                """)
                
                for row in cursor.fetchall():
                    date, count = row
                    if date in daily_count:
                        daily_count[date] += count
                    else:
                        daily_count[date] = count
        else:
            # 查询指定年份的数据
            cursor.execute(f"""
                SELECT 
                    strftime('%Y-%m-%d', datetime(view_at, 'unixepoch')) as date,
                    COUNT(*) as count
                FROM {table_name}
                GROUP BY date
                ORDER BY date
            """)
            
            daily_count = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 保存到JSON文件
        try:
            if year:
                output_file = save_daily_count_to_json(daily_count, year)
            else:
                # 按年份拆分数据并保存
                daily_count_by_year = {}
                for date, count in daily_count.items():
                    year = date.split('-')[0]
                    if year not in daily_count_by_year:
                        daily_count_by_year[year] = {}
                    daily_count_by_year[year][date] = count
                
                # 保存每年的数据到单独的文件
                for year, data in daily_count_by_year.items():
                    output_file = save_daily_count_to_json(data, year)
                    print(f"数据已保存到: {output_file}")
        except Exception as e:
            print(f"保存JSON文件时出错: {e}")
            return {"error": f"保存JSON文件时出错: {e}"}
        
        return daily_count
        
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return {"error": f"数据库错误: {e}"}
    finally:
        conn.close()

def get_monthly_counts(year=None):
    """获取每月观看数量"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        table_name = f"bilibili_history_{year}" if year else None
        
        if not table_name:
            # 获取所有年份的表
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name LIKE 'bilibili_history_%'
            """)
            tables = cursor.fetchall()
            if not tables:
                return {"error": "未找到任何历史记录数据"}
            
            # 合并所有年份的数据
            monthly_count = {}
            for (table,) in tables:
                cursor.execute(f"""
                    SELECT 
                        strftime('%Y-%m', datetime(view_at, 'unixepoch')) as month,
                        COUNT(*) as count
                    FROM {table}
                    GROUP BY month
                    ORDER BY month
                """)
                
                for row in cursor.fetchall():
                    month, count = row
                    if month in monthly_count:
                        monthly_count[month] += count
                    else:
                        monthly_count[month] = count
        else:
            cursor.execute(f"""
                SELECT 
                    strftime('%Y-%m', datetime(view_at, 'unixepoch')) as month,
                    COUNT(*) as count
                FROM {table_name}
                GROUP BY month
                ORDER BY month
            """)
            
            monthly_count = {row[0]: row[1] for row in cursor.fetchall()}
            
        return monthly_count
        
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return {"error": f"数据库错误: {e}"}
    finally:
        conn.close()

def get_available_years():
    """获取可用的年份列表"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name LIKE 'bilibili_history_%'
        """)
        tables = cursor.fetchall()
        years = []
        for (table_name,) in tables:
            try:
                year = int(table_name.split('_')[-1])
                years.append(year)
            except (ValueError, IndexError):
                continue
        return sorted(years, reverse=True)
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return []
    finally:
        conn.close()

def get_daily_and_monthly_counts(target_year=None):
    """获取每日和每月的观看数量统计
    
    Args:
        target_year: 要分析的年份，不传则分析所有年份
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"========== 运行时间: {current_time} ==========")
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        
        # 获取所有可用年份
        available_years = get_available_years()
        if not available_years:
            return {"error": "未找到任何历史记录数据"}
        
        # 如果指定了年份，检查是否可用
        if target_year is not None:
            if target_year not in available_years:
                return {"error": f"未找到 {target_year} 年的历史记录数据"}
            years_to_analyze = [target_year]
        else:
            years_to_analyze = available_years
        
        daily_count = {}
        monthly_count = {}
        total_count = 0

        # 新增: 时长统计
        daily_watch_seconds = {}
        monthly_watch_seconds = {}
        total_watch_seconds = 0
        
        # 分析每个年份的数据
        for year in years_to_analyze:
            table_name = f"bilibili_history_{year}"
            
            # 获取每日观看数量，使用localtime进行时区转换
            cursor.execute(f"""
                SELECT 
                    strftime('%Y-%m-%d', datetime(view_at, 'unixepoch', 'localtime')) as date,
                    COUNT(*) as count
                FROM {table_name}
                GROUP BY date
                ORDER BY date
            """)
            year_daily_count = {row[0]: row[1] for row in cursor.fetchall()}
            daily_count.update(year_daily_count)

            # 获取每日观看总时长（秒），使用localtime进行时区转换
            cursor.execute(f"""
                SELECT
                    strftime('%Y-%m-%d', datetime(view_at, 'unixepoch', 'localtime')) as date,
                    SUM(
                        CASE
                            WHEN progress = -1 THEN duration
                            WHEN progress IS NULL THEN 0
                            WHEN progress >= 0 THEN CASE WHEN progress > duration THEN duration ELSE progress END
                            ELSE 0
                        END
                    ) as seconds
                FROM {table_name}
                GROUP BY date
                ORDER BY date
            """)
            year_daily_watch = {row[0]: int(row[1] or 0) for row in cursor.fetchall()}
            daily_watch_seconds.update(year_daily_watch)
            total_watch_seconds += sum(year_daily_watch.values())
            
            # 获取每月观看数量，使用localtime进行时区转换
            cursor.execute(f"""
                SELECT 
                    strftime('%Y-%m', datetime(view_at, 'unixepoch', 'localtime')) as month,
                    COUNT(*) as count
                FROM {table_name}
                GROUP BY month
                ORDER BY month
            """)
            year_monthly_count = {row[0]: row[1] for row in cursor.fetchall()}
            monthly_count.update(year_monthly_count)

            # 获取每月观看总时长（秒），使用localtime进行时区转换
            cursor.execute(f"""
                SELECT
                    strftime('%Y-%m', datetime(view_at, 'unixepoch', 'localtime')) as month,
                    SUM(
                        CASE
                            WHEN progress = -1 THEN duration
                            WHEN progress IS NULL THEN 0
                            WHEN progress >= 0 THEN CASE WHEN progress > duration THEN duration ELSE progress END
                            ELSE 0
                        END
                    ) as seconds
                FROM {table_name}
                GROUP BY month
                ORDER BY month
            """)
            year_monthly_watch = {row[0]: int(row[1] or 0) for row in cursor.fetchall()}
            monthly_watch_seconds.update(year_monthly_watch)
            
            # 计算该年份的总数
            total_count += sum(year_daily_count.values())
            
            # 输出每月的视频观看统计
            print(f"\n{year}年每月观看视频数量：")
            for month, count in sorted(year_monthly_count.items()):
                print(f"{month}: {count} 个视频")
        
        # 保存每日观看数量到JSON文件
        try:
            if target_year:
                output_file = save_daily_count_to_json(daily_count, target_year)
                print(f"每日观看数量已保存到: {output_file}")
            else:
                # 按年份拆分数据并保存
                daily_count_by_year = {}
                for date, count in daily_count.items():
                    year = date.split('-')[0]
                    if year not in daily_count_by_year:
                        daily_count_by_year[year] = {}
                    daily_count_by_year[year][date] = count
                
                # 保存每年的数据到单独的文件
                for year, data in daily_count_by_year.items():
                    output_file = save_daily_count_to_json(data, year)
                    print(f"{year}年每日观看数量已保存到: {output_file}")
        except Exception as e:
            print(f"保存JSON文件时出错: {e}")
        
        return {
            "daily_count": daily_count,
            "monthly_count": monthly_count,
            "total_count": total_count,
            "daily_watch_seconds": daily_watch_seconds,
            "monthly_watch_seconds": monthly_watch_seconds,
            "total_watch_seconds": total_watch_seconds
        }
        
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return {"error": f"数据库错误: {e}"}
    finally:
        if conn:
            conn.close()

# 如果该脚本直接运行，则调用 main()
if __name__ == '__main__':
    result = get_daily_and_monthly_counts()
    if "error" in result:
        print(f"错误: {result['error']}")
    else:
        print("\n分析完成！")
