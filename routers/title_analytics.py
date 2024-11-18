import sqlite3
from collections import Counter
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

import jieba
import numpy as np
from fastapi import APIRouter, HTTPException
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from snownlp import SnowNLP

from scripts.utils import load_config, get_output_path

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

def analyze_title_length(cursor) -> dict:
    """分析标题长度与观看行为的关系"""
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
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

def analyze_title_sentiment(cursor) -> dict:
    """分析标题情感与观看行为的关系"""
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
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

def analyze_title_patterns(cursor) -> dict:
    """分析标题模式与观看行为的关系"""
    patterns = {
        '教程': ['教程', '教学', '入门', '指南', '技巧', '方法', '怎么', '如何'],
        '排名': ['排名', '榜单', 'TOP', '最佳', '最强', '最美', '第一'],
        '解说': ['解说', '分析', '讲解', '详解', '探索', '揭秘'],
        '评测': ['评测', '测评', '体验', '评价', '优缺点'],
        '娱乐': ['搞笑', '有趣', '沙雕', '逗比', '泪目', '感动'],
    }
    
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
    pattern_stats = defaultdict(lambda: {'count': 0, 'completion_rates': []})
    
    for title, duration, progress in cursor.fetchall():
        completion_rate = progress / duration if duration > 0 else 0
        
        # 检查标题属于哪种模式
        matched = False
        for pattern_name, keywords in patterns.items():
            if any(keyword in title for keyword in keywords):
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
                'avg_completion_rate': np.mean(stats['completion_rates'])
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

def analyze_title_clusters(cursor) -> dict:
    """使用K-means对标题进行主题聚类分析"""
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
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

def analyze_title_trends(cursor) -> dict:
    """分析标题关键词随时间的变化趋势"""
    cursor.execute("""
        SELECT title, view_at
        FROM bilibili_history_2024
        WHERE title IS NOT NULL
        ORDER BY view_at
    """)
    
    # 按月分组的关键词统计
    monthly_keywords = defaultdict(lambda: defaultdict(int))
    
    for title, view_at in cursor.fetchall():
        month = datetime.fromtimestamp(view_at).strftime('%Y-%m')
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
            'total_videos': sum(keywords.values())
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

def analyze_title_interaction(cursor) -> dict:
    """分析标题互动元素与观看行为的关系"""
    interaction_patterns = {
        '对话式': ['来聊聊', '一起', '讨论', '分享', '告诉你'],
        '疑问式': ['为什么', '是什么', '怎么样', '如何'],
        '悬念式': ['震惊', '万万没想到', '竟然', '居然', '惊人'],
        '引导式': ['建议', '推荐', '必看', '不要错过'],
    }
    
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
    interaction_stats = defaultdict(lambda: {'count': 0, 'completion_rates': []})
    
    for title, duration, progress in cursor.fetchall():
        completion_rate = progress / duration if duration > 0 else 0
        found_pattern = False
        
        for pattern_type, keywords in interaction_patterns.items():
            if any(keyword in title for keyword in keywords):
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
                'avg_completion_rate': np.mean(stats['completion_rates'])
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

def analyze_title_duration_correlation(cursor) -> dict:
    """分析标题特征与视频时长的关系"""
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
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

def analyze_title_feature_combinations(cursor) -> dict:
    """分析标题特征组合与观看行为的关系"""
    cursor.execute("""
        SELECT title, duration, progress
        FROM bilibili_history_2024
        WHERE duration > 0 AND title IS NOT NULL
    """)
    
    # 定义特征检测函数
    def get_sentiment(title):
        sentiment = SnowNLP(title).sentiments
        if sentiment > 0.6:
            return '积极'
        elif sentiment < 0.4:
            return '消极'
        return '中性'
    
    def get_pattern(title):
        patterns = {
            '教程': ['教程', '教学', '入门', '指南', '技巧'],
            '排名': ['排名', '榜单', 'TOP', '最佳', '最强'],
            '解说': ['解说', '分析', '讲解', '详解', '探索'],
            '评测': ['评测', '测评', '体验', '评价'],
            '娱乐': ['搞笑', '有趣', '沙雕', '逗比']
        }
        
        for pattern, keywords in patterns.items():
            if any(keyword in title for keyword in keywords):
                return pattern
        return '其他'
    
    combination_stats = defaultdict(lambda: {'count': 0, 'completion_rates': []})
    
    for title, duration, progress in cursor.fetchall():
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

@router.get("/title-analytics")
async def get_title_analytics():
    """
    获取标题分析结果，包括关键词分析和完成率关联分析
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 获取所有有效的标题
        cursor.execute("""
            SELECT title
            FROM bilibili_history_2024
            WHERE title IS NOT NULL
        """)
        
        titles = [row[0] for row in cursor.fetchall() if row[0]]
        
        # 提取关键词
        keywords = extract_keywords(titles)
        
        # 分析标题与完成率的关系
        completion_analysis = analyze_title_completion_rate(conn)
        
        # 生成洞察
        insights = []
        
        # 1. 关键词频率洞察
        insights.append(f"在您观看的视频中，最常出现的关键词是：{', '.join([f'{word}({count}次)' for word, count in keywords[:5]])}")
        
        # 2. 完成率洞察
        completion_rates = completion_analysis['keyword_completion_rates']
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
            insights.append(f"包含关键词 {', '.join([f'{k}({rate:.1%})' for k, rate, count in high_completion])} 的视频往往会被您看完。")
            
            # 低完成率关键词（后3个）
            low_completion = sorted_rates[-3:]
            low_completion.reverse()  # 从低到高显示
            insights.append(f"而包含关键词 {', '.join([f'{k}({rate:.1%})' for k, rate, count in low_completion])} 的视频较少被看完。")
        
        # 获取新增的分析结果
        length_analysis = analyze_title_length(cursor)
        sentiment_analysis = analyze_title_sentiment(cursor)
        pattern_analysis = analyze_title_patterns(cursor)
        cluster_analysis = analyze_title_clusters(cursor)
        trend_analysis = analyze_title_trends(cursor)
        
        # 新增分析维度
        interaction_analysis = analyze_title_interaction(cursor)
        duration_correlation = analyze_title_duration_correlation(cursor)
        feature_combinations = analyze_title_feature_combinations(cursor)
        
        return {
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
                "insights": insights
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()
