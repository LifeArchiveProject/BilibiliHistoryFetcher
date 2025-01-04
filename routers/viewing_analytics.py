from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Dict, List
from datetime import datetime
import sqlite3
from collections import defaultdict

from scripts.utils import load_config, get_output_path

router = APIRouter()
config = load_config()

def get_db():
    """获取数据库连接"""
    db_path = get_output_path(config['db_file'])
    return sqlite3.connect(db_path)

def get_current_year():
    """获取当前年份"""
    return datetime.now().year

def sort_dict_by_value(d: dict, key: str = None, reverse: bool = True) -> dict:
    """按值对字典进行排序，支持嵌套字典"""
    if key:
        return dict(sorted(d.items(), key=lambda x: x[1][key], reverse=reverse))
    return dict(sorted(d.items(), key=lambda x: x[1], reverse=reverse))

def get_top_n_items(d: dict, n: int, key: str = None) -> dict:
    """获取排序后的前N个项目"""
    sorted_dict = sort_dict_by_value(d, key, reverse=True)
    return dict(list(sorted_dict.items())[:n])

def generate_time_insights(data: dict) -> dict:
    """根据时间分布数据生成人性化的见解和总结
    
    Args:
        data: 包含各种时间统计数据的字典
    
    Returns:
        dict: 包含各个维度的数据解读
    """
    insights = {}
    
    # 1. 活跃度解读
    total_views = data['stats_summary']['total_views']
    active_days = data['stats_summary']['active_days']
    avg_daily = data['stats_summary']['average_daily_views']
    
    if active_days > 25:
        activity_level = "非常活跃"
    elif active_days > 15:
        activity_level = "比较活跃"
    else:
        activity_level = "较为悠闲"
    
    insights['overall_activity'] = f"今年以来，你在B站观看了{total_views}个视频，总计活跃了{active_days}天，平均每天观看{avg_daily}个视频。整体来说，你是一位{activity_level}的B站用户。"
    
    # 2. 月度规律解读
    monthly_stats = data['monthly_stats']
    if monthly_stats:
        max_month = max(monthly_stats.items(), key=lambda x: x[1])
        min_month = min(monthly_stats.items(), key=lambda x: x[1])
        month_trend = ""
        
        # 计算月度趋势
        months = sorted(monthly_stats.keys())
        if len(months) >= 2:
            first_month_count = monthly_stats[months[0]]
            last_month_count = monthly_stats[months[-1]]
            if last_month_count > first_month_count * 1.2:
                month_trend = "你在B站观看视频的热情正在逐月增长，看来你越来越喜欢B站了呢！"
            elif last_month_count < first_month_count * 0.8:
                month_trend = "最近你在B站的活跃度有所下降，可能是工作或学习变得更忙了吧。"
            else:
                month_trend = "你在B站的活跃度保持得很稳定，看来已经养成了良好的观看习惯。"
        
        insights['monthly_pattern'] = f"在{max_month[0]}月，你观看了{max_month[1]}个视频，是你最活跃的月份；而在{min_month[0]}月，观看量为{min_month[1]}个。{month_trend}"
    
    # 3. 周间分布解读
    weekly_stats = data['weekly_stats']
    if weekly_stats:
        max_weekday = max(weekly_stats.items(), key=lambda x: x[1])
        min_weekday = min(weekly_stats.items(), key=lambda x: x[1])
        
        # 计算工作日和周末的平均值
        workday_avg = sum(weekly_stats[day] for day in ['周一', '周二', '周三', '周四', '周五']) / 5
        weekend_avg = sum(weekly_stats[day] for day in ['周六', '周日']) / 2
        
        if weekend_avg > workday_avg * 1.5:
            week_pattern = "你是一位周末党，倾向于在周末集中补番或观看视频。"
        elif workday_avg > weekend_avg:
            week_pattern = "工作日反而是你观看视频的主要时间，也许是通过B站来缓解工作压力？"
        else:
            week_pattern = "你的观看时间分布很均衡，不管是工作日还是周末都保持着适度的观看习惯。"
        
        insights['weekly_pattern'] = f"{week_pattern}其中{max_weekday[0]}是你最喜欢刷B站的日子，平均会看{round(max_weekday[1]/active_days*7, 1)}个视频；而{min_weekday[0]}的观看量最少。"
    
    # 4. 时段分布解读
    peak_hours = data['peak_hours']
    daily_slots = data['daily_time_slots']
    
    # 将一天分为几个时间段
    morning = sum(daily_slots.get(f"{i}时", 0) for i in range(5, 12))
    afternoon = sum(daily_slots.get(f"{i}时", 0) for i in range(12, 18))
    evening = sum(daily_slots.get(f"{i}时", 0) for i in range(18, 23))
    night = sum(daily_slots.get(f"{i}时", 0) for i in range(23, 24)) + sum(daily_slots.get(f"{i}时", 0) for i in range(0, 5))
    
    time_slots = [
        ("清晨和上午", morning),
        ("下午", afternoon),
        ("傍晚和晚上", evening),
        ("深夜", night)
    ]
    primary_slot = max(time_slots, key=lambda x: x[1])
    
    if primary_slot[0] == "深夜":
        time_advice = "熬夜看视频可能会影响健康，建议调整作息哦！"
    else:
        time_advice = "这个时间段的观看习惯很好，既不影响作息，也能享受视频带来的乐趣。"
    
    insights['time_pattern'] = f"你最喜欢在{primary_slot[0]}观看B站视频，特别是{peak_hours[0]['hour']}达到观看高峰。{time_advice}"
    
    # 5. 特殊观看日解读
    max_daily = data['max_daily_record']
    if max_daily:
        insights['peak_day'] = f"在{max_daily['date']}这一天，你创下了单日观看{max_daily['view_count']}个视频的记录！这可能是一个特别的日子，也许是在追番、学习或者在家放松的一天。"
    
    return insights

