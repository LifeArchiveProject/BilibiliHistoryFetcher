import sqlite3
from collections import Counter
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import jieba
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from snownlp import SnowNLP

from scripts.utils import load_config, get_output_path
from .title_pattern_discovery import discover_title_patterns, discover_interaction_patterns

router = APIRouter()
config = load_config()

def get_db():
    """获取数据库连接"""
    db_path = get_output_path(config['db_file'])
    return sqlite3.connect(db_path)

def extract_keywords(titles: List[str], top_n: int = 20) -> List[Tuple[str, int]]:
    """
    从标题列表中提取关键词及其频率
    """
    # 停用词列表（可以根据需要扩展）
    stop_words = {'的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
    
    # 所有标题分词后的结果
    all_words = []
    for title in titles:
        if not title:  # 跳过空标题
            continue
        words = jieba.cut(title)
        # 过滤停用词和单字词（通常单字词不能很好地表达含义）
        words = [w for w in words if w not in stop_words and len(w) > 1]
        all_words.extend(words)
    
    # 统计词频
    word_freq = Counter(all_words)
    
    # 返回前N个最常见的词
    return word_freq.most_common(top_n)

def analyze_keywords(titles_data: List[tuple]) -> List[Tuple[str, int]]:
    """
    从标题数据中提取关键词及其频率
    
    Args:
        titles_data: 包含(title, duration, progress, tag_name, view_at)的元组列表
    
    Returns:
        List[Tuple[str, int]]: 关键词和频率的列表
    """
    # 停用词列表（可以根据需要扩展）
    stop_words = {'的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
    
    # 所有标题分词后的结果
    all_words = []
    for title_data in titles_data:
        title = title_data[0]  # 标题在元组的第一个位置
        if not title:  # 跳过空标题
            continue
        words = jieba.cut(title)
        # 过滤停用词和单字词（通常单字词不能很好地表达含义）
        words = [w for w in words if w not in stop_words and len(w) > 1]
        all_words.extend(words)
    
    # 统计词频
    word_freq = Counter(all_words)
    
    # 返回前20个最常见的词
    return word_freq.most_common(20)

def analyze_completion_rates(titles_data: List[tuple]) -> Dict:
    """
    分析标题特征与完成率的关系
    
    Args:
        titles_data: 包含(title, duration, progress, tag_name, view_at)的元组列表
    
    Returns:
        Dict: 完成率分析结果
    """
    # 计算每个视频的完成率
    completion_rates = []
    titles = []
    for title_data in titles_data:
        title = title_data[0]
        duration = float(title_data[1]) if title_data[1] else 0
        progress = float(title_data[2]) if title_data[2] else 0
        
        if duration and progress:  # 确保数据有效
            completion_rate = min(progress / duration, 1.0)  # 限制最大值为1
            completion_rates.append(completion_rate)
            titles.append(title)
    
    # 提取关键词
    keywords = analyze_keywords([(title,) for title in titles])
    
    # 分析包含每个关键词的视频的平均完成率
    keyword_completion_rates = {}
    for keyword, _ in keywords:
        rates = []
        for title, rate in zip(titles, completion_rates):
            if keyword in title:
                rates.append(rate)
        if rates:  # 如果有包含该关键词的视频
            avg_rate = sum(rates) / len(rates)
            keyword_completion_rates[keyword] = {
                'average_completion_rate': avg_rate,
                'video_count': len(rates)
            }
    
    return keyword_completion_rates

def generate_insights(keywords: List[Tuple[str, int]], completion_rates: Dict) -> List[str]:
    """
    根据关键词和完成率生成洞察
    
    Args:
        keywords: 关键词和频率的列表
        completion_rates: 完成率分析结果
    
    Returns:
        List[str]: 洞察列表
    """
    insights = []
    
    # 1. 关键词频率洞察
    top_keywords = [(word, count) for word, count in keywords[:5]]
    if top_keywords:
        insights.append(f"在您观看的视频中，最常出现的关键词是：{', '.join([f'{word}({count}次)' for word, count in top_keywords])}")
    
    # 2. 完成率洞察
    if completion_rates:
        # 按完成率排序
        sorted_rates = sorted(
            [(k, v['average_completion_rate'], v['video_count']) 
             for k, v in completion_rates.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        # 高完成率关键词（前3个）
        high_completion = sorted_rates[:3]
        if high_completion:
            insights.append(f"包含关键词 {', '.join([f'{k}({rate:.1%})' for k, rate, count in high_completion])} 的视频往往会被您看完。")
        
        # 低完成率关键词（后3个）
        low_completion = sorted_rates[-3:]
        low_completion.reverse()  # 从低到高显示
        if low_completion:
            insights.append(f"而包含关键词 {', '.join([f'{k}({rate:.1%})' for k, rate, count in low_completion])} 的视频较少被看完。")
    
    return insights

def analyze_title_completion_rate(conn: sqlite3.Connection) -> Dict:
    """
    分析标题特征与完成率的关系
    """
    cursor = conn.cursor()
    
    # 获取所有视频的标题、时长和观看进度
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
    videos = cursor.fetchall()
    
    # 计算每个视频的完成率
    completion_rates = []
    titles = []
    for title, duration, progress in videos:
        if duration and progress:  # 确保数据有效
            completion_rate = min(progress / duration, 1.0)  # 限制最大值为1
            completion_rates.append(completion_rate)
            titles.append(title)
    
    # 提取关键词
    keywords = extract_keywords(titles, top_n=10)
    
    # 分析包含每个关键词的视频的平均完成率
    keyword_completion_rates = {}
    for keyword, _ in keywords:
        rates = []
        for title, rate in zip(titles, completion_rates):
            if keyword in title:
                rates.append(rate)
        if rates:  # 如果有包含该关键词的视频
            avg_rate = sum(rates) / len(rates)
            keyword_completion_rates[keyword] = {
                'average_completion_rate': avg_rate,
                'video_count': len(rates)
            }
    
    return {
        'keyword_completion_rates': keyword_completion_rates,
        'top_keywords': keywords
    }

def analyze_title_length(cursor, table_name: str) -> dict:
    """分析标题长度与观看行为的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
    """, (table_name.split('_')[-1],))
    
    length_stats = defaultdict(lambda: {'count': 0, 'completion_rates': []})
    
    for title, duration, progress in cursor.fetchall():
        length = len(title)
        completion_rate = progress / duration if duration > 0 else 0
        length_group = (length // 5) * 5  # 按5个字符分组
        length_stats[length_group]['count'] += 1
        length_stats[length_group]['completion_rates'].append(completion_rate)
    
    # 计算每个长度组的平均完成率
    results = {}
    for length_group, stats in length_stats.items():
        avg_completion = np.mean(stats['completion_rates'])
        results[f"{length_group}-{length_group+4}字"] = {
            'count': stats['count'],
            'avg_completion_rate': avg_completion
        }
    
    # 找出最佳长度范围
    best_length = max(results.items(), key=lambda x: x[1]['avg_completion_rate'])
    most_common = max(results.items(), key=lambda x: x[1]['count'])
    
    return {
        'length_stats': results,
        'best_length': best_length[0],
        'most_common_length': most_common[0],
        'insights': [
            f"标题长度在{best_length[0]}的视频最容易被你看完，平均完成率为{best_length[1]['avg_completion_rate']:.1%}",
            f"你观看的视频中，标题长度最常见的是{most_common[0]}，共有{most_common[1]['count']}个视频"
        ]
    }

def analyze_title_sentiment(cursor, table_name: str) -> dict:
    """分析标题情感与观看行为的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
    """, (table_name.split('_')[-1],))
    
    sentiment_stats = {
        '积极': {'count': 0, 'completion_rates': []},
        '中性': {'count': 0, 'completion_rates': []},
        '消极': {'count': 0, 'completion_rates': []}
    }
    
    for title, duration, progress in cursor.fetchall():
        sentiment = SnowNLP(title).sentiments
        completion_rate = progress / duration if duration > 0 else 0
        
        # 情感分类
        if sentiment > 0.6:
            category = '积极'
        elif sentiment < 0.4:
            category = '消极'
        else:
            category = '中性'
            
        sentiment_stats[category]['count'] += 1
        sentiment_stats[category]['completion_rates'].append(completion_rate)
    
    # 计算每种情感的平均完成率
    results = {}
    for sentiment, stats in sentiment_stats.items():
        if stats['count'] > 0:
            results[sentiment] = {
                'count': stats['count'],
                'avg_completion_rate': np.mean(stats['completion_rates'])
            }
    
    # 找出最受欢迎的情感类型
    best_sentiment = max(results.items(), key=lambda x: x[1]['avg_completion_rate'])
    most_common = max(results.items(), key=lambda x: x[1]['count'])
    
    return {
        'sentiment_stats': results,
        'best_sentiment': best_sentiment[0],
        'most_common_sentiment': most_common[0],
        'insights': [
            f"{best_sentiment[0]}情感的视频最容易引起你的兴趣，平均完成率为{best_sentiment[1]['avg_completion_rate']:.1%}",
            f"在你观看的视频中，{most_common[0]}情感的内容最多，共有{most_common[1]['count']}个视频"
        ]
    }

def analyze_title_patterns(cursor, table_name: str) -> dict:
    """分析标题模式与观看行为的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress, tag_name, view_at
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
    """, (table_name.split('_')[-1],))
    
    titles_data = cursor.fetchall()
    
    # 使用模式发现功能，不再传递table_name参数
    discovered_patterns = discover_title_patterns(titles_data)
    
    pattern_stats = defaultdict(lambda: {'count': 0, 'completion_rates': []})
    
    # 分析每个标题的完成率
    for title, duration, progress, *_ in titles_data:
        completion_rate = progress / duration if duration > 0 else 0
        
        # 检查标题属于哪个模式
        matched = False
        for pattern_name, pattern_info in discovered_patterns.items():
            if any(keyword in title for keyword in pattern_info['keywords']):
                pattern_stats[pattern_name]['count'] += 1
                pattern_stats[pattern_name]['completion_rates'].append(completion_rate)
                matched = True
                break
        
        if not matched:
            pattern_stats['其他']['count'] += 1
            pattern_stats['其他']['completion_rates'].append(completion_rate)
    
    # 计算每种模式的平均完成率
    results = {}
    for pattern, stats in pattern_stats.items():
        if stats['count'] > 0:
            results[pattern] = {
                'count': stats['count'],
                'avg_completion_rate': np.mean(stats['completion_rates']),
                'keywords': discovered_patterns[pattern]['keywords'] if pattern in discovered_patterns else []
            }
    
    # 找出最受欢迎的模式
    best_pattern = max(results.items(), key=lambda x: x[1]['avg_completion_rate'])
    most_common = max(results.items(), key=lambda x: x[1]['count'])
    
    return {
        'pattern_stats': results,
        'best_pattern': best_pattern[0],
        'most_common_pattern': most_common[0],
        'insights': [
            f"{best_pattern[0]}类型的视频最容易被你看完，平均完成率为{best_pattern[1]['avg_completion_rate']:.1%}",
            f"你最常观看的是{most_common[0]}类型的视频，共计{most_common[1]['count']}个"
        ]
    }

def analyze_title_clusters(cursor, table_name: str) -> dict:
    """分析标题聚类与观看行为的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
    """, (table_name.split('_')[-1],))
    
    titles = []
    completion_rates = []
    for title, duration, progress in cursor.fetchall():
        titles.append(' '.join(jieba.cut(title)))
        completion_rates.append(progress / duration if duration > 0 else 0)
    
    # 使用TF-IDF向量化标题
    vectorizer = TfidfVectorizer(max_features=1000)
    X = vectorizer.fit_transform(titles)
    
    # K-means聚类
    n_clusters = 5
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    clusters = kmeans.fit_predict(X)
    
    # 分析每个聚类
    cluster_stats = defaultdict(lambda: {'titles': [], 'completion_rates': []})
    for i, (title, cluster, completion_rate) in enumerate(zip(titles, clusters, completion_rates)):
        cluster_stats[f'主题{cluster+1}']['titles'].append(title)
        cluster_stats[f'主题{cluster+1}']['completion_rates'].append(completion_rate)
    
    # 计算每个聚类的特征词和统计信息
    results = {}
    for cluster_name, stats in cluster_stats.items():
        avg_completion = np.mean(stats['completion_rates'])
        # 获取该聚类的特征词
        cluster_titles = stats['titles']
        vectorizer = TfidfVectorizer(max_features=5)
        cluster_vectors = vectorizer.fit_transform(cluster_titles)
        top_words = vectorizer.get_feature_names_out()
        
        results[cluster_name] = {
            'count': len(stats['titles']),
            'avg_completion_rate': avg_completion,
            'key_words': list(top_words)
        }
    
    # 找出最受欢迎的主题
    best_cluster = max(results.items(), key=lambda x: x[1]['avg_completion_rate'])
    most_common = max(results.items(), key=lambda x: x[1]['count'])
    
    return {
        'cluster_stats': results,
        'best_cluster': best_cluster[0],
        'most_common_cluster': most_common[0],
        'insights': [
            f"{best_cluster[0]}(关键词: {', '.join(best_cluster[1]['key_words'])})的视频最容易被你看完，平均完成率为{best_cluster[1]['avg_completion_rate']:.1%}",
            f"你最常观看的是{most_common[0]}(关键词: {', '.join(most_common[1]['key_words'])})相关的视频，共有{most_common[1]['count']}个"
        ]
    }

def analyze_title_trends(cursor, table_name: str) -> dict:
    """分析标题趋势与观看行为的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress, view_at
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
        ORDER BY view_at ASC
    """, (table_name.split('_')[-1],))
    
    # 按月分组的关键词统计和视频计数
    monthly_keywords = defaultdict(lambda: defaultdict(int))
    monthly_video_count = defaultdict(int)  # 新增：每月视频计数
    
    for title, duration, progress, view_at in cursor.fetchall():
        month = datetime.fromtimestamp(view_at).strftime('%Y-%m')
        monthly_video_count[month] += 1  # 新增：增加月度视频计数
        words = jieba.cut(title)
        for word in words:
            if len(word) > 1:  # 排除单字词
                monthly_keywords[month][word] += 1
    
    # 分析每个月的热门关键词
    trending_keywords = {}
    for month, keywords in monthly_keywords.items():
        # 获取当月TOP5关键词
        top_keywords = sorted(keywords.items(), key=lambda x: x[1], reverse=True)[:5]
        trending_keywords[month] = {
            'top_keywords': top_keywords,
            'total_videos': monthly_video_count[month]  # 修改：使用实际的月度视频数量
        }
    
    # 识别关键词趋势
    all_months = sorted(trending_keywords.keys())
    if len(all_months) >= 2:
        first_month = all_months[0]
        last_month = all_months[-1]
        
        # 计算关键词增长率
        first_keywords = set(k for k, _ in trending_keywords[first_month]['top_keywords'])
        last_keywords = set(k for k, _ in trending_keywords[last_month]['top_keywords'])
        
        new_trending = last_keywords - first_keywords
        fading = first_keywords - last_keywords
        consistent = first_keywords & last_keywords
        
        trend_insights = []
        if new_trending:
            trend_insights.append(f"新兴关键词: {', '.join(new_trending)}")
        if consistent:
            trend_insights.append(f"持续热门: {', '.join(consistent)}")
        if fading:
            trend_insights.append(f"减少关注: {', '.join(fading)}")
    else:
        trend_insights = ["数据量不足以分析趋势"]
    
    return {
        'monthly_trends': trending_keywords,
        'insights': trend_insights
    }

