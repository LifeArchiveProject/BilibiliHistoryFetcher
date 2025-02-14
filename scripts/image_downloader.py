import os
import sys

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import json
import time
import hashlib
import random
import threading
import sqlite3
from datetime import datetime
from queue import Queue, Empty
from typing import Optional, Dict, List
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scripts.utils import get_output_path, load_config

config = load_config()

class ImageDownloader:
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ImageDownloader, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self.session = self._create_session()
            self.download_status = self._load_download_status()
            self.download_queue = Queue()
            self.lock = threading.Lock()
            self.status_lock = threading.Lock()  # 专门用于状态更新的锁
            self.is_downloading = False  # 下载状态标志
            
            # 状态缓存
            self.stats_cache = {}
            self.stats_cache_time = 0
            self.stats_cache_ttl = 1  # 缓存有效期(秒)
            
            # 总下载数量跟踪
            self.total_covers_to_download = 0
            self.total_avatars_to_download = 0
            
            # 确保目录存在
            self.base_path = get_output_path('images')
            self.covers_path = os.path.join(self.base_path, 'covers')
            self.avatars_path = os.path.join(self.base_path, 'avatars')
            self.orphaned_covers_path = os.path.join(self.base_path, 'orphaned_covers')
            self.orphaned_avatars_path = os.path.join(self.base_path, 'orphaned_avatars')
            
            os.makedirs(self.covers_path, exist_ok=True)
            os.makedirs(self.avatars_path, exist_ok=True)
            os.makedirs(self.orphaned_covers_path, exist_ok=True)
            os.makedirs(self.orphaned_avatars_path, exist_ok=True)
            
            # 用于记录重复的URL
            self.avatar_url_map = {}
            self.cover_url_map = {}
            
            # 加载已存在的图片信息
            self._load_existing_images()
            
            print("初始化图片下载器完成")
            print(f"图片保存基础路径: {self.base_path}")
            print(f"封面保存路径: {self.covers_path}")
            print(f"头像保存路径: {self.avatars_path}")
            print(f"孤立封面保存路径: {self.orphaned_covers_path}")
            print(f"孤立头像保存路径: {self.orphaned_avatars_path}")
    
    def _create_session(self) -> requests.Session:
        """创建请求会话，配置重试策略和请求头"""
        session = requests.Session()
        
        # 配置重试策略
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 设置请求头
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.bilibili.com'
        })
        
        print("创建请求会话完成，已配置重试策略和请求头")
        return session
    
    def _load_download_status(self) -> Dict:
        """加载下载状态记录"""
        try:
            status_file = get_output_path('download_status.json')
            print(f"\n=== 加载下载状态 ===")
            print(f"状态文件路径: {status_file}")
            
            if os.path.exists(status_file):
                print(f"发现现有下载状态文件")
                file_size = os.path.getsize(status_file)
                print(f"文件大小: {file_size/1024:.2f}KB")
                
                with open(status_file, 'r', encoding='utf-8') as f:
                    status = json.load(f)
                    print(f"已加载下载状态:")
                    print(f"- 封面: {len(status['covers'])}个")
                    print(f"- 头像: {len(status['avatars'])}个")
                    return status
                    
            print("未找到下载状态文件，将创建新的状态记录")
            return {'covers': {}, 'avatars': {}}
            
        except Exception as e:
            print(f"\n加载状态文件时出错:")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            import traceback
            print("错误堆栈:")
            print(traceback.format_exc())
            return {'covers': {}, 'avatars': {}}
    
    def _save_download_status(self):
        """保存下载状态"""
        try:
            status_file = get_output_path('download_status.json')
            print(f"\n=== 保存下载状态 ===")
            print(f"状态文件路径: {status_file}")
            
            with self.status_lock:  # 使用status_lock而不是lock
                # 如果状态文件存在,先读取现有状态
                existing_status = {'covers': {}, 'avatars': {}}
                if os.path.exists(status_file):
                    try:
                        with open(status_file, 'r', encoding='utf-8') as f:
                            existing_status = json.load(f)
                    except Exception as e:
                        print(f"读取现有状态文件失败: {e}")
                
                # 合并状态
                merged_status = {
                    'covers': {**existing_status.get('covers', {}), **self.download_status['covers']},
                    'avatars': {**existing_status.get('avatars', {}), **self.download_status['avatars']}
                }
                
                print(f"当前状态内容:")
                print(f"- 封面数量: {len(merged_status['covers'])}")
                print(f"- 头像数量: {len(merged_status['avatars'])}")
                
                # 检查目录是否存在
                os.makedirs(os.path.dirname(status_file), exist_ok=True)
                
                # 保存合并后的状态
                with open(status_file, 'w', encoding='utf-8') as f:
                    json.dump(merged_status, f, ensure_ascii=False, indent=2)
                
                # 更新内存中的状态
                self.download_status = merged_status
                
                # 验证文件是否成功写入
                if os.path.exists(status_file):
                    file_size = os.path.getsize(status_file)
                    print(f"状态文件已保存，大小: {file_size/1024:.2f}KB")
                else:
                    print("警告：状态文件未成功创建")
                    
        except Exception as e:
            print(f"\n保存状态文件时出错:")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            import traceback
            print("错误堆栈:")
            print(traceback.format_exc())
    
    def _get_file_hash(self, url: str) -> str:
        """获取URL的哈希值作为文件名"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def _get_file_extension(self, url: str) -> str:
        """从URL中获取文件扩展名"""
        path = urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        
        # 如果URL中没有扩展名，从Content-Type中获取
        if not ext:
            try:
                response = self.session.head(url, timeout=5)
                content_type = response.headers.get('content-type', '')
                if 'gif' in content_type:
                    return '.gif'
                elif 'png' in content_type:
                    return '.png'
                elif 'jpeg' in content_type or 'jpg' in content_type:
                    return '.jpg'
                elif 'webp' in content_type:
                    return '.webp'
            except Exception as e:
                print(f"获取Content-Type失败: {str(e)}")
        
        return ext if ext else '.jpg'
    
    def _download_image(self, url: str, save_path: str) -> bool:
        """下载单个图片"""
        try:
            print(f"\n开始下载图片: {url}")
            print(f"保存路径: {save_path}")
            
            # 随机延迟
            delay = random.uniform(2, 5)
            print(f"随机延迟 {delay:.2f} 秒")
            time.sleep(delay)
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            # 检查是否是图片
            content_type = response.headers.get('content-type', '')
            print(f"响应Content-Type: {content_type}")
            
            if not content_type.startswith('image/'):
                print(f"警告：URL {url} 返回的不是图片（{content_type}）")
                return False
            
            # 特殊处理GIF图片
            if 'gif' in content_type.lower():
                print("检测到GIF图片，使用二进制模式保存")
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                if not save_path.lower().endswith('.gif'):
                    new_path = os.path.splitext(save_path)[0] + '.gif'
                    os.rename(save_path, new_path)
                    print(f"重命名文件为GIF格式: {new_path}")
                    return True
            
            # 保存其他类型的图片
            with open(save_path, 'wb') as f:
                f.write(response.content)
            
            file_size = os.path.getsize(save_path)
            print(f"图片下载成功，文件大小: {file_size/1024:.2f}KB")
            return True
            
        except Exception as e:
            print(f"下载图片失败 {url}")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            if isinstance(e, requests.exceptions.RequestException):
                print(f"请求异常详情: {e.response.status_code if e.response else '无响应'}")
            return False
    
    def _get_cover_path(self, url: str) -> str:
        """获取封面图片的保存路径，使用哈希值组织目录结构"""
        file_hash = self._get_file_hash(url)
        ext = self._get_file_extension(url)
        
        # 使用哈希的前两位作为子目录
        sub_dir = file_hash[:2]
        save_dir = os.path.join(self.covers_path, sub_dir)
        os.makedirs(save_dir, exist_ok=True)
        
        return os.path.join(save_dir, f"{file_hash}{ext}")
    
    def _get_avatar_path(self, url: str) -> str:
        """获取头像图片的保存路径"""
        file_hash = self._get_file_hash(url)
        ext = self._get_file_extension(url)
        
        # 使用哈希的前两位作为子目录
        sub_dir = file_hash[:2]
        save_dir = os.path.join(self.avatars_path, sub_dir)
        os.makedirs(save_dir, exist_ok=True)
        
        return os.path.join(save_dir, f"{file_hash}{ext}")
    
    def download_worker(self):
        """下载工作线程"""
        while True:
            try:
                # 使用超时获取任务,避免永久阻塞
                try:
                    task = self.download_queue.get(timeout=1)
                except Empty:
                    # 如果队列为空且下载已完成,退出线程
                    if not self.is_downloading:
                        break
                    continue
                
                if task is None:
                    break
                
                url, save_path, is_cover, key = task
                print(f"\n=== 处理下载任务 ===")
                print(f"URL: {url}")
                print(f"保存路径: {save_path}")
                print(f"类型: {'封面' if is_cover else '头像'}")
                
                try:
                    # 检查是否已下载
                    with self.status_lock:  # 使用专门的状态锁
                        status_dict = self.download_status.get('covers' if is_cover else 'avatars', {})
                        if key in status_dict and status_dict[key].get('downloaded'):
                            print(f"跳过已下载的图片: {url}")
                            self.download_queue.task_done()
                            continue
                    
                    # 确保目录存在
                    save_dir = os.path.dirname(save_path)
                    os.makedirs(save_dir, exist_ok=True)
                    
                    # 下载图片
                    print("开始下载图片...")
                    success = self._download_image(url, save_path)
                    print(f"下载结果: {'成功' if success else '失败'}")
                    
                    # 更新状态
                    print("更新下载状态...")
                    with self.status_lock:  # 使用专门的状态锁
                        # 确保字典存在
                        if 'covers' not in self.download_status:
                            self.download_status['covers'] = {}
                        if 'avatars' not in self.download_status:
                            self.download_status['avatars'] = {}
                            
                        status_dict = self.download_status['covers' if is_cover else 'avatars']
                        status_dict[key] = {
                            'url': url,
                            'path': save_path,
                            'downloaded': success,
                            'timestamp': int(time.time())
                        }
                        print(f"状态已更新: {status_dict[key]}")
                    
                        # 更新URL映射
                        if success:
                            if is_cover:
                                self.cover_url_map[key] = save_path
                                print(f"已更新封面URL映射")
                            else:
                                self.avatar_url_map[key] = save_path
                                print(f"已更新头像URL映射")
                    
                    # 定期保存状态
                    if random.random() < 0.1:  # 10%的概率保存状态
                        print("触发定期状态保存...")
                        self._save_download_status()
                
                except Exception as e:
                    print(f"\n处理下载任务时出错:")
                    print(f"URL: {url}")
                    print(f"错误类型: {type(e).__name__}")
                    print(f"错误信息: {str(e)}")
                    print("错误堆栈:")
                    import traceback
                    print(traceback.format_exc())
                    
                    # 记录错误状态
                    with self.status_lock:  # 使用专门的状态锁
                        # 确保字典存在
                        if 'covers' not in self.download_status:
                            self.download_status['covers'] = {}
                        if 'avatars' not in self.download_status:
                            self.download_status['avatars'] = {}
                            
                        status_dict = self.download_status['covers' if is_cover else 'avatars']
                        status_dict[key] = {
                            'url': url,
                            'path': save_path,
                            'downloaded': False,
                            'timestamp': int(time.time()),
                            'error': str(e)
                        }
                        print(f"已记录错误状态: {status_dict[key]}")
                
                finally:
                    # 无论成功与否，都标记任务完成
                    self.download_queue.task_done()
                    print("任务已标记为完成")
                
            except Exception as e:
                print(f"\n下载工作线程发生错误:")
                print(f"错误类型: {type(e).__name__}")
                print(f"错误信息: {str(e)}")
                print("错误堆栈:")
                import traceback
                print(traceback.format_exc())
    
    def _load_existing_images(self):
        """加载已存在的图片信息"""
        print("\n加载已存在的图片信息...")
        
        # 清空现有映射
        self.cover_url_map.clear()
        self.avatar_url_map.clear()
        
        # 加载封面图片
        for root, _, files in os.walk(self.covers_path):
            for file in files:
                if file.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                    file_path = os.path.join(root, file)
                    try:
                        file_hash = file.split('.')[0]  # 获取文件名（不含扩展名）
                        if os.path.getsize(file_path) > 0:  # 确保文件不是空的
                            self.cover_url_map[file_hash] = file_path
                        else:
                            print(f"警告：发现空文件：{file_path}")
                            try:
                                os.remove(file_path)
                                print(f"已删除空文件：{file_path}")
                            except Exception as e:
                                print(f"删除空文件失败：{str(e)}")
                    except Exception as e:
                        print(f"处理文件时出错：{file_path} - {str(e)}")
        print(f"已加载 {len(self.cover_url_map)} 个封面图片")
        
        # 加载头像图片
        for root, _, files in os.walk(self.avatars_path):
            for file in files:
                if file.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                    file_path = os.path.join(root, file)
                    try:
                        file_hash = file.split('.')[0]  # 获取文件名（不含扩展名）
                        if os.path.getsize(file_path) > 0:  # 确保文件不是空的
                            self.avatar_url_map[file_hash] = file_path
                        else:
                            print(f"警告：发现空文件：{file_path}")
                            try:
                                os.remove(file_path)
                                print(f"已删除空文件：{file_path}")
                            except Exception as e:
                                print(f"删除空文件失败：{str(e)}")
                    except Exception as e:
                        print(f"处理文件时出错：{file_path} - {str(e)}")
        print(f"已加载 {len(self.avatar_url_map)} 个头像图片")
        
        # 检查状态记录中的文件是否存在
        self._check_status_files()
    
    def _check_status_files(self):
        """检查状态记录中的文件是否存在"""
        # 检查封面状态
        missing_covers = []
        for key, value in self.download_status['covers'].items():
            if value.get('downloaded'):
                file_path = value['path']
                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    missing_covers.append((key, value))
        
        if missing_covers:
            print(f"\n发现 {len(missing_covers)} 个状态为已下载但文件不存在或为空的封面记录：")
            for key, value in missing_covers:
                print(f"URL: {value['url']}")
                print(f"路径: {value['path']}")
                print(f"时间戳: {datetime.fromtimestamp(value['timestamp'])}")
                print("---")
                value['downloaded'] = False
                value['error'] = 'File not found or empty'
        
        # 检查头像状态
        missing_avatars = []
        for key, value in self.download_status['avatars'].items():
            if value.get('downloaded'):
                file_path = value['path']
                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    missing_avatars.append((key, value))
        
        if missing_avatars:
            print(f"\n发现 {len(missing_avatars)} 个状态为已下载但文件不存在或为空的头像记录：")
            for key, value in missing_avatars:
                print(f"URL: {value['url']}")
                print(f"路径: {value['path']}")
                print(f"时间戳: {datetime.fromtimestamp(value['timestamp'])}")
                print("---")
                value['downloaded'] = False
                value['error'] = 'File not found or empty'
        
        # 如果有任何更新，保存状态
        if missing_covers or missing_avatars:
            self._save_download_status()
    
    def _filter_new_urls(self, urls: set, is_cover: bool) -> set:
        """过滤出需要下载的新URL
        
        Args:
            urls: URL集合
            is_cover: 是否是封面图片
            
        Returns:
            set: 需要下载的URL集合
        """
        url_map = self.cover_url_map if is_cover else self.avatar_url_map
        new_urls = set()
        
        for url in urls:
            # 跳过空URL
            if not url or not isinstance(url, str):
                continue
                
            # 确保URL是有效的
            if not url.startswith(('http://', 'https://')):
                continue
                
            url_hash = self._get_file_hash(url)
            if url_hash not in url_map:
                new_urls.add(url)
        
        return new_urls
    
    def _preprocess_year_data(self, year: int) -> tuple[set, set]:
        """预处理指定年份的数据，获取去重后的URL集合"""
        print(f"\n预处理 {year} 年数据...")
        cover_urls = set()
        avatar_urls = set()
        
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # 获取去重后的封面URL，区分普通视频和专栏
            cursor.execute(f"""
                SELECT DISTINCT 
                    CASE 
                        WHEN badge = '专栏' AND covers IS NOT NULL AND covers != '' 
                        THEN json_extract(covers, '$[0]')  -- 专栏使用covers数组的第一个元素
                        ELSE cover  -- 其他情况使用cover字段
                    END as cover_url,
                    author_face
                FROM bilibili_history_{year}
                WHERE (
                    (badge != '专栏' AND cover IS NOT NULL AND cover != '' AND (cover LIKE 'http://%' OR cover LIKE 'https://%'))
                    OR 
                    (badge = '专栏' AND covers IS NOT NULL AND covers != '' AND json_valid(covers))
                )
            """)
            
            for row in cursor.fetchall():
                cover_url, author_face = row
                
                # 处理封面URL
                if cover_url and isinstance(cover_url, str) and (cover_url.startswith('http://') or cover_url.startswith('https://')):
                    cover_urls.add(cover_url)
                
                # 处理头像URL
                if author_face and isinstance(author_face, str) and (author_face.startswith('http://') or author_face.startswith('https://')):
                    avatar_urls.add(author_face)
            
            print(f"找到 {len(cover_urls)} 个不重复的封面URL")
            print(f"找到 {len(avatar_urls)} 个不重复的头像URL")
            
            # 更新总下载数量
            with self.status_lock:
                self.total_covers_to_download += len(cover_urls)
                self.total_avatars_to_download += len(avatar_urls)
            
            return cover_urls, avatar_urls
            
        except Exception as e:
            print(f"预处理数据时出错: {str(e)}")
            print("错误详情:")
            import traceback
            print(traceback.format_exc())
            return set(), set()
        finally:
            if 'conn' in locals():
                conn.close()
    
    def start_download(self, year: Optional[int] = None):
        """开始下载指定年份的图片"""
        try:
            print(f"\n{'='*50}")
            print(f"开始下载图片 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"目标年份: {'所有年份' if year is None else year}")
            
            # 重置总下载数量
            with self.status_lock:
                self.total_covers_to_download = 0
                self.total_avatars_to_download = 0
            
            # 设置下载状态标志
            self.is_downloading = True
            
            # 获取要处理的年份列表
            if year:
                years = [year]
            else:
                years = get_available_years()
            
            if not years:
                print("错误：未找到任何可用年份")
                raise ValueError("未找到任何可用年份")
            
            print(f"将处理以下年份: {years}")
            
            # 创建下载线程池
            num_threads = 6
            print(f"创建 {num_threads} 个下载线程")
            threads = []
            for i in range(num_threads):
                t = threading.Thread(target=self.download_worker, name=f"DownloadWorker-{i+1}")
                t.daemon = True  # 设置为守护线程
                t.start()
                threads.append(t)
            
            # 处理每个年份的数据
            total_processed = 0
            for year in years:
                print(f"\n=== 处理 {year} 年数据 ===")
                # 预处理年份数据
                cover_urls, avatar_urls = self._preprocess_year_data(year)
                
                # 过滤出需要下载的新URL
                new_cover_urls = self._filter_new_urls(cover_urls, True)
                new_avatar_urls = self._filter_new_urls(avatar_urls, False)
                
                print(f"\n{year}年需要下载的图片:")
                print(f"封面: {len(new_cover_urls)}/{len(cover_urls)} 个")
                print(f"头像: {len(new_avatar_urls)}/{len(avatar_urls)} 个")
                
                # 添加下载任务
                for url in new_cover_urls:
                    save_path = self._get_cover_path(url)
                    self.cover_url_map[self._get_file_hash(url)] = save_path
                    self.download_queue.put((
                        url,
                        save_path,
                        True,
                        self._get_file_hash(url)
                    ))
                    print(f"添加封面下载任务: {url}")
                
                for url in new_avatar_urls:
                    save_path = self._get_avatar_path(url)
                    self.avatar_url_map[self._get_file_hash(url)] = save_path
                    self.download_queue.put((
                        url,
                        save_path,
                        False,
                        self._get_file_hash(url)
                    ))
                    print(f"添加头像下载任务: {url}")
                
                total_processed += len(new_cover_urls) + len(new_avatar_urls)
                
                # 等待队列处理完毕,但设置超时避免永久阻塞
                print("\n等待当前年份下载任务完成...")
                while not self.download_queue.empty():
                    try:
                        self.download_queue.join()
                    except Exception as e:
                        print(f"等待任务完成时出错: {str(e)}")
                        break
            
            print("\n所有数据处理完成，正在停止下载线程...")
            
            # 停止工作线程
            self.is_downloading = False
            for _ in threads:
                self.download_queue.put(None)
            
            # 等待线程结束,但设置超时
            for t in threads:
                t.join(timeout=5)
            
            print("\n=== 保存最终下载状态 ===")
            print("当前状态统计:")
            stats = self.get_download_stats()
            print(f"封面图片:")
            print(f"- 总数: {stats['covers']['total']}")
            print(f"- 需要下载: {stats['covers']['total_to_download']}")
            print(f"- 已下载: {stats['covers']['downloaded']}")
            print(f"- 失败: {stats['covers']['failed']}")
            print(f"\n头像图片:")
            print(f"- 总数: {stats['avatars']['total']}")
            print(f"- 需要下载: {stats['avatars']['total_to_download']}")
            print(f"- 已下载: {stats['avatars']['downloaded']}")
            print(f"- 失败: {stats['avatars']['failed']}")
            
            self._save_download_status()
            
            print(f"\n下载任务完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"总处理记录数: {total_processed}")
            print('='*50)
            
        except Exception as e:
            print("\n下载过程发生错误:")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            import traceback
            print("错误堆栈:")
            print(traceback.format_exc())
        finally:
            self.is_downloading = False
            if 'conn' in locals():
                conn.close()
                print("数据库连接已关闭")
    
    def get_download_stats(self) -> Dict:
        """获取下载统计信息"""
        current_time = time.time()
        status_file = get_output_path('download_status.json')
        
        # 如果缓存有效且状态文件存在,直接返回缓存的状态
        if (current_time - self.stats_cache_time < self.stats_cache_ttl and 
            os.path.exists(status_file)):
            return self.stats_cache
            
        # 获取当前正在下载的任务数量
        try:
            active_task_count = self.download_queue.qsize()
        except NotImplementedError:
            active_task_count = 0
            
        active_tasks = [{'status': 'pending', 'type': 'unknown'} for _ in range(active_task_count)]

        # 使用status_lock保护状态读取
        with self.status_lock:
            # 如果状态文件存在，尝试加载状态
            if os.path.exists(status_file):
                try:
                    with open(status_file, 'r', encoding='utf-8') as f:
                        file_status = json.load(f)
                        # 合并文件状态和内存状态
                        self.download_status = {
                            'covers': {**file_status.get('covers', {}), **self.download_status.get('covers', {})},
                            'avatars': {**file_status.get('avatars', {}), **self.download_status.get('avatars', {})}
                        }
                except Exception as e:
                    print(f"加载下载状态文件失败: {e}")
                    # 不重置状态,继续使用内存中的状态
            
            cover_stats = {
                'total': len(self.download_status.get('covers', {})),
                'total_to_download': self.total_covers_to_download,
                'downloaded': sum(1 for v in self.download_status.get('covers', {}).values() if v.get('downloaded')),
                'failed': sum(1 for v in self.download_status.get('covers', {}).values() if not v.get('downloaded')),
                'pending': active_task_count,
                'existing_files': len(self.cover_url_map),
                'last_download': max([v.get('timestamp', 0) for v in self.download_status.get('covers', {}).values() if v.get('downloaded')]) if any(v.get('downloaded') for v in self.download_status.get('covers', {}).values()) else 0,
                'failed_urls': [
                    {
                        'url': v['url'],
                        'path': v['path'],
                        'timestamp': v['timestamp'],
                        'error': v.get('error', 'Unknown error')
                    }
                    for v in self.download_status.get('covers', {}).values()
                    if not v.get('downloaded') and v.get('url') and v['url'] not in ('null', 'None', '')
                ],
                'orphaned_files': len(self.cover_url_map) - len(self.download_status.get('covers', {})),
                'orphaned_file_details': self.orphaned_files['covers'] if hasattr(self, 'orphaned_files') else []
            }
            
            avatar_stats = {
                'total': len(self.download_status.get('avatars', {})),
                'total_to_download': self.total_avatars_to_download,
                'downloaded': sum(1 for v in self.download_status.get('avatars', {}).values() if v.get('downloaded')),
                'failed': sum(1 for v in self.download_status.get('avatars', {}).values() if not v.get('downloaded')),
                'pending': active_task_count,
                'existing_files': len(self.avatar_url_map),
                'last_download': max([v.get('timestamp', 0) for v in self.download_status.get('avatars', {}).values() if v.get('downloaded')]) if any(v.get('downloaded') for v in self.download_status.get('avatars', {}).values()) else 0,
                'failed_urls': [
                    {
                        'url': v['url'],
                        'path': v['path'],
                        'timestamp': v['timestamp'],
                        'error': v.get('error', 'Unknown error')
                    }
                    for v in self.download_status.get('avatars', {}).values()
                    if not v.get('downloaded') and v.get('url') and v['url'] not in ('null', 'None', '')
                ],
                'orphaned_files': len(self.avatar_url_map) - len(self.download_status.get('avatars', {})),
                'orphaned_file_details': self.orphaned_files['avatars'] if hasattr(self, 'orphaned_files') else []
            }
            
            # 更新缓存
            self.stats_cache = {
                'covers': cover_stats,
                'avatars': avatar_stats,
                'active_tasks': active_tasks,
                'last_update': int(current_time),
                'is_downloading': active_task_count > 0
            }
            self.stats_cache_time = current_time
            
            return self.stats_cache
    
    def _clean_invalid_status(self):
        """清理无效的状态记录"""
        # 清理covers状态
        invalid_covers = []
        for key, value in self.download_status['covers'].items():
            if not value.get('url') or value['url'] in ('null', 'None', ''):
                invalid_covers.append(key)
            elif value.get('timestamp', 0) > int(time.time()):
                value['timestamp'] = int(time.time())
        
        for key in invalid_covers:
            del self.download_status['covers'][key]
        
        # 清理avatars状态
        invalid_avatars = []
        for key, value in self.download_status['avatars'].items():
            if not value.get('url') or value['url'] in ('null', 'None', ''):
                invalid_avatars.append(key)
            elif value.get('timestamp', 0) > int(time.time()):
                value['timestamp'] = int(time.time())
        
        for key in invalid_avatars:
            del self.download_status['avatars'][key]
        
        # 保存清理后的状态
        if invalid_covers or invalid_avatars:
            self._save_download_status()
    
    def _sync_status_with_files(self):
        """同步文件系统状态和下载状态"""
        # 同步封面状态
        for key, value in list(self.download_status['covers'].items()):
            if value.get('downloaded'):
                file_path = value['path']
                if not os.path.exists(file_path):
                    # 检查是否存在于其他路径
                    url_hash = self._get_file_hash(value['url'])
                    if url_hash in self.cover_url_map:
                        # 更新为新的路径
                        value['path'] = self.cover_url_map[url_hash]
                        print(f"更新封面路径: {file_path} -> {value['path']}")
                    else:
                        # 文件不存在，更新状态
                        value['downloaded'] = False
                        value['error'] = 'File not found on disk'
        
        # 同步头像状态
        for key, value in list(self.download_status['avatars'].items()):
            if value.get('downloaded'):
                file_path = value['path']
                if not os.path.exists(file_path):
                    # 检查是否存在于其他路径
                    url_hash = self._get_file_hash(value['url'])
                    if url_hash in self.avatar_url_map:
                        # 更新为新的路径
                        value['path'] = self.avatar_url_map[url_hash]
                        print(f"更新头像路径: {file_path} -> {value['path']}")
                    else:
                        # 文件不存在，更新状态
                        value['downloaded'] = False
                        value['error'] = 'File not found on disk'
        
        # 查找孤立文件
        self._find_orphaned_files()
        
        # 合并相同URL的状态记录
        self._merge_duplicate_status()
        
        # 保存更新后的状态
        self._save_download_status()
    
    def _find_orphaned_files(self):
        """查找孤立文件（存在于磁盘但没有对应状态记录的文件）"""
        # 查找孤立的封面文件
        cover_hashes = {self._get_file_hash(v['url']): v for v in self.download_status['covers'].values()}
        orphaned_covers = []
        for file_hash, file_path in self.cover_url_map.items():
            if file_hash not in cover_hashes:
                try:
                    file_size = os.path.getsize(file_path)
                    file_time = os.path.getmtime(file_path)
                    orphaned_covers.append({
                        'hash': file_hash,
                        'path': file_path,
                        'size': file_size,
                        'modified_time': int(file_time)
                    })
                except Exception as e:
                    print(f"获取孤立文件信息失败: {file_path} - {str(e)}")
        
        # 查找孤立的头像文件
        avatar_hashes = {self._get_file_hash(v['url']): v for v in self.download_status['avatars'].values()}
        orphaned_avatars = []
        for file_hash, file_path in self.avatar_url_map.items():
            if file_hash not in avatar_hashes:
                try:
                    file_size = os.path.getsize(file_path)
                    file_time = os.path.getmtime(file_path)
                    orphaned_avatars.append({
                        'hash': file_hash,
                        'path': file_path,
                        'size': file_size,
                        'modified_time': int(file_time)
                    })
                except Exception as e:
                    print(f"获取孤立文件信息失败: {file_path} - {str(e)}")
        
        # 保存孤立文件信息
        self.orphaned_files = {
            'covers': orphaned_covers,
            'avatars': orphaned_avatars
        }
        
        # 移动孤立文件到专门的文件夹
        self._move_orphaned_files()
    
    def _move_orphaned_files(self):
        """移动孤立文件到专门的文件夹"""
        # 移动孤立的封面文件
        if self.orphaned_files['covers']:
            print(f"\n开始移动 {len(self.orphaned_files['covers'])} 个孤立的封面文件...")
            for file_info in self.orphaned_files['covers']:
                try:
                    src_path = file_info['path']
                    if not os.path.exists(src_path):
                        print(f"源文件不存在，跳过: {src_path}")
                        continue
                        
                    # 获取文件名（包含扩展名）
                    filename = os.path.basename(src_path)
                    dst_path = os.path.join(self.orphaned_covers_path, filename)
                    
                    # 如果目标文件已存在，添加数字后缀
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dst_path):
                        dst_path = os.path.join(self.orphaned_covers_path, f"{base}_{counter}{ext}")
                        counter += 1
                    
                    # 移动文件
                    os.rename(src_path, dst_path)
                    print(f"已移动封面文件: {src_path} -> {dst_path}")
                    
                    # 更新文件信息中的路径
                    file_info['path'] = dst_path
                    
                except Exception as e:
                    print(f"移动封面文件失败: {src_path} - {str(e)}")
        
        # 移动孤立的头像文件
        if self.orphaned_files['avatars']:
            print(f"\n开始移动 {len(self.orphaned_files['avatars'])} 个孤立的头像文件...")
            for file_info in self.orphaned_files['avatars']:
                try:
                    src_path = file_info['path']
                    if not os.path.exists(src_path):
                        print(f"源文件不存在，跳过: {src_path}")
                        continue
                        
                    # 获取文件名（包含扩展名）
                    filename = os.path.basename(src_path)
                    dst_path = os.path.join(self.orphaned_avatars_path, filename)
                    
                    # 如果目标文件已存在，添加数字后缀
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dst_path):
                        dst_path = os.path.join(self.orphaned_avatars_path, f"{base}_{counter}{ext}")
                        counter += 1
                    
                    # 移动文件
                    os.rename(src_path, dst_path)
                    print(f"已移动头像文件: {src_path} -> {dst_path}")
                    
                    # 更新文件信息中的路径
                    file_info['path'] = dst_path
                    
                except Exception as e:
                    print(f"移动头像文件失败: {src_path} - {str(e)}")
        
        # 清理空文件夹
        self._cleanup_empty_dirs()
    
    def _cleanup_empty_dirs(self):
        """清理空文件夹"""
        def remove_empty_dirs(path):
            for root, dirs, files in os.walk(path, topdown=False):
                for dirname in dirs:
                    dir_path = os.path.join(root, dirname)
                    try:
                        if not os.listdir(dir_path):  # 检查目录是否为空
                            os.rmdir(dir_path)
                            print(f"已删除空文件夹: {dir_path}")
                    except Exception as e:
                        print(f"删除空文件夹失败: {dir_path} - {str(e)}")
        
        # 清理封面目录中的空文件夹
        remove_empty_dirs(self.covers_path)
        # 清理头像目录中的空文件夹
        remove_empty_dirs(self.avatars_path)
    
    def _merge_duplicate_status(self):
        """合并相同URL的状态记录"""
        # 合并封面状态
        url_to_status = {}
        for key, value in list(self.download_status['covers'].items()):
            url = value.get('url')
            if not url or url in ('null', 'None', ''):
                continue
                
            if url in url_to_status:
                # 如果已存在这个URL的记录
                existing = url_to_status[url]
                if value.get('downloaded') and not existing.get('downloaded'):
                    # 如果当前记录是成功的而现有记录是失败的，使用当前记录
                    url_to_status[url] = value
                elif value.get('timestamp', 0) > existing.get('timestamp', 0):
                    # 使用最新的记录
                    url_to_status[url] = value
                # 删除旧的状态记录
                del self.download_status['covers'][key]
            else:
                url_to_status[url] = value
        
        # 合并头像状态
        url_to_status = {}
        for key, value in list(self.download_status['avatars'].items()):
            url = value.get('url')
            if not url or url in ('null', 'None', ''):
                continue
                
            if url in url_to_status:
                # 如果已存在这个URL的记录
                existing = url_to_status[url]
                if value.get('downloaded') and not existing.get('downloaded'):
                    # 如果当前记录是成功的而现有记录是失败的，使用当前记录
                    url_to_status[url] = value
                elif value.get('timestamp', 0) > existing.get('timestamp', 0):
                    # 使用最新的记录
                    url_to_status[url] = value
                # 删除旧的状态记录
                del self.download_status['avatars'][key]
            else:
                url_to_status[url] = value

    def clear_all_images(self):
        """清空所有图片和下载状态"""
        try:
            print("\n开始清空所有图片和下载状态...")
            
            # 停止当前下载任务（如果有）
            self.is_downloading = False
            self.download_queue = Queue()
            
            # 清空状态文件
            status_file = get_output_path('download_status.json')
            if os.path.exists(status_file):
                try:
                    os.remove(status_file)
                    print(f"已删除下载状态文件: {status_file}")
                except Exception as e:
                    print(f"删除状态文件失败: {str(e)}")
            
            # 重置内存中的状态
            self.download_status = {'covers': {}, 'avatars': {}}
            self.stats_cache = None
            self.stats_cache_time = 0
            self.total_covers_to_download = 0
            self.total_avatars_to_download = 0
            
            # 清空URL映射
            self.cover_url_map.clear()
            self.avatar_url_map.clear()
            
            # 删除所有图片文件夹中的文件
            def remove_files_in_dir(directory):
                if os.path.exists(directory):
                    for root, dirs, files in os.walk(directory, topdown=False):
                        for name in files:
                            try:
                                file_path = os.path.join(root, name)
                                os.remove(file_path)
                                print(f"已删除文件: {file_path}")
                            except Exception as e:
                                print(f"删除文件失败: {file_path} - {str(e)}")
                        for name in dirs:
                            try:
                                dir_path = os.path.join(root, name)
                                os.rmdir(dir_path)
                                print(f"已删除空文件夹: {dir_path}")
                            except Exception as e:
                                print(f"删除文件夹失败: {dir_path} - {str(e)}")
            
            # 清空各个图片目录
            remove_files_in_dir(self.covers_path)
            remove_files_in_dir(self.avatars_path)
            remove_files_in_dir(self.orphaned_covers_path)
            remove_files_in_dir(self.orphaned_avatars_path)
            
            # 重新创建基础目录
            os.makedirs(self.covers_path, exist_ok=True)
            os.makedirs(self.avatars_path, exist_ok=True)
            os.makedirs(self.orphaned_covers_path, exist_ok=True)
            os.makedirs(self.orphaned_avatars_path, exist_ok=True)
            
            print("\n清空操作完成！")
            print(f"- 图片保存基础路径: {self.base_path}")
            print(f"- 封面保存路径: {self.covers_path}")
            print(f"- 头像保存路径: {self.avatars_path}")
            print(f"- 孤立封面保存路径: {self.orphaned_covers_path}")
            print(f"- 孤立头像保存路径: {self.orphaned_avatars_path}")
            
            return True
            
        except Exception as e:
            print(f"\n清空过程发生错误:")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            import traceback
            print("错误堆栈:")
            print(traceback.format_exc())
            return False

def get_db():
    """获取数据库连接"""
    db_path = get_output_path(config['db_file'])
    return sqlite3.connect(db_path)

def get_available_years() -> List[int]:
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
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    try:
        print("\n=== 开始图片下载任务 ===")
        print("初始化下载器...")
        downloader = ImageDownloader()
        
        print("\n下载2025年的图片...")
        downloader.start_download(2025)
        
        print("\n获取下载统计...")
        stats = downloader.get_download_stats()
        print("\n下载统计:")
        print(f"封面图片: 总数 {stats['covers']['total']}, "
              f"需要下载 {stats['covers']['total_to_download']}, "
              f"已下载 {stats['covers']['downloaded']}, "
              f"失败 {stats['covers']['failed']}")
        print(f"头像图片: 总数 {stats['avatars']['total']}, "
              f"需要下载 {stats['avatars']['total_to_download']}, "
              f"已下载 {stats['avatars']['downloaded']}, "
              f"失败 {stats['avatars']['failed']}") 
    except Exception as e:
        print("\n程序执行出错:")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        import traceback
        print("错误堆栈:")
        print(traceback.format_exc()) 