def generate_continuity_insights(continuity_data: dict) -> dict:
    """生成连续性相关的洞察"""
    insights = {}
    
    # 连续性洞察
    max_streak = continuity_data['max_streak']
    current_streak = continuity_data['current_streak']
    
    # 根据连续天数生成评价
    streak_comment = ""
    if max_streak >= 30:
        streak_comment = "你是B站的铁杆粉丝啊！"
    elif max_streak >= 14:
        streak_comment = "看来你对B站情有独钟呢！"
    else:
        streak_comment = "你的观看习惯比较随性自由。"
    
    insights['continuity'] = f"你最长连续观看B站达到了{max_streak}天，{streak_comment}目前已经连续观看了{current_streak}天。"
    
    return insights

def analyze_viewing_continuity(cursor, table_name: str) -> dict:
    """分析观看习惯的连续性
    
    Args:
        cursor: 数据库游标
        table_name: 表名
    
    Returns:
        dict: 连续性分析结果
    """
    # 获取所有观看日期
    cursor.execute(f"""
        SELECT DISTINCT date(datetime(view_at, 'unixepoch')) as view_date
        FROM {table_name}
        ORDER BY view_date
    """)
    dates = [row[0] for row in cursor.fetchall()]
    
    # 计算连续观看天数
    max_streak = current_streak = 1
    longest_streak_start = longest_streak_end = current_streak_start = dates[0] if dates else None
    
    for i in range(1, len(dates)):
        date1 = datetime.strptime(dates[i-1], '%Y-%m-%d')
        date2 = datetime.strptime(dates[i], '%Y-%m-%d')
        if (date2 - date1).days == 1:
            current_streak += 1
            if current_streak > max_streak:
                max_streak = current_streak
                longest_streak_start = datetime.strptime(dates[i-max_streak+1], '%Y-%m-%d').strftime('%Y-%m-%d')
                longest_streak_end = dates[i]
        else:
            current_streak = 1
            current_streak_start = dates[i]
    
    return {
        'max_streak': max_streak,
        'longest_streak_period': {
            'start': longest_streak_start,
            'end': longest_streak_end
        },
        'current_streak': current_streak,
        'current_streak_start': current_streak_start
    }

def analyze_time_investment(cursor, table_name: str) -> dict:
    """分析时间投入强度
    
    Args:
        cursor: 数据库游标
        table_name: 表名
    
    Returns:
        dict: 时间投入分析结果
    """
    cursor.execute(f"""
        SELECT 
            date(datetime(view_at, 'unixepoch')) as view_date,
            COUNT(*) as video_count,
            SUM(duration) as total_duration
        FROM {table_name}
        GROUP BY view_date
        ORDER BY total_duration DESC
        LIMIT 1
    """)
    max_duration_day = cursor.fetchone()
    
    cursor.execute(f"""
        SELECT 
            AVG(daily_duration) as avg_duration
        FROM (
            SELECT 
                date(datetime(view_at, 'unixepoch')) as view_date,
                SUM(duration) as daily_duration
            FROM {table_name}
            GROUP BY view_date
        )
    """)
    avg_daily_duration = cursor.fetchone()[0]
    
    return {
        'max_duration_day': {
            'date': max_duration_day[0],
            'video_count': max_duration_day[1],
            'total_duration': max_duration_day[2]
        },
        'avg_daily_duration': avg_daily_duration
    }

def analyze_seasonal_patterns(cursor, table_name: str) -> dict:
    """分析季节性观看模式
    
    Args:
        cursor: 数据库游标
        table_name: 表名
    
    Returns:
        dict: 季节性分析结果
    """
    cursor.execute(f"""
        SELECT 
            CASE 
                WHEN CAST(strftime('%m', datetime(view_at, 'unixepoch')) AS INTEGER) IN (3,4,5) THEN '春季'
                WHEN CAST(strftime('%m', datetime(view_at, 'unixepoch')) AS INTEGER) IN (6,7,8) THEN '夏季'
                WHEN CAST(strftime('%m', datetime(view_at, 'unixepoch')) AS INTEGER) IN (9,10,11) THEN '秋季'
                ELSE '冬季'
            END as season,
            COUNT(*) as view_count,
            AVG(duration) as avg_duration
        FROM {table_name}
        GROUP BY season
    """)
    
    return {row[0]: {'view_count': row[1], 'avg_duration': row[2]} for row in cursor.fetchall()}

