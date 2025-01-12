import sqlite3
from collections import Counter, defaultdict
from typing import List, Dict, Tuple, Set, Optional
import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from snownlp import SnowNLP
import json
import os
from datetime import datetime, timedelta

class PatternCache:
    """模式缓存管理器"""
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            # 使用项目根目录下的cache文件夹
            import sys
            import os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.cache_dir = os.path.join(project_root, "cache")
        else:
            self.cache_dir = cache_dir
            
        # 确保缓存目录存在并设置正确的权限
        try:
            print(f"尝试创建缓存目录: {self.cache_dir}")
            
            # 如果目录不存在，创建它
            if not os.path.exists(self.cache_dir):
                os.makedirs(self.cache_dir, mode=0o755, exist_ok=True)
                print(f"缓存目录已创建: {self.cache_dir}")
            
            # 确保目录权限正确
            os.chmod(self.cache_dir, 0o755)
            print(f"缓存目录权限已设置为755")
            
            # 获取当前用户和组
            import pwd
            import grp
            current_user = os.getlogin() if hasattr(os, 'getlogin') else pwd.getpwuid(os.getuid()).pw_name
            current_group = grp.getgrgid(os.getgid()).gr_name if hasattr(grp, 'getgrgid') else None
            
            print(f"当前用户: {current_user}")
            if current_group:
                print(f"当前用户组: {current_group}")
            
            # 检查目录权限
            mode = oct(os.stat(self.cache_dir).st_mode)[-3:]
            print(f"缓存目录权限: {mode}")
            
            # 尝试创建测试文件以验证写入权限
            test_file = os.path.join(self.cache_dir, "test.txt")
            try:
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                print("缓存目录写入权限验证成功")
            except Exception as e:
                print(f"缓存目录写入权限验证失败: {str(e)}")
                print(f"错误类型: {type(e).__name__}")
                print(f"错误详情: {str(e)}")
                
        except Exception as e:
            print(f"创建缓存目录时出错: {str(e)}")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误详情: {str(e)}")
            # 如果是权限问题，打印更多信息
            if isinstance(e, PermissionError):
                print(f"当前用户: {os.getlogin() if hasattr(os, 'getlogin') else 'unknown'}")
                print(f"当前工作目录: {os.getcwd()}")
                print(f"目录是否存在: {os.path.exists(self.cache_dir)}")
                if os.path.exists(self.cache_dir):
                    print(f"目录权限: {oct(os.stat(self.cache_dir).st_mode)[-3:]}")
    
    def _get_cache_path(self, table_name: str, pattern_type: str) -> str:
        """获取缓存文件路径"""
        cache_file = f"{table_name}_{pattern_type}_patterns.json"
        cache_path = os.path.join(self.cache_dir, cache_file)
        print(f"缓存文件路径: {cache_path}")
        return cache_path
    
    def get_cached_patterns(self, table_name: str, pattern_type: str) -> Optional[Dict]:
        """
        获取缓存的模式数据
        
        Args:
            table_name: 数据表名
            pattern_type: 模式类型（'title' 或 'interaction'）
        
        Returns:
            Dict | None: 缓存的模式数据，如果缓存不存在则返回None
        """
        try:
            cache_path = self._get_cache_path(table_name, pattern_type)
            if not os.path.exists(cache_path):
                print(f"缓存文件不存在: {cache_path}")
                return None
            
            print(f"读取缓存文件: {cache_path}")
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"成功读取缓存数据，包含 {len(data)} 个模式")
                return data
                
        except Exception as e:
            print(f"读取缓存时出错: {str(e)}")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误详情: {str(e)}")
            return None
    
    def cache_patterns(self, table_name: str, pattern_type: str, patterns: Dict) -> None:
        """
        缓存模式数据
        
        Args:
            table_name: 数据表名
            pattern_type: 模式类型（'title' 或 'interaction'）
            patterns: 要缓存的模式数据
        """
        try:
            if not patterns:
                print("没有模式数据需要缓存")
                return
                
            cache_path = self._get_cache_path(table_name, pattern_type)
            print(f"准备写入缓存: {cache_path}")
            print(f"缓存数据包含 {len(patterns)} 个模式")
            
            # 确保目录存在
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(patterns, f, ensure_ascii=False, indent=2)
                print(f"成功写入缓存: {cache_path}")
                
        except Exception as e:
            print(f"写入缓存时出错: {str(e)}")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误详情: {str(e)}")
            # 如果是权限问题，打印更多信息
            if isinstance(e, PermissionError):
                print(f"缓存目录权限: {oct(os.stat(self.cache_dir).st_mode)[-3:]}")
                print(f"当前用户: {os.getlogin()}")
                print(f"当前工作目录: {os.getcwd()}")
                print(f"目录是否存在: {os.path.exists(self.cache_dir)}")
                if os.path.exists(self.cache_dir):
                    print(f"目录权限: {oct(os.stat(self.cache_dir).st_mode)[-3:]}")
                    