def analyze_title_interaction(cursor, table_name: str) -> dict:
    """分析标题与用户互动的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress, tag_name, view_at
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
    """, (table_name.split('_')[-1],))
    
    titles_data = cursor.fetchall()
    
    # 使用互动模式发现功能，不再传递table_name参数
    discovered_patterns = discover_interaction_patterns(titles_data)
    
    interaction_stats = defaultdict(lambda: {'count': 0, 'completion_rates': []})
    
    for title, duration, progress, *_ in titles_data:
        completion_rate = progress / duration if duration > 0 else 0
        found_pattern = False
        
        for pattern_type, pattern_info in discovered_patterns.items():
            if any(keyword in title for keyword in pattern_info['keywords']):
                interaction_stats[pattern_type]['count'] += 1
                interaction_stats[pattern_type]['completion_rates'].append(completion_rate)
                found_pattern = True
        
        if not found_pattern:
            interaction_stats['其他']['count'] += 1
            interaction_stats['其他']['completion_rates'].append(completion_rate)
    
    results = {}
    for pattern, stats in interaction_stats.items():
        if stats['count'] > 0:
            results[pattern] = {
                'count': stats['count'],
                'avg_completion_rate': np.mean(stats['completion_rates']),
                'keywords': discovered_patterns[pattern]['keywords'] if pattern in discovered_patterns else []
            }
    
    best_pattern = max(results.items(), key=lambda x: x[1]['avg_completion_rate'])
    most_common = max(results.items(), key=lambda x: x[1]['count'])
    
    return {
        'interaction_stats': results,
        'best_pattern': best_pattern[0],
        'most_common_pattern': most_common[0],
        'insights': [
            f"{best_pattern[0]}互动方式的标题最容易引起互动，平均完成率为{best_pattern[1]['avg_completion_rate']:.1%}",
            f"在你观看的视频中，{most_common[0]}互动方式最常见，共有{most_common[1]['count']}个视频"
        ]
    }