def analyze_holiday_patterns(cursor, table_name: str) -> dict:
    """分析假期和工作日的观看差异
    
    Args:
        cursor: 数据库游标
        table_name: 表名
    
    Returns:
        dict: 假期与工作日对比分析结果
    """
    # 简单起见，这里只考虑周末作为假期
    cursor.execute(f"""
        SELECT 
            CASE 
                WHEN strftime('%w', datetime(view_at, 'unixepoch')) IN ('0', '6') THEN '周末'
                ELSE '工作日'
            END as day_type,
            COUNT(*) as view_count,
            AVG(duration) as avg_duration,
            COUNT(DISTINCT date(datetime(view_at, 'unixepoch'))) as active_days
        FROM {table_name}
        GROUP BY day_type
    """)
    
    results = {row[0]: {
        'view_count': row[1],
        'avg_duration': row[2],
        'active_days': row[3]
    } for row in cursor.fetchall()}
    
    # 计算平均值
    for day_type in results:
        total_possible_days = 52 * (2 if day_type == '周末' else 5)  # 假设一年52周
        results[day_type]['activity_rate'] = results[day_type]['active_days'] / total_possible_days
    
    return results

def analyze_duration_time_correlation(cursor, table_name: str) -> dict:
    """分析视频时长与观看时间段的关联
    
    Args:
        cursor: 数据库游标
        table_name: 表名
    
    Returns:
        dict: 时长与时间段关联分析结果
    """
    cursor.execute(f"""
        SELECT 
            CASE 
                WHEN CAST(strftime('%H', datetime(view_at, 'unixepoch')) AS INTEGER) < 6 THEN '凌晨'
                WHEN CAST(strftime('%H', datetime(view_at, 'unixepoch')) AS INTEGER) < 12 THEN '上午'
                WHEN CAST(strftime('%H', datetime(view_at, 'unixepoch')) AS INTEGER) < 18 THEN '下午'
                ELSE '晚上'
            END as time_slot,
            CASE 
                WHEN duration < 300 THEN '短视频'
                WHEN duration < 1200 THEN '中等视频'
                ELSE '长视频'
            END as duration_type,
            COUNT(*) as video_count,
            AVG(duration) as avg_duration
        FROM {table_name}
        GROUP BY time_slot, duration_type
    """)
    
    results = defaultdict(dict)
    for row in cursor.fetchall():
        results[row[0]][row[1]] = {
            'video_count': row[2],
            'avg_duration': row[3]
        }
    
    return dict(results)