# 创建全局缓存管理器实例
pattern_cache = PatternCache()

def get_stop_words() -> Set[str]:
    """获取停用词列表"""
    return {
        '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', 
        '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '啊', '呢', '吧',
        '吗', '啦', '呀', '哦', '哈', '嘿', '哎', '哟', '唉', '嗯', '嘛', '哼', '哇', '咦', '诶', '喂',
        '么', '什么', '这个', '那个', '这样', '那样', '怎么', '为什么', '如何', '哪里', '谁', '什么时候',
        '多少', '几', '怎样', '为何', '哪个', '哪些', '几个', '多久', '多长时间', '什么样'
    }

def collect_title_data(cursor: sqlite3.Cursor, table_name: str) -> List[Tuple[str, float, float, str, int]]:
    """
    从数据库收集标题数据
    
    Args:
        cursor: 数据库游标
        table_name: 表名
    
    Returns:
        List[Tuple]: 包含(title, duration, progress, tag_name, view_at)的元组列表
    """
    cursor.execute(f"""
        SELECT title, duration, progress, tag_name, view_at
        FROM {table_name}
        WHERE title IS NOT NULL AND title != ''
    """)
    return cursor.fetchall()

def preprocess_titles(titles_data: List[Tuple[str, float, float, str, int]]) -> List[str]:
    """
    预处理标题文本
    
    Args:
        titles_data: 原始标题数据
    
    Returns:
        List[str]: 预处理后的标题列表
    """
    stop_words = get_stop_words()
    processed_titles = []
    
    for title_data in titles_data:
        title = title_data[0]
        # 分词
        words = jieba.cut(title)
        # 过滤停用词和单字词
        filtered_words = [w for w in words if w not in stop_words and len(w) > 1]
        # 重新组合成句子
        processed_title = ' '.join(filtered_words)
        processed_titles.append(processed_title)
    
    return processed_titles

def extract_title_features(processed_titles: List[str], n_features: int = 1000) -> Tuple[TfidfVectorizer, np.ndarray]:
    """
    提取标题特征
    
    Args:
        processed_titles: 预处理后的标题列表
        n_features: 特征数量
    
    Returns:
        Tuple: (TF-IDF向量器, 特征矩阵)
    """
    vectorizer = TfidfVectorizer(max_features=n_features)
    features = vectorizer.fit_transform(processed_titles)
    return vectorizer, features

