import asyncio
import hashlib
import os
from typing import Dict, Iterable, List, Set, Tuple, Any
from urllib.parse import urlparse

import aiohttp
import aiofiles


def _looks_like_image_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    if not url.startswith("http://") and not url.startswith("https://"):
        return False
    lower = url.lower()
    if any(ext in lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
        return True
    # 常见B站图片CDN路径包含 /bfs/，即便未带扩展名
    if "/bfs/" in lower:
        return True
    return False


def _walk_collect_urls(obj: Any, path: List[str], collector: Set[str]) -> None:
    """递归遍历对象并按上下文收集图片URL，排除标签、头像和表情相关图片"""
    # 路径关键字，用于排除
    path_lower = [p.lower() for p in path]

    def is_label_context() -> bool:
        return any(p == "label" for p in path_lower)

    def is_avatar_context() -> bool:
        return any(p in ("avatar", "face", "avatar_subscript_url") for p in path_lower)

    def is_decorate_card_context() -> bool:
        return any(p in ("decorate", "decorate_card", "decoration_card") for p in path_lower)

    def is_interaction_context() -> bool:
        return any(p == "module_interaction" for p in path_lower)

    def is_emoji_context() -> bool:
        """检查是否是表情上下文"""
        if isinstance(obj, dict):
            # 检查是否是表情节点
            if obj.get("type") == "RICH_TEXT_NODE_TYPE_EMOJI":
                return True
            # 检查是否在表情数据结构中
            if "emoji" in obj and isinstance(obj["emoji"], dict):
                emoji_data = obj["emoji"]
                if "icon_url" in emoji_data and "text" in emoji_data:
                    return True
        return False

    # 如果当前路径已经落在 label、avatar、表情相关区域，直接不收集其下任何URL
    if is_label_context() or is_avatar_context() or is_decorate_card_context() or is_interaction_context() or is_emoji_context():
        return

    if isinstance(obj, dict):
        for k, v in obj.items():
            # 对于已知的标签字段，跳过
            k_lower = str(k).lower()
            if k_lower in (
                "img_label_uri_hans",
                "img_label_uri_hans_static",
                "img_label_uri_hant",
                "img_label_uri_hant_static",
                "label_theme",
            ):
                continue

            _walk_collect_urls(v, path + [str(k)], collector)
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            _walk_collect_urls(v, path + [str(idx)], collector)
    elif isinstance(obj, str):
        s = obj
        if _looks_like_image_url(s):
            # 额外基于URL路径排除头像类
            low = s.lower()
            if "/bfs/face/" in low or "/face/" in low:
                return
            # 其它图片加入集合
            collector.add(s)


def collect_image_urls(dynamic_item: Dict) -> List[str]:
    """从动态条目中抽取图片类URL（包含视频封面），排除标签图片与头像图片"""
    urls: Set[str] = set()
    _walk_collect_urls(dynamic_item, [], urls)
    return list(urls)


def collect_live_media_urls(dynamic_item: Dict) -> List[Tuple[str, str]]:
    """从动态条目中抽取实况媒体URL，返回(image_url, video_url)的元组列表"""
    live_media: List[Tuple[str, str]] = []
    
    def _extract_live_media(obj: Any, path: List[str]) -> None:
        if isinstance(obj, dict):
            # 检查是否包含live_url字段
            if "live_url" in obj and "url" in obj:
                image_url = obj.get("url")
                live_url = obj.get("live_url")
                if image_url and live_url and live_url != "null":
                    live_media.append((image_url, live_url))
            
            for k, v in obj.items():
                _extract_live_media(v, path + [str(k)])
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _extract_live_media(item, path + [str(i)])
    
    _extract_live_media(dynamic_item, [])
    return live_media


def collect_emoji_urls(dynamic_item: Dict) -> List[Tuple[str, str]]:
    """从动态条目中抽取表情URL，返回(emoji_url, emoji_text)的元组列表"""
    emoji_list: List[Tuple[str, str]] = []
    
    def _extract_emojis(obj: Any, path: List[str]) -> None:
        if isinstance(obj, dict):
            # 检查是否是表情节点
            if (obj.get("type") == "RICH_TEXT_NODE_TYPE_EMOJI" and 
                "emoji" in obj and isinstance(obj["emoji"], dict)):
                emoji_data = obj["emoji"]
                icon_url = emoji_data.get("icon_url")
                text = emoji_data.get("text", "")
                if icon_url and text:
                    # 去掉文本中的方括号
                    clean_text = text.strip("[]")
                    if clean_text:
                        emoji_list.append((icon_url, clean_text))
            
            for k, v in obj.items():
                _extract_emojis(v, path + [str(k)])
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _extract_emojis(item, path + [str(i)])
    
    _extract_emojis(dynamic_item, [])
    return emoji_list


def _guess_extension(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    ext = (ext or "").lower()
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        return ext
    return ".jpg"


def _hash_name(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def predict_image_path(url: str, save_dir: str) -> str:
    """基于链接原始文件名预测保存路径（不依赖下载结果）"""
    os.makedirs(save_dir, exist_ok=True)
    path = urlparse(url).path
    base = os.path.basename(path)
    if not base:
        base = _hash_name(url) + _guess_extension(url)
    # 确保有扩展名
    root, ext = os.path.splitext(base)
    if not ext:
        base = f"{base}{_guess_extension(url)}"
    return os.path.join(save_dir, base)


async def _download_one(session: aiohttp.ClientSession, url: str, save_dir: str) -> Tuple[str, str, bool]:
    os.makedirs(save_dir, exist_ok=True)
    save_path = predict_image_path(url, save_dir)

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return url, save_path, False
            content_type = resp.headers.get("content-type", "").lower()
            if "image" not in content_type:
                return url, save_path, False
            data = await resp.read()
            async with aiofiles.open(save_path, "wb") as f:
                await f.write(data)
            return url, save_path, True
    except Exception:
        return url, save_path, False


async def download_images(urls: Iterable[str], save_dir: str, concurrency: int = 6) -> List[Tuple[str, str, bool]]:
    unique_urls = list(dict.fromkeys(urls))
    if not unique_urls:
        return []

    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession(headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/'
    }) as session:
        async def bound(u: str):
            async with sem:
                return await _download_one(session, u, save_dir)

        tasks = [bound(u) for u in unique_urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


async def _download_live_media(session: aiohttp.ClientSession, image_url: str, video_url: str, save_dir: str) -> Tuple[str, str, str, str, bool]:
    """下载实况媒体(图片和视频)，返回(image_url, video_url, image_path, video_path, success)"""
    os.makedirs(save_dir, exist_ok=True)
    
    # 生成文件名
    image_name = _hash_name(image_url) + _guess_extension(image_url)
    video_name = _hash_name(video_url) + ".mp4"  # live视频通常是mp4格式
    
    image_path = os.path.join(save_dir, image_name)
    video_path = os.path.join(save_dir, video_name)
    
    try:
        # 下载图片
        image_success = False
        if not os.path.exists(image_path):
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(image_path, "wb") as f:
                        await f.write(data)
                    image_success = True
        else:
            image_success = True
            
        # 下载视频
        video_success = False
        if not os.path.exists(video_path):
            async with session.get(video_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(video_path, "wb") as f:
                        await f.write(data)
                    video_success = True
        else:
            video_success = True
            
        return image_url, video_url, image_path, video_path, (image_success and video_success)
    except Exception:
        return image_url, video_url, image_path, video_path, False


async def download_live_media(live_media_pairs: List[Tuple[str, str]], save_dir: str, concurrency: int = 3) -> List[Tuple[str, str, str, str, bool]]:
    """下载实况媒体列表，返回下载结果"""
    if not live_media_pairs:
        return []
        
    sem = asyncio.Semaphore(concurrency)
    
    async with aiohttp.ClientSession(headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/'
    }) as session:
        async def bound(pair: Tuple[str, str]):
            async with sem:
                image_url, video_url = pair
                return await _download_live_media(session, image_url, video_url, save_dir)
                
        tasks = [bound(pair) for pair in live_media_pairs]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


async def _download_emoji(session: aiohttp.ClientSession, emoji_url: str, emoji_text: str, save_dir: str) -> Tuple[str, str, bool]:
    """下载单个表情，返回(emoji_url, emoji_path, success)"""
    os.makedirs(save_dir, exist_ok=True)
    
    # 使用表情文本作为文件名，并添加.png扩展名
    # 清理文件名中的非法字符
    import re
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', emoji_text)
    emoji_name = f"{safe_name}.png"
    emoji_path = os.path.join(save_dir, emoji_name)
    
    try:
        if not os.path.exists(emoji_path):
            async with session.get(emoji_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(emoji_path, "wb") as f:
                        await f.write(data)
                    return emoji_url, emoji_path, True
        else:
            return emoji_url, emoji_path, True
    except Exception:
        pass
    
    return emoji_url, emoji_path, False


async def download_emojis(emoji_pairs: List[Tuple[str, str]], save_dir: str, concurrency: int = 6) -> List[Tuple[str, str, bool]]:
    """下载表情列表，返回下载结果"""
    if not emoji_pairs:
        return []
        
    sem = asyncio.Semaphore(concurrency)
    
    async with aiohttp.ClientSession(headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/'
    }) as session:
        async def bound(pair: Tuple[str, str]):
            async with sem:
                emoji_url, emoji_text = pair
                return await _download_emoji(session, emoji_url, emoji_text, save_dir)
                
        tasks = [bound(pair) for pair in emoji_pairs]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