def analyze_completion_rates(cursor, table_name: str) -> dict:
    """分析视频完成率"""
    # 获取表结构
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {col[1]: idx for idx, col in enumerate(cursor.fetchall())}
    
    # 确保必要的列存在
    required_columns = ['duration', 'progress', 'author_name', 'author_mid', 'tag_name']
    for col in required_columns:
        if col not in columns:
            raise ValueError(f"Required column '{col}' not found in table {table_name}")
    
    cursor.execute(f"SELECT * FROM {table_name}")
    histories = cursor.fetchall()
    
    # 基础统计
    total_videos = len(histories)
    total_completion = 0
    fully_watched = 0
    not_started = 0
    
    # UP主统计
    author_stats = {}
    # 分区统计
    tag_stats = {}
    # 时长分布统计
    duration_stats = {
        "短视频(≤5分钟)": {"video_count": 0, "total_completion": 0, "fully_watched": 0, "average_completion_rate": 0},
        "中等视频(5-20分钟)": {"video_count": 0, "total_completion": 0, "fully_watched": 0, "average_completion_rate": 0},
        "长视频(>20分钟)": {"video_count": 0, "total_completion": 0, "fully_watched": 0, "average_completion_rate": 0}
    }
    # 完成率分布
    completion_distribution = {
        "0-10%": 0,
        "10-30%": 0,
        "30-50%": 0,
        "50-70%": 0,
        "70-90%": 0,
        "90-100%": 0
    }
    
    for history in histories:
        # 获取并转换数据类型
        try:
            duration = float(history[columns['duration']]) if history[columns['duration']] else 0
            progress = float(history[columns['progress']]) if history[columns['progress']] else 0
            author_name = history[columns['author_name']]
            author_mid = history[columns['author_mid']]
            tag_name = history[columns['tag_name']]
        except (ValueError, TypeError) as e:
            print(f"Warning: Failed to process record: {history}")
            continue
        
        # 计算完成率
        completion_rate = (progress / duration * 100) if duration > 0 else 0
        total_completion += completion_rate
        
        # 统计完整观看和未开始观看
        if completion_rate >= 90:  # 90%以上视为完整观看
            fully_watched += 1
        elif completion_rate == 0:
            not_started += 1
        
        # 更新完成率分布
        if completion_rate <= 10:
            completion_distribution["0-10%"] += 1
        elif completion_rate <= 30:
            completion_distribution["10-30%"] += 1
        elif completion_rate <= 50:
            completion_distribution["30-50%"] += 1
        elif completion_rate <= 70:
            completion_distribution["50-70%"] += 1
        elif completion_rate <= 90:
            completion_distribution["70-90%"] += 1
        else:
            completion_distribution["90-100%"] += 1
        
        # UP主统计
        if author_name and author_mid:
            if author_name not in author_stats:
                author_stats[author_name] = {
                    "author_mid": author_mid,
                    "video_count": 0,
                    "total_completion": 0,
                    "fully_watched": 0
                }
            stats = author_stats[author_name]
            stats["video_count"] += 1
            stats["total_completion"] += completion_rate
            if completion_rate >= 90:
                stats["fully_watched"] += 1
        
        # 分区统计
        if tag_name:
            if tag_name not in tag_stats:
                tag_stats[tag_name] = {
                    "video_count": 0,
                    "total_completion": 0,
                    "fully_watched": 0
                }
            stats = tag_stats[tag_name]
            stats["video_count"] += 1
            stats["total_completion"] += completion_rate
            if completion_rate >= 90:
                stats["fully_watched"] += 1
        
        # 时长分布统计
        if duration <= 300:  # 5分钟
            category = "短视频(≤5分钟)"
        elif duration <= 1200:  # 20分钟
            category = "中等视频(5-20分钟)"
        else:
            category = "长视频(>20分钟)"
        
        stats = duration_stats[category]
        stats["video_count"] += 1
        stats["total_completion"] += completion_rate
        if completion_rate >= 90:
            stats["fully_watched"] += 1
    
    # 计算总体统计
    overall_stats = {
        "total_videos": total_videos,
        "average_completion_rate": round(total_completion / total_videos, 2) if total_videos > 0 else 0,
        "fully_watched_count": fully_watched,
        "not_started_count": not_started,
        "fully_watched_rate": round(fully_watched / total_videos * 100, 2) if total_videos > 0 else 0,
        "not_started_rate": round(not_started / total_videos * 100, 2) if total_videos > 0 else 0
    }
    
    # 计算各类视频的平均完成率和完整观看率
    for category, stats in duration_stats.items():
        if stats["video_count"] > 0:
            stats["average_completion_rate"] = round(stats["total_completion"] / stats["video_count"], 2)
            stats["fully_watched_rate"] = round(stats["fully_watched"] / stats["video_count"] * 100, 2)
        else:
            stats["average_completion_rate"] = 0
            stats["fully_watched_rate"] = 0
    
    # 计算UP主平均完成率和完整观看率，并按观看数量筛选和排序
    filtered_authors = {}
    for name, stats in author_stats.items():
        if stats["video_count"] >= 5:  # 只保留观看数量>=5的UP主
            stats["average_completion_rate"] = round(stats["total_completion"] / stats["video_count"], 2)
            stats["fully_watched_rate"] = round(stats["fully_watched"] / stats["video_count"] * 100, 2)
            filtered_authors[name] = stats
    
    # 获取观看次数最多的UP主
    most_watched_authors = dict(sorted(
        filtered_authors.items(),
        key=lambda x: x[1]["video_count"],
        reverse=True
    )[:10])
    
    # 获取完成率最高的UP主
    highest_completion_authors = dict(sorted(
        filtered_authors.items(),
        key=lambda x: x[1]["average_completion_rate"],
        reverse=True
    )[:10])
    
    # 计算分区平均完成率和完整观看率，并按观看数量筛选和排序
    filtered_tags = {}
    for tag, stats in tag_stats.items():
        if stats["video_count"] >= 5:  # 只保留视频数量>=5的分区
            stats["average_completion_rate"] = round(stats["total_completion"] / stats["video_count"], 2)
            stats["fully_watched_rate"] = round(stats["fully_watched"] / stats["video_count"] * 100, 2)
            filtered_tags[tag] = stats
    
    # 获取完成率最高的分区
    top_tags = dict(sorted(
        filtered_tags.items(),
        key=lambda x: x[1]["average_completion_rate"],
        reverse=True
    )[:10])
    
    return {
        "overall_stats": overall_stats,
        "duration_based_stats": duration_stats,
        "completion_distribution": completion_distribution,
        "tag_completion_rates": top_tags,
        "most_watched_authors": most_watched_authors,
        "highest_completion_authors": highest_completion_authors
    }