def validate_patterns(titles_data: List[Tuple[str, float, float, str, int]], patterns: Dict) -> Dict:
    """
    验证和优化发现的模式
    
    Args:
        titles_data: 原始标题数据
        patterns: 发现的模式字典
    
    Returns:
        Dict: 优化后的模式字典
    """
    print(f"开始验证模式，标题数量: {len(titles_data)}, 模式数量: {len(patterns)}")
    # 计算每个模式的覆盖率和区分度
    pattern_metrics = {}
    total_titles = len(titles_data)
    if total_titles == 0:  # 如果没有标题数据，直接返回原始模式
        return {name: {**info, 'metrics': {
            'coverage': 0,
            'distinctiveness': 0,
            'unique_matches': 0,
            'shared_matches': 0
        }} for name, info in patterns.items()}
    
    titles = [t[0] for t in titles_data]  # 提取标题文本
    
    # 计算每个模式的覆盖率和区分度
    for pattern_name, pattern_info in patterns.items():
        # 计算该模式覆盖的标题数量
        covered_titles = sum(1 for title in titles 
                           if any(keyword in title for keyword in pattern_info['keywords']))
        
        # 计算覆盖率
        coverage = covered_titles / total_titles
        
        # 计算区分度（独特性）
        unique_coverage = 0
        shared_coverage = 0
        for title in titles:
            # 检查当前模式是否匹配
            current_matches = any(keyword in title for keyword in pattern_info['keywords'])
            if current_matches:
                # 检查其他模式是否也匹配
                other_matches = sum(1 for other_name, other_info in patterns.items()
                                  if other_name != pattern_name and
                                  any(keyword in title for keyword in other_info['keywords']))
                if other_matches == 0:
                    unique_coverage += 1
                else:
                    shared_coverage += 1
        
        # 计算区分度，避免除零错误
        total_matches = unique_coverage + shared_coverage
        distinctiveness = unique_coverage / total_matches if total_matches > 0 else 0
        
        pattern_metrics[pattern_name] = {
            'coverage': coverage,
            'distinctiveness': distinctiveness,
            'unique_matches': unique_coverage,
            'shared_matches': shared_coverage
        }
    
    # 优化模式
    optimized_patterns = {}
    for pattern_name, pattern_info in patterns.items():
        metrics = pattern_metrics[pattern_name]
        
        # 如果模式的覆盖率太低或区分度太低，尝试优化
        if metrics['coverage'] < 0.05 or metrics['distinctiveness'] < 0.3:
            # 获取该模式下的所有标题
            pattern_titles = [title for title in titles 
                            if any(keyword in title for keyword in pattern_info['keywords'])]
            
            # 重新提取关键词，使用更严格的TF-IDF阈值
            if pattern_titles:
                try:
                    vectorizer = TfidfVectorizer(max_features=5)  # 减少关键词数量，提高精确性
                    features = vectorizer.fit_transform(pattern_titles)
                    keywords = vectorizer.get_feature_names_out()
                    
                    # 更新模式信息
                    optimized_patterns[pattern_name] = {
                        'keywords': list(keywords),
                        'sentiment': pattern_info['sentiment'],
                        'sample_size': len(pattern_titles),
                        'metrics': metrics
                    }
                except Exception:
                    # 如果TF-IDF提取失败，保持原有关键词
                    optimized_patterns[pattern_name] = {
                        **pattern_info,
                        'metrics': metrics
                    }
            else:
                # 如果没有匹配的标题，保持原有模式
                optimized_patterns[pattern_name] = {
                    **pattern_info,
                    'metrics': metrics
                }
        else:
            # 保持原有模式，只添加指标信息
            optimized_patterns[pattern_name] = {
                **pattern_info,
                'metrics': metrics
            }
    
    return optimized_patterns