def analyze_title_duration_correlation(cursor, table_name: str) -> dict:
    """分析标题特征与视频时长的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
    """, (table_name.split('_')[-1],))
    
    # 按时长分组
    duration_groups = {
        '短视频(0-5分钟)': (0, 300),
        '中等(5-15分钟)': (300, 900),
        '长视频(15-30分钟)': (900, 1800),
        '超长(30分钟以上)': (1800, float('inf'))
    }
    
    duration_stats = defaultdict(lambda: {
        'title_lengths': [],
        'completion_rates': [],
        'count': 0,
        'keywords': Counter()
    })
    
    for title, duration, progress in cursor.fetchall():
        completion_rate = progress / duration if duration > 0 else 0
        
        # 确定时长分组
        for group_name, (min_dur, max_dur) in duration_groups.items():
            if min_dur <= duration < max_dur:
                stats = duration_stats[group_name]
                stats['title_lengths'].append(len(title))
                stats['completion_rates'].append(completion_rate)
                stats['count'] += 1
                
                # 提取关键词
                words = jieba.cut(title)
                stats['keywords'].update(w for w in words if len(w) > 1)
                break
    
    results = {}
    for group, stats in duration_stats.items():
        if stats['count'] > 0:
            results[group] = {
                'avg_title_length': np.mean(stats['title_lengths']),
                'avg_completion_rate': np.mean(stats['completion_rates']),
                'count': stats['count'],
                'top_keywords': stats['keywords'].most_common(5)
            }
    
    best_duration = max(results.items(), key=lambda x: x[1]['avg_completion_rate'])
    most_common = max(results.items(), key=lambda x: x[1]['count'])
    
    return {
        'duration_stats': results,
        'best_duration': best_duration[0],
        'most_common_duration': most_common[0],
        'insights': [
            f"{best_duration[0]}类视频最容易被看完，平均完成率为{best_duration[1]['avg_completion_rate']:.1%}",
            f"你最常观看{most_common[0]}的视频，共有{most_common[1]['count']}个"
        ]
    }