def generate_completion_insights(completion_data: dict) -> dict:
    """生成视频完成率相关的洞察"""
    insights = {}
    
    try:
        # 整体完成率洞察
        overall = completion_data.get("overall_stats", {})
        if overall:
            insights["overall_completion"] = (
                f"在观看的{overall.get('total_videos', 0)}个视频中，你平均观看完成率为{overall.get('average_completion_rate', 0)}%，"
                f"完整看完的视频占比{overall.get('fully_watched_rate', 0)}%，未开始观看的占比{overall.get('not_started_rate', 0)}%。"
            )
        
        # 视频时长偏好洞察
        duration_stats = completion_data.get("duration_based_stats", {})
        if duration_stats:
            valid_durations = [(k, v) for k, v in duration_stats.items() 
                             if v.get("video_count", 0) > 0 and v.get("average_completion_rate", 0) > 0]
            if valid_durations:
                max_completion_duration = max(valid_durations, key=lambda x: x[1].get("average_completion_rate", 0))
                insights["duration_preference"] = (
                    f"你最容易看完的是{max_completion_duration[0]}，平均完成率达到{max_completion_duration[1].get('average_completion_rate', 0)}%，"
                    f"其中完整看完的视频占比{max_completion_duration[1].get('fully_watched_rate', 0)}%。"
                )
        
        # 分区兴趣洞察
        tag_rates = completion_data.get("tag_completion_rates", {})
        if tag_rates:
            valid_tags = [(k, v) for k, v in tag_rates.items() 
                         if v.get("video_count", 0) >= 5]  # 只考虑观看数量>=5的分区
            if valid_tags:
                top_tag = max(valid_tags, key=lambda x: x[1].get("average_completion_rate", 0))
                insights["tag_completion"] = (
                    f"在经常观看的分区中，你对{top_tag[0]}分区的视频最感兴趣，平均完成率达到{top_tag[1].get('average_completion_rate', 0)}%，"
                    f"观看过{top_tag[1].get('video_count', 0)}个该分区的视频。"
                )
        
        # UP主偏好洞察
        most_watched = completion_data.get("most_watched_authors", {})
        if most_watched:
            top_watched = next(iter(most_watched.items()), None)
            if top_watched:
                insights["most_watched_author"] = (
                    f"你观看最多的UP主是{top_watched[0]}，观看了{top_watched[1].get('video_count', 0)}个视频，"
                    f"平均完成率为{top_watched[1].get('average_completion_rate', 0)}%。"
                )
        
        highest_completion = completion_data.get("highest_completion_authors", {})
        if highest_completion and most_watched:
            top_completion = next(iter(highest_completion.items()), None)
            if top_completion and top_completion[0] != next(iter(most_watched.keys())):
                insights["highest_completion_author"] = (
                    f"在经常观看的UP主中，你对{top_completion[0]}的视频完成度最高，"
                    f"平均完成率达到{top_completion[1].get('average_completion_rate', 0)}%，"
                    f"观看过{top_completion[1].get('video_count', 0)}个视频。"
                )
    
    except Exception as e:
        print(f"Error generating completion insights: {str(e)}")
        # 返回一个基础的洞察信息
        insights["basic_completion"] = "暂时无法生成详细的观看完成率分析。"
    
    return insights

def generate_extended_insights(
    continuity_data: dict,
    completion_data: dict,
    time_stats: dict
) -> dict:
    """生成扩展的数据洞察"""
    insights = {}
    
    # 获取各个维度的洞察
    time_insights = generate_time_insights(time_stats)
    completion_insights = generate_completion_insights(completion_data)
    continuity_insights = generate_continuity_insights(continuity_data)
    
    # 合并所有洞察
    insights.update(time_insights)
    insights.update(completion_insights)
    insights.update(continuity_insights)
    
    return insights