def discover_title_patterns(titles_data: List[Tuple[str, float, float, str, int]], n_clusters: int = 5) -> Dict:
    """
    发现标题模式
    
    Args:
        titles_data: 原始标题数据
        n_clusters: 聚类数量
    
    Returns:
        Dict: 发现的模式及其关键词
    """
    # 数据验证
    if not titles_data:
        return {
            'default': {
                'keywords': [],
                'sentiment': 0.5,
                'sample_size': 0,
                'metrics': {
                    'coverage': 0,
                    'distinctiveness': 0,
                    'unique_matches': 0,
                    'shared_matches': 0
                }
            }
        }
    
    # 预处理标题
    processed_titles = preprocess_titles(titles_data)
    if not processed_titles:  # 如果预处理后没有有效标题
        return {
            'default': {
                'keywords': [],
                'sentiment': 0.5,
                'sample_size': 0,
                'metrics': {
                    'coverage': 0,
                    'distinctiveness': 0,
                    'unique_matches': 0,
                    'shared_matches': 0
                }
            }
        }
    
    # 调整聚类数量，确保不超过标题数量
    actual_n_clusters = min(n_clusters, len(processed_titles))
    if actual_n_clusters < 2:  # 如果数据太少，不进行聚类
        # 直接使用TF-IDF提取关键词
        try:
            vectorizer = TfidfVectorizer(max_features=10)
            features = vectorizer.fit_transform(processed_titles)
            keywords = list(vectorizer.get_feature_names_out())
            
            # 计算情感倾向
            sentiments = [SnowNLP(title).sentiments for title in processed_titles]
            avg_sentiment = float(np.mean(sentiments))
            
            patterns = {
                '默认模式': {
                    'keywords': keywords,
                    'sentiment': avg_sentiment,
                    'sample_size': len(processed_titles)
                }
            }
            
            # 验证和优化模式
            optimized_patterns = validate_patterns(titles_data, patterns)
            return optimized_patterns
            
        except Exception as e:
            print(f"Error in TF-IDF processing: {str(e)}")
            return {
                'default': {
                    'keywords': [],
                    'sentiment': 0.5,
                    'sample_size': 0,
                    'metrics': {
                        'coverage': 0,
                        'distinctiveness': 0,
                        'unique_matches': 0,
                        'shared_matches': 0
                    }
                }
            }
    
    try:
        # 提取特征
        vectorizer, features = extract_title_features(processed_titles)
        
        # 聚类
        kmeans = KMeans(n_clusters=actual_n_clusters, random_state=42)
        clusters = kmeans.fit_predict(features)
        
        # 分析每个聚类的特征词
        patterns = {}
        for i in range(actual_n_clusters):
            # 获取该聚类的标题索引
            cluster_indices = np.where(clusters == i)[0]
            if len(cluster_indices) == 0:  # 如果聚类为空，跳过
                continue
                
            cluster_titles = [processed_titles[idx] for idx in cluster_indices]
            
            try:
                # 为该聚类创建新的TF-IDF向量器
                cluster_vectorizer = TfidfVectorizer(max_features=10)
                cluster_features = cluster_vectorizer.fit_transform(cluster_titles)
                
                # 获取特征词
                feature_names = cluster_vectorizer.get_feature_names_out()
                
                # 计算该聚类的主要情感倾向
                sentiments = [SnowNLP(title).sentiments for title in cluster_titles]
                avg_sentiment = float(np.mean(sentiments))
                
                # 根据情感和关键词确定模式名称
                if avg_sentiment > 0.6:
                    pattern_type = '积极'
                elif avg_sentiment < 0.4:
                    pattern_type = '消极'
                else:
                    pattern_type = '中性'
                
                # 存储模式信息
                patterns[f'模式{i+1}_{pattern_type}'] = {
                    'keywords': list(feature_names),
                    'sentiment': avg_sentiment,
                    'sample_size': len(cluster_titles)
                }
            except Exception as e:
                print(f"Error processing cluster {i}: {str(e)}")
                continue
        
        # 如果没有成功创建任何模式，返回默认模式
        if not patterns:
            return {
                'default': {
                    'keywords': [],
                    'sentiment': 0.5,
                    'sample_size': 0,
                    'metrics': {
                        'coverage': 0,
                        'distinctiveness': 0,
                        'unique_matches': 0,
                        'shared_matches': 0
                    }
                }
            }
        
        # 验证和优化模式
        optimized_patterns = validate_patterns(titles_data, patterns)
        return optimized_patterns
        
    except Exception as e:
        print(f"Error in pattern discovery: {str(e)}")
        return {
            'default': {
                'keywords': [],
                'sentiment': 0.5,
                'sample_size': 0,
                'metrics': {
                    'coverage': 0,
                    'distinctiveness': 0,
                    'unique_matches': 0,
                    'shared_matches': 0
                }
            }
        }