def analyze_title_feature_combinations(cursor, table_name: str) -> dict:
    """分析标题特征组合与观看行为的关系"""
    cursor.execute(f"""
        SELECT title, duration, progress, tag_name, view_at
        FROM {table_name}
        WHERE duration > 0 AND title IS NOT NULL
        AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
    """, (table_name.split('_')[-1],))
    
    titles_data = cursor.fetchall()
    
    # 获取标题模式
    discovered_patterns = discover_title_patterns(titles_data)
    
    # 定义特征检测函数
    def get_sentiment(title):
        sentiment = SnowNLP(title).sentiments
        if sentiment > 0.6:
            return '积极'
        elif sentiment < 0.4:
            return '消极'
        return '中性'
    
    def get_pattern(title):
        for pattern_name, pattern_info in discovered_patterns.items():
            if any(keyword in title for keyword in pattern_info['keywords']):
                return pattern_name
        return '其他'
    
    combination_stats = defaultdict(lambda: {'count': 0, 'completion_rates': []})
    
    for title, duration, progress, *_ in titles_data:
        completion_rate = progress / duration if duration > 0 else 0
        
        # 获取标题特征组合
        sentiment = get_sentiment(title)
        pattern = get_pattern(title)
        combination = f"{pattern}+{sentiment}"
        
        combination_stats[combination]['count'] += 1
        combination_stats[combination]['completion_rates'].append(completion_rate)
    
    results = {}
    for combination, stats in combination_stats.items():
        if stats['count'] >= 5:  # 只分析样本量足够的组合
            results[combination] = {
                'count': stats['count'],
                'avg_completion_rate': np.mean(stats['completion_rates'])
            }
    
    best_combination = max(results.items(), key=lambda x: x[1]['avg_completion_rate'])
    most_common = max(results.items(), key=lambda x: x[1]['count'])
    
    return {
        'combination_stats': results,
        'best_combination': best_combination[0],
        'most_common_combination': most_common[0],
        'insights': [
            f"{best_combination[0]}组合的标题最容易被看完，平均完成率为{best_combination[1]['avg_completion_rate']:.1%}",
            f"你最常看到的是{most_common[0]}组合的标题，共有{most_common[1]['count']}个视频"
        ]
    }

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
async def get_title_analytics(
    year: Optional[int] = Query(None, description="要分析的年份，不传则使用当前年份"),
    use_cache: bool = Query(True, description="是否使用缓存，默认为True。如果为False则重新分析数据")
):
    """获取标题分析数据
    
    Args:
        year: 要分析的年份，不传则使用当前年份
        use_cache: 是否使用缓存，默认为True。如果为False则重新分析数据
    
    Returns:
        dict: 包含标题分析的各个维度的数据
    """
    try:
        conn = get_db()
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
            cached_response = pattern_cache.get_cached_patterns(table_name, 'full_response')
            if cached_response:
                print(f"从缓存获取 {target_year} 年的分析数据")
                return cached_response
        
        print(f"开始分析 {target_year} 年的数据")
        
        # 获取所有标题，添加年份限制
        cursor.execute(f"""
            SELECT title, duration, progress, tag_name, view_at
            FROM {table_name}
            WHERE title IS NOT NULL AND title != ''
            AND strftime('%Y', datetime(view_at, 'unixepoch')) = ?
        """, (str(target_year),))
        titles = cursor.fetchall()
        
        if not titles:
            return {
                "status": "error",
                "message": "未找到任何有效的标题数据"
            }
        
        # 分词和关键词提取
        keywords = analyze_keywords(titles)
        
        # 分析完成率
        completion_analysis = analyze_completion_rates(titles)
        
        # 生成洞察
        insights = generate_insights(keywords, completion_analysis)
        
        # 获取新增的分析结果
        length_analysis = analyze_title_length(cursor, table_name)
        sentiment_analysis = analyze_title_sentiment(cursor, table_name)
        pattern_analysis = analyze_title_patterns(cursor, table_name)
        cluster_analysis = analyze_title_clusters(cursor, table_name)
        trend_analysis = analyze_title_trends(cursor, table_name)
        
        # 新增分析维度
        interaction_analysis = analyze_title_interaction(cursor, table_name)
        duration_correlation = analyze_title_duration_correlation(cursor, table_name)
        feature_combinations = analyze_title_feature_combinations(cursor, table_name)
        
        # 构建完整响应
        response = {
            "status": "success",
            "data": {
                "keyword_analysis": {
                    "top_keywords": [{"word": word, "count": count} for word, count in keywords],
                    "completion_rates": completion_analysis
                },
                "length_analysis": length_analysis,
                "sentiment_analysis": sentiment_analysis,
                "pattern_analysis": pattern_analysis,
                "cluster_analysis": cluster_analysis,
                "trend_analysis": trend_analysis,
                "interaction_analysis": interaction_analysis,
                "duration_correlation": duration_correlation,
                "feature_combinations": feature_combinations,
                "insights": insights,
                "year": target_year,
                "available_years": available_years
            }
        }
        
        # 无论是否启用缓存，都更新缓存数据
        from .title_pattern_discovery import pattern_cache
        print(f"更新 {target_year} 年的分析数据缓存")
        pattern_cache.cache_patterns(table_name, 'full_response', response)
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()