def analyze_video_watch_counts(cursor, table_name: str) -> dict:
    """分析视频观看次数"""
    # 获取表结构
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {col[1]: idx for idx, col in enumerate(cursor.fetchall())}
    
    # 确保必要的列存在
    required_columns = ['title', 'bvid', 'duration', 'tag_name', 'author_name']
    for col in required_columns:
        if col not in columns:
            raise ValueError(f"Required column '{col}' not found in table {table_name}")
    
    # 获取视频观看次数统计
    cursor.execute(f"""
        SELECT 
            title,
            bvid,
            duration,
            tag_name,
            author_name,
            COUNT(*) as watch_count,
            MIN(view_at) as first_view,
            MAX(view_at) as last_view
        FROM {table_name}
        WHERE bvid IS NOT NULL AND bvid != ''
        GROUP BY bvid
        HAVING COUNT(*) > 1
        ORDER BY watch_count DESC
    """)
    
    results = cursor.fetchall()
    
    # 处理统计结果
    most_watched_videos = []
    total_rewatched = 0
    total_videos = len(results)
    duration_distribution = {
        "短视频(≤5分钟)": 0,
        "中等视频(5-20分钟)": 0,
        "长视频(>20分钟)": 0
    }
    tag_distribution = {}
    
    for row in results:
        title = row[0]
        bvid = row[1]
        duration = float(row[2]) if row[2] else 0
        tag_name = row[3]
        author_name = row[4]
        watch_count = row[5]
        first_view = row[6]
        last_view = row[7]
        
        # 统计重复观看的视频时长分布
        if duration <= 300:
            duration_distribution["短视频(≤5分钟)"] += 1
        elif duration <= 1200:
            duration_distribution["中等视频(5-20分钟)"] += 1
        else:
            duration_distribution["长视频(>20分钟)"] += 1
        
        # 统计重复观看的视频分区分布
        if tag_name:
            tag_distribution[tag_name] = tag_distribution.get(tag_name, 0) + 1
        
        # 记录观看次数最多的视频
        if len(most_watched_videos) < 10:
            most_watched_videos.append({
                "title": title,
                "bvid": bvid,
                "duration": duration,
                "tag_name": tag_name,
                "author_name": author_name,
                "watch_count": watch_count,
                "first_view": first_view,
                "last_view": last_view,
                "avg_interval": (last_view - first_view) / (watch_count - 1) if watch_count > 1 else 0
            })
        
        total_rewatched += watch_count - 1
    
    # 获取总视频数
    cursor.execute(f"SELECT COUNT(DISTINCT bvid) FROM {table_name}")
    total_unique_videos = cursor.fetchone()[0]
    
    # 计算重复观看率
    rewatch_rate = round(total_videos / total_unique_videos * 100, 2)
    
    # 获取分区排名
    tag_ranking = sorted(
        tag_distribution.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]
    
    return {
        "rewatch_stats": {
            "total_rewatched_videos": total_videos,
            "total_unique_videos": total_unique_videos,
            "rewatch_rate": rewatch_rate,
            "total_rewatch_count": total_rewatched
        },
        "most_watched_videos": most_watched_videos,
        "duration_distribution": duration_distribution,
        "tag_distribution": dict(tag_ranking)
    }

def generate_watch_count_insights(watch_count_data: dict) -> dict:
    """生成视频观看次数相关的洞察"""
    insights = {}
    
    try:
        # 重复观看统计洞察
        rewatch_stats = watch_count_data.get("rewatch_stats", {})
        total_videos = rewatch_stats.get('total_unique_videos', 0)
        rewatched_videos = rewatch_stats.get('total_rewatched_videos', 0)
        rewatch_rate = rewatch_stats.get('rewatch_rate', 0)
        total_rewatches = rewatch_stats.get('total_rewatch_count', 0)
        
        if rewatched_videos > 0:
            avg_watches_per_video = round(total_rewatches/rewatched_videos + 1, 1)
            insights["rewatch_overview"] = (
                f"在你观看的{total_videos}个视频中，有{rewatched_videos}个视频被重复观看，"
                f"重复观看率为{rewatch_rate}%。这些视频总共被额外观看了{total_rewatches}次，"
                f"平均每个重复观看的视频被看了{avg_watches_per_video}次。"
            )
        else:
            insights["rewatch_overview"] = f"在你观看的{total_videos}个视频中，暂时还没有重复观看的视频。"
        
        # 最多观看视频洞察
        most_watched = watch_count_data.get("most_watched_videos", [])
        if most_watched:
            top_videos = most_watched[:3]  # 取前三
            top_video = top_videos[0]
            
            # 计算平均重看间隔（天）
            avg_interval_days = round(top_video.get('avg_interval', 0) / (24 * 3600), 1)
            
            if avg_interval_days > 0:
                insights["most_watched_videos"] = (
                    f"你最喜欢的视频是{top_video.get('author_name', '未知作者')}的《{top_video.get('title', '未知视频')}》，"
                    f"共观看了{top_video.get('watch_count', 0)}次，平均每{avg_interval_days}天就会重看一次。"
                )
            else:
                insights["most_watched_videos"] = (
                    f"你最喜欢的视频是{top_video.get('author_name', '未知作者')}的《{top_video.get('title', '未知视频')}》，"
                    f"共观看了{top_video.get('watch_count', 0)}次。"
                )
            
            if len(top_videos) > 1:
                other_favorites = [
                    f"{v.get('author_name', '未知作者')}的《{v.get('title', '未知视频')}》({v.get('watch_count', 0)}次)"
                    for v in top_videos[1:3]
                ]
                insights["most_watched_videos"] += f"紧随其后的是{' 和 '.join(other_favorites)}。"
        
        # 重复观看视频时长分布洞察
        duration_dist = watch_count_data.get("duration_distribution", {})
        if duration_dist:
            total_rewatched = sum(duration_dist.values())
            if total_rewatched > 0:
                duration_percentages = {
                    k: round(v/total_rewatched * 100, 1)
                    for k, v in duration_dist.items()
                }
                sorted_durations = sorted(
                    duration_percentages.items(),
                    key=lambda x: x[1],
                    reverse=True
                )
                
                insights["duration_preference"] = (
                    f"在重复观看的视频中，{sorted_durations[0][0]}最多，占比{sorted_durations[0][1]}%。"
                    f"其次是{sorted_durations[1][0]}({sorted_durations[1][1]}%)，"
                    f"而{sorted_durations[2][0]}占比{sorted_durations[2][1]}%。"
                    f"这表明你在重复观看时更偏好{sorted_durations[0][0].replace('视频', '')}的内容。"
                )
        
        # 重复观看分区分布洞察
        tag_dist = watch_count_data.get("tag_distribution", {})
        if tag_dist:
            total_tags = sum(tag_dist.values())
            if total_tags > 0:
                top_tags = sorted(tag_dist.items(), key=lambda x: x[1], reverse=True)[:3]
                
                tag_insights = []
                for tag, count in top_tags:
                    percentage = round(count/total_tags * 100, 1)
                    tag_insights.append(f"{tag}({count}个视频, {percentage}%)")
                
                insights["tag_preference"] = (
                    f"你最常重复观看的内容类型是{tag_insights[0]}。"
                    f"紧随其后的是{' 和 '.join(tag_insights[1:])}。"
                )
        
        # 生成总体观看行为总结
        if rewatched_videos > 0:
            insights["behavior_summary"] = (
                f"总的来说，你是一位{_get_rewatch_habit_description(rewatch_rate)}。"
                f"你特别喜欢重复观看{_get_preferred_content_type(tag_dist, duration_dist)}的内容。"
            )
        else:
            insights["behavior_summary"] = "总的来说，你喜欢探索新的内容，很少重复观看同一个视频。"
    
    except Exception as e:
        print(f"Error generating watch count insights: {str(e)}")
        insights["basic_watch_count"] = "暂时无法生成详细的重复观看分析。"
    
    return insights