def discover_interaction_patterns(titles_data: List[Tuple[str, float, float, str, int]]) -> Dict:
    """
    发现互动模式
    
    Args:
        titles_data: 原始标题数据
    
    Returns:
        Dict: 发现的互动模式及其关键词
    """
    try:
        # 数据验证
        if not titles_data:
            return {
                'default': {
                    'keywords': [],
                    'sample_size': 0,
                    'metrics': {
                        'coverage': 0,
                        'distinctiveness': 0,
                        'unique_matches': 0,
                        'shared_matches': 0
                    }
                }
            }
        
        # 预处理标题
        processed_titles = preprocess_titles(titles_data)
        if not processed_titles:  # 如果预处理后没有有效标题
            return {
                'default': {
                    'keywords': [],
                    'sample_size': 0,
                    'metrics': {
                        'coverage': 0,
                        'distinctiveness': 0,
                        'unique_matches': 0,
                        'shared_matches': 0
                    }
                }
            }
        
        # 定义基本的语言模式特征
        question_markers = {
            # 基础疑问词
            '?', '？', '吗', '呢', '么', '嘛', '吧',
            # 特定疑问词
            '什么', '为什么', '如何', '怎么', '怎样', '几时', '哪里', '谁', '多少',
            '哪个', '哪些', '几个', '多久', '怎么办', '怎么样', '为何', '是不是',
            # 疑问词组
            '难道说', '究竟是', '到底是', '是否', '能否', '可否', '何必', '何不',
            '为何要', '怎么会', '怎么能', '如何才能', '为什么会', '是不是要',
            # 反问词组
            '岂不是', '难道不', '怎能不', '何尝不', '谁不',
            # 网络流行疑问
            '啥玩意', '啥情况', '咋回事', '咋办', '咋整', '啥意思',
            '这是啥', '这是什么', '这啥啊', '这怎么回事',
            '这合理吗', '这能行吗', '这靠谱吗', '这玩意儿',
            '搞啥呢', '闹哪样', '整啥活', '整这出'
        }
        
        exclamation_markers = {
            # 基础感叹词
            '!', '！', '啊', '哇', '哦', '呀', '呐', '哎', '诶', '咦',
            # 程度词
            '太', '真', '好', '非常', '超级', '特别', '极其', '格外', '分外',
            '相当', '十分', '很是', '尤其', '特', '超', '贼', '巨',
            # 感叹词组
            '太棒了', '真棒', '好厉害', '太强了', '太牛了', '太秀了', '绝了',
            '震惊', '惊呆了', '厉害了', '牛逼', '卧槽', '我的天', '天呐',
            '要命', '要死了', '受不了', '没谁了', '绝绝子', '太可了', '太爱了',
            # 正面评价
            '完美', '神级', '顶级', '极品', '优秀', '精彩', '精品', '经典',
            '必看', '值得', '推荐', '珍藏', '收藏', '赞', '好评',
            # 负面感叹
            '可怕', '恐怖', '吓人', '要命', '糟糕', '完蛋', '惨', '惨了',
            '可恶', '气死', '无语', '离谱', '扯淡', '要疯了',
            # B站特色感叹
            '草', '蚌埠住了', '绷不住了', '崩溃', '破防了', '麻了', '顶不住了',
            '笑死', '笑yue了', '笑死我了', '乐死我了', '乐', '孝死',
            '爷青回', '爷青结', '爷哭了', '泪目', '呜呜呜', '呜呜',
            '啊这', '这河里吗', '这不河里', '这不对劲', '这不科学',
            # 2023-2024热梗
            '鼠鼠我啊', '答应我', '不要再', '给我狠狠', '给我使劲',
            '啊对对对', '好似', '开香槟咯', '大胆', '荒谬', 
            '我说不要', '我说要要要', '不认识', '很会', '很懂',
            '不懂就问', '求求了', '人生建议', '建议', '速速',
            '狠狠', '使劲', '疯狂', '大声', '大胆',
            # 2024新梗
            '纯纯', '典典', '润润', '狂狂', '疯疯',
            '笑死个人', '急急国王', '急急子', '急了急了',
            '慌慌子', '慌了慌了', '酸酸子', '酸了酸了',
            '急了蚌', '笑死蚌', '破防蚌', '麻了蚌',
            # 网络流行语
            '太上头了', '上头', '太香了', '香疯了', '太戳了', '戳爆了',
            '太欧了', '太非了', '太悲伤了', '太难了', '太难蚌了',
            '太难绷了', '太离谱了', '太荒谬了', '太逆天了', '太致命了',
            '太邪门了', '太魔幻了', '太真实了', '太炸裂了', '太生草了',
            # 新增流行语
            '真的会谢', '真的会哭', '真的会笑', '真的会玩',
            '狠狠地心动', '狠狠地心疼', '狠狠地感动', '狠狠地共情',
            '生死时速', '生死时刻', '生死时分', '生死关头',
            '一整个', '一整个爱了', '一整个哭了', '一整个笑了',
            # 夸张表达
            '吊炸天', '厉害炸了', '牛炸了', '强炸了', '秀炸了',
            '猛炸了', '狠炸了', '吓死人', '笑死人', '气死人',
            '玩明白了', '玩懂了', '玩透了', '整明白了', '整懂了',
            '整透了', '搞明白了', '搞懂了', '搞透了'
        }
        
        dialogue_markers = {
            # 基础对话词
            '来', '一起', '让我们', '跟着', '教你', '告诉你', 
            # 邀请词组
            '带你', '陪你', '和你', '跟你', '请你', '邀请你',
            '一块儿', '一块', '一同', '共同', '大家', '咱们',
            # 引导词组
            '看看', '来看', '快看', '瞧瞧', '听听', '试试',
            '学习', '了解', '探索', '发现', '感受', '体验',
            # 分享词组
            '分享', '推荐', '介绍', '安利', '种草', '测评',
            '解说', '讲解', '教程', '攻略', '指南', '技巧',
            # 互动词组
            '互动', '交流', '讨论', '聊聊', '说说', '谈谈',
            '评论', '留言', '关注', '订阅', '点赞', '转发',
            # B站特色互动
            '三连', '一键三连', '点个三连', '求三连', '给个三连',
            '投币', '充电', '收藏', '关注', '催更', '别走',
            '别急', '慢慢看', '细细品', '仔细看', '往后看',
            # 2023-2024新增互动
            '速来', '速看', '速冲', '速进', '速食',
            '必看合集', '珍藏合集', '收藏合集', '经典合集',
            '建议收藏', '建议点赞', '建议三连', '建议关注',
            '记得一键三连', '记得关注', '记得收藏', '记得转发',
            '务必三连', '务必收藏', '务必关注', '务必转发',
            # 网络流行互动
            '整活', '搞起来', '安排上', '冲冲冲', '搞快点',
            '安排', '奥利给', '搞起', '整起来', '冲它',
            '搞这个', '整这个', '来这个', '整一个', '搞一个',
            # 口语化表达
            '咱整个', '咱搞个', '咱来个', '给你整个', '给你搞个',
            '跟你说个', '给你说个', '告诉你个', '说个事', '整点刺激的',
            '搞点刺激的', '来点刺激的', '整点意思', '搞点意思',
            # 新增口语化
            '给大家整个', '给大家搞个', '给大家来个',
            '给你们整个', '给你们搞个', '给你们来个',
            '速速来个', '速速整个', '速速搞个',
            # 亲切称呼
            '老铁', '兄弟', '姐妹', '小伙伴', '小可爱', '小宝贝',
            '宝', '亲', '朋友', '兄弟姐妹', '铁子', '老哥',
            '老姐', '老弟', '老妹', '小老弟', '小老妹',
            # 新增称呼
            '宝贝们', '亲们', '朋友们', '兄弟们', '姐妹们',
            '小伙伴们', '铁子们', '老铁们', '粉丝们', '观众们'
        }
        
        # 统计各种模式的出现
        pattern_stats = defaultdict(lambda: {'titles': [], 'keywords': Counter()})
        
        for title, processed_title in zip([t[0] for t in titles_data], processed_titles):
            words = processed_title.split()
            
            try:
                # 检测问句模式
                if any(marker in title for marker in question_markers):
                    pattern_stats['疑问式']['titles'].append(title)
                    pattern_stats['疑问式']['keywords'].update(words)
                
                # 检测感叹句模式
                if any(marker in title for marker in exclamation_markers):
                    pattern_stats['感叹式']['titles'].append(title)
                    pattern_stats['感叹式']['keywords'].update(words)
                
                # 检测对话式模式
                if any(marker in title for marker in dialogue_markers):
                    pattern_stats['对话式']['titles'].append(title)
                    pattern_stats['对话式']['keywords'].update(words)
            except Exception as e:
                print(f"Error processing title: {str(e)}")
                continue
        
        # 处理统计结果
        interaction_patterns = {}
        for pattern_name, stats in pattern_stats.items():
            if stats['titles']:  # 如果有匹配的标题
                try:
                    interaction_patterns[pattern_name] = {
                        'keywords': [word for word, _ in stats['keywords'].most_common(10)],
                        'sample_size': len(stats['titles'])
                    }
                except Exception as e:
                    print(f"Error processing pattern {pattern_name}: {str(e)}")
                    continue
        
        # 如果没有发现任何模式，返回默认模式
        if not interaction_patterns:
            interaction_patterns = {
                'default': {
                    'keywords': [],
                    'sample_size': 0,
                    'metrics': {
                        'coverage': 0,
                        'distinctiveness': 0,
                        'unique_matches': 0,
                        'shared_matches': 0
                    }
                }
            }
        
        return interaction_patterns
        
    except Exception as e:
        print(f"Error in interaction pattern discovery: {str(e)}")
        return {
            'default': {
                'keywords': [],
                'sample_size': 0,
                'metrics': {
                    'coverage': 0,
                    'distinctiveness': 0,
                    'unique_matches': 0,
                    'shared_matches': 0
                }
            }
        } 