def _get_rewatch_habit_description(rewatch_rate: float) -> str:
    """根据重复观看率描述用户习惯"""
    if rewatch_rate < 2:
        return "喜欢探索新内容的观众"
    elif rewatch_rate < 5:
        return "对特定内容会重复观看的观众"
    else:
        return "经常重复观看喜欢内容的忠实观众"

def _get_preferred_content_type(tag_dist: dict, duration_dist: dict) -> str:
    """根据分区和时长分布描述用户偏好"""
    if not tag_dist or not duration_dist:
        return "多样化"
        
    top_tag = max(tag_dist.items(), key=lambda x: x[1])[0]
    top_duration = max(duration_dist.items(), key=lambda x: x[1])[0]
    
    return f"{top_duration.replace('视频', '')}的{top_tag}"

def get_available_years():
    """获取数据库中所有可用的年份"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name LIKE 'bilibili_history_%'
            ORDER BY name DESC
        """)
        
        years = []
        for (table_name,) in cursor.fetchall():
            try:
                year = int(table_name.split('_')[-1])
                years.append(year)
            except (ValueError, IndexError):
                continue
                
        return sorted(years, reverse=True)
    except sqlite3.Error as e:
        print(f"获取年份列表时发生错误: {e}")
        return []
    finally:
        if conn:
            conn.close()

@router.get("/")
async def get_viewing_analytics(
    year: Optional[int] = Query(None, description="要分析的年份，不传则使用当前年份"),
    use_cache: bool = Query(True, description="是否使用缓存，默认为True。如果为False则重新分析数据")
):
    """获取用户观看时间分布分析
    
    Args:
        year: 要分析的年份，不传则使用当前年份
        use_cache: 是否使用缓存，默认为True。如果为False则重新分析数据
    
    Returns:
        dict: 包含观看时间分布分析的各个维度的数据
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        
        # 获取可用年份列表
        available_years = get_available_years()
        if not available_years:
            return {
                "status": "error",
                "message": "未找到任何历史记录数据"
            }
        
        # 如果未指定年份，使用最新的年份
        target_year = year if year is not None else available_years[0]
        
        # 检查指定的年份是否可用
        if year is not None and year not in available_years:
            return {
                "status": "error",
                "message": f"未找到 {year} 年的历史记录数据。可用的年份有：{', '.join(map(str, available_years))}"
            }
        
        table_name = f"bilibili_history_{target_year}"
        
        # 如果启用缓存，尝试从缓存获取完整响应
        if use_cache:
            from .title_pattern_discovery import pattern_cache
            cached_response = pattern_cache.get_cached_patterns(table_name, 'viewing_analytics')
            if cached_response:
                print(f"从缓存获取 {target_year} 年的观看时间分析数据")
                return cached_response
        
        print(f"开始分析 {target_year} 年的观看时间数据")
        
        # 1. 月度观看统计
        cursor.execute(f"""
            SELECT 
                strftime('%Y-%m', datetime(view_at, 'unixepoch')) as month,
                COUNT(*) as view_count
            FROM {table_name}
            GROUP BY month
            ORDER BY month
        """)
        monthly_stats = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 2. 每周观看分布（0=周日，1-6=周一至周六）
        weekday_mapping = {'0': '周日', '1': '周一', '2': '周二', '3': '周三', 
                          '4': '周四', '5': '周五', '6': '周六'}
        # 初始化所有星期的默认值为0
        weekly_stats = {day: 0 for day in weekday_mapping.values()}
        cursor.execute(f"""
            SELECT 
                strftime('%w', datetime(view_at, 'unixepoch')) as weekday,
                COUNT(*) as view_count
            FROM {table_name}
            GROUP BY weekday
            ORDER BY weekday
        """)
        # 更新有数据的星期的值
        for row in cursor.fetchall():
            weekly_stats[weekday_mapping[row[0]]] = row[1]
        
        # 3. 每日时段分布（按小时统计）
        cursor.execute(f"""
            SELECT 
                strftime('%H', datetime(view_at, 'unixepoch')) as hour,
                COUNT(*) as view_count
            FROM {table_name}
            GROUP BY hour
            ORDER BY hour
        """)
        daily_time_slots = {f"{int(row[0])}时": row[1] for row in cursor.fetchall()}
        
        # 4. 最活跃时段TOP5
        cursor.execute(f"""
            SELECT 
                strftime('%H', datetime(view_at, 'unixepoch')) as hour,
                COUNT(*) as view_count
            FROM {table_name}
            GROUP BY hour
            ORDER BY view_count DESC
            LIMIT 5
        """)
        peak_hours = [{
            "hour": f"{int(row[0])}时",
            "view_count": row[1]
        } for row in cursor.fetchall()]
        
        # 5. 最高单日观看记录
        cursor.execute(f"""
            SELECT 
                strftime('%Y-%m-%d', datetime(view_at, 'unixepoch')) as date,
                COUNT(*) as view_count
            FROM {table_name}
            GROUP BY date
            ORDER BY view_count DESC
            LIMIT 1
        """)
        max_daily = cursor.fetchone()
        max_daily_record = {
            "date": max_daily[0],
            "view_count": max_daily[1]
        } if max_daily else None
        
        # 6. 计算一些统计指标
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        total_views = cursor.fetchone()[0]
        
        cursor.execute(f"""
            SELECT COUNT(DISTINCT strftime('%Y-%m-%d', datetime(view_at, 'unixepoch')))
            FROM {table_name}
        """)
        active_days = cursor.fetchone()[0]
        
        stats_summary = {
            "total_views": total_views,
            "active_days": active_days,
            "average_daily_views": round(total_views / active_days, 2) if active_days > 0 else 0
        }
        
        # 获取扩展分析数据
        continuity_data = analyze_viewing_continuity(cursor, table_name)
        time_investment_data = analyze_time_investment(cursor, table_name)
        seasonal_data = analyze_seasonal_patterns(cursor, table_name)
        holiday_data = analyze_holiday_patterns(cursor, table_name)
        duration_correlation_data = analyze_duration_time_correlation(cursor, table_name)
        completion_data = analyze_completion_rates(cursor, table_name)
        watch_count_data = analyze_video_watch_counts(cursor, table_name)
        
        # 生成基础洞察
        insights = generate_time_insights({
            "monthly_stats": monthly_stats,
            "weekly_stats": weekly_stats,
            "daily_time_slots": daily_time_slots,
            "peak_hours": peak_hours,
            "max_daily_record": max_daily_record,
            "stats_summary": stats_summary
        })
        
        # 生成扩展洞察
        extended_insights = generate_extended_insights(
            continuity_data,
            completion_data,
            {
                "monthly_stats": monthly_stats,
                "weekly_stats": weekly_stats,
                "daily_time_slots": daily_time_slots,
                "peak_hours": peak_hours,
                "max_daily_record": max_daily_record,
                "stats_summary": stats_summary
            }
        )
        
        # 生成重复观看洞察
        watch_count_insights = generate_watch_count_insights(watch_count_data)
        
        # 构建完整响应
        response = {
            "status": "success",
            "data": {
                'monthly_stats': monthly_stats,
                'weekly_stats': weekly_stats,
                'daily_time_slots': daily_time_slots,
                'peak_hours': peak_hours,
                'max_daily_record': max_daily_record,
                'viewing_continuity': continuity_data,
                'time_investment': time_investment_data,
                'seasonal_patterns': seasonal_data,
                'holiday_patterns': holiday_data,
                'duration_correlation': duration_correlation_data,
                'completion_rates': completion_data,
                'watch_counts': watch_count_data,
                'insights': {**insights, **extended_insights, **watch_count_insights},
                'year': target_year,
                'available_years': available_years
            }
        }
        
        # 如果启用缓存，缓存完整响应
        if use_cache:
            from .title_pattern_discovery import pattern_cache
            print(f"缓存 {target_year} 年的观看时间分析数据")
            pattern_cache.cache_patterns(table_name, 'viewing_analytics', response)
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()
