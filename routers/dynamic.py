import os
import shutil
import asyncio
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from loguru import logger
import aiohttp
import aiofiles

from scripts.utils import load_config, setup_logger, get_output_path
from scripts.dynamic_db import (
    get_connection,
    save_normalized_dynamic_item,
    list_hosts_with_stats,
    list_dynamics_for_host,
    dynamic_core_exists,
    purge_host,
)
from scripts.dynamic_media import collect_image_urls, download_images, predict_image_path, collect_live_media_urls, download_live_media, collect_emoji_urls, download_emojis
from scripts.wbi_sign import get_wbi_sign

# 确保日志系统已初始化
setup_logger()

router = APIRouter()

# 任务管理：按 host_mid 管理抓取任务、停止信号与进度
_tasks = {}
_stop_events = {}
_progress = {}

def _get_or_create_event(host_mid: int) -> asyncio.Event:
    if host_mid not in _stop_events:
        _stop_events[host_mid] = asyncio.Event()
    return _stop_events[host_mid]

def _clear_event(host_mid: int) -> None:
    """清除停止事件"""
    if host_mid in _stop_events:
        try:
            _stop_events[host_mid].clear()
            logger.info(f"[DEBUG] 已清除停止事件 host_mid={host_mid}")
        except Exception as e:
            logger.warning(f"[DEBUG] 清除停止事件失败: {e}")
    else:
        logger.info(f"[DEBUG] 停止事件不存在于缓存中 host_mid={host_mid}")

def _set_progress(host_mid: int, page: int, total_items: int, last_offset: str, message: str) -> None:
    _progress[host_mid] = {
        "page": page,
        "total_items": total_items,
        "last_offset": last_offset or "",
        "message": message,
    }

def _get_progress(host_mid: int) -> Dict[str, Any]:
    return _progress.get(host_mid, {"page": 0, "total_items": 0, "last_offset": "", "message": "空闲状态，未开始抓取"})


@router.get("/space/auto/{host_mid}/progress", summary="SSE 实时获取自动抓取进度")
async def auto_fetch_progress(host_mid: int):
    """
    以 SSE 流方式每秒推送一次当前抓取进度。
    数据格式为 text/event-stream，data 为 JSON 字符串。
    """
    async def event_generator():
        while True:
            progress = _get_progress(host_mid)
            # 构造 SSE 包
            import json
            payload = json.dumps({
                "host_mid": host_mid,
                "page": progress.get("page", 0),
                "total_items": progress.get("total_items", 0),
                "last_offset": progress.get("last_offset", ""),
                "message": progress.get("message", "idle"),
            }, ensure_ascii=False)
            yield f"event: progress\ndata: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/space/auto/{host_mid}/stop", summary="停止当前自动抓取（页级停止）")
async def stop_auto_fetch(host_mid: int):
    """
    发送停止信号，当前页完成后停止抓取，并记录 offset 以便下次继续。
    注意：下次开始抓取时会自动清除停止信号。
    """
    ev = _get_or_create_event(host_mid)
    ev.set()
    logger.info(f"[DEBUG] 发送停止信号 host_mid={host_mid}, 事件状态: is_set={ev.is_set()}")
    return {"status": "ok", "message": "stop signal sent", "event_is_set": ev.is_set()}


@router.get("/db/hosts", summary="列出数据库中已有动态的UP列表")
async def list_db_hosts(
    limit: int = Query(50, ge=1, le=200, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    try:
        conn = get_connection()
    except Exception as e:
        logger.error(f"打开动态数据库失败: {e}")
        raise HTTPException(status_code=500, detail=f"打开动态数据库失败: {str(e)}")
    try:
        data = list_hosts_with_stats(conn, limit=limit, offset=offset)

        # 基础输出根目录（用于拼接相对路径）
        base_output_dir = os.path.dirname(get_output_path("__base__"))

        # 为每个 host_mid 增补 up_name 与 face_path（若存在则返回相对路径）
        cursor = conn.cursor()
        for rec in data:
            host_mid = rec.get("host_mid")
            up_name = None
            face_rel = None
            try:
                # 查询最近一条记录的作者名
                row = cursor.execute(
                    """
                    SELECT author_name
                    FROM dynamic_core
                    WHERE host_mid = ? AND author_name IS NOT NULL AND author_name <> ''
                    ORDER BY (publish_ts IS NULL) ASC, publish_ts DESC, fetch_time DESC
                    LIMIT 1
                    """,
                    (str(host_mid),),
                ).fetchone()
                if row and row[0]:
                    up_name = row[0]
            except Exception as e:
                logger.warning(f"查询作者名失败（忽略） host_mid={host_mid}: {e}")

            # 头像：output/dynamic/{mid}/face.*
            try:
                host_dir = os.path.dirname(get_output_path("dynamic", str(host_mid), "__host_meta.json"))
                if os.path.isdir(host_dir):
                    for name in os.listdir(host_dir):
                        if os.path.isfile(os.path.join(host_dir, name)) and name.lower().startswith("face."):
                            face_rel = os.path.relpath(os.path.join(host_dir, name), base_output_dir)
                            break
            except Exception as e:
                logger.warning(f"定位头像失败（忽略） host_mid={host_mid}: {e}")

        	# 写回扩展字段
            rec["up_name"] = up_name
            rec["face_path"] = face_rel

        return {"data": data, "limit": limit, "offset": offset}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/db/space/{host_mid}", summary="列出指定UP的动态（来自数据库）")
async def list_db_space(
    host_mid: int,
    limit: int = Query(20, ge=1, le=200, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    try:
        conn = get_connection()
    except Exception as e:
        logger.error(f"打开动态数据库失败: {e}")
        raise HTTPException(status_code=500, detail=f"打开动态数据库失败: {str(e)}")
    try:
        result = list_dynamics_for_host(conn, host_mid=host_mid, limit=limit, offset=offset)

        # 将 media_locals 和 live_media_locals 从逗号分隔字符串转换为数组，便于前端使用
        try:
            items = result.get("items", []) if isinstance(result, dict) else []
            for item in items:
                # 处理普通媒体
                ml = item.get("media_locals")
                if isinstance(ml, str):
                    ml_str = ml.strip()
                    if ml_str:
                        item["media_locals"] = [p for p in (s.strip() for s in ml_str.split(",")) if p]
                    else:
                        item["media_locals"] = []
                elif ml is None:
                    item["media_locals"] = []
                
                # 处理实况媒体
                lml = item.get("live_media_locals")
                if isinstance(lml, str):
                    lml_str = lml.strip()
                    if lml_str:
                        item["live_media_locals"] = [p for p in (s.strip() for s in lml_str.split(",")) if p]
                    else:
                        item["live_media_locals"] = []
                elif lml is None:
                    item["live_media_locals"] = []
        except Exception as e:
            logger.warning(f"媒体路径转换失败（忽略） host_mid={host_mid}: {e}")

        return {"host_mid": str(host_mid), **result, "limit": limit, "offset": offset}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_headers() -> Dict[str, str]:
    """获取请求头（包含完整的浏览器模拟 Headers 以避免 412 风控）"""
    config = load_config()
    sessdata = config.get("SESSDATA", "")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    cookie_parts = []
    if sessdata:
        cookie_parts.append(f'SESSDATA={sessdata}')
    bili_jct = config.get("bili_jct", "")
    if bili_jct:
        cookie_parts.append(f'bili_jct={bili_jct}')
    dede_user_id = config.get("DedeUserID", "")
    if dede_user_id:
        cookie_parts.append(f'DedeUserID={dede_user_id}')
    dede_ck = config.get("DedeUserID__ckMd5", "")
    if dede_ck:
        cookie_parts.append(f'DedeUserID__ckMd5={dede_ck}')
    buvid3 = config.get("buvid3", "")
    if buvid3:
        cookie_parts.append(f'buvid3={buvid3}')

    if cookie_parts:
        headers['Cookie'] = '; '.join(cookie_parts)

    return headers


async def fetch_dynamic_data(api_url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """获取动态数据的通用函数"""
    headers = get_headers()
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, headers=headers, params=params) as response:
                if response.status == 200:
                    # 内容类型保护：仅当返回为 JSON 时才解析为 JSON
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" in content_type or "text/json" in content_type or "application/vnd" in content_type:
                        data = await response.json()
                    else:
                        # 非JSON返回，读取少量文本用于错误提示（不抛出二次异常）
                        try:
                            snippet = (await response.text())[:256]
                        except Exception:
                            snippet = "<non-text response>"
                        logger.error(f"请求返回非JSON，Content-Type={content_type} url={api_url} params={params} snippet={snippet}")
                        raise HTTPException(status_code=500, detail="非JSON响应，无法解析")
                    logger.info(f"成功获取动态数据，状态码: {response.status}")
                    return data
                else:
                    try:
                        error_text = (await response.text())[:512]
                    except Exception:
                        error_text = ""
                    logger.error(f"请求失败，状态码: {response.status} url={api_url} params={params} body={error_text}")
                    raise HTTPException(status_code=response.status, detail=f"请求失败: {response.status}")
        except aiohttp.ClientError as e:
            logger.error(f"网络请求错误: {e}")
            raise HTTPException(status_code=500, detail=f"网络请求错误: {str(e)}")


@router.get("/space/auto/{host_mid}", summary="自动从前到后抓取直至完成")
async def auto_fetch_all(
    host_mid: int,
    need_top: bool = Query(False, description="是否需要置顶动态"),
    save_to_db: bool = Query(True, description="是否保存到数据库"),
    save_media: bool = Query(True, description="是否保存图片等多媒体"),
):
    """
    自动连续抓取用户空间动态：
    - 从上次记录的offset继续；若存在 fully_fetched=true 则从头开始
    - 每页3-5秒随机延迟
    - 当 offset 为空时终止，写 fully_fetched=true
    - 若从头开始抓取遇到连续10条已存在的动态ID则停止，并不保存这10条
    """
    import json, time, random

    api_url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
    base_params = {
        "host_mid": host_mid,
        "need_top": 1 if need_top else 0,
        "features": "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,forwardListHidden,decorationCard,commentsNewVersion,onlyfansAssetsV2,ugcDelete,onlyfansQaCard",
        "timezone_offset": -480,
        "platform": "web",
        "web_location": "333.1387",
    }

    # 读取 host 元数据
    host_dir = os.path.dirname(get_output_path("dynamic", str(host_mid), "__host_meta.json"))
    os.makedirs(host_dir, exist_ok=True)
    meta_path = os.path.join(host_dir, "__host_meta.json")
    meta = {"host_mid": str(host_mid), "last_fetch_time": 0, "last_offset": {"offset": "", "update_baseline": "", "update_num": 0}, "fully_fetched": False}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as rf:
                old = json.load(rf)
            if isinstance(old, dict):
                meta.update(old)
        except Exception:
            pass

    # 确定起点
    start_from_head = bool(meta.get("fully_fetched", False))
    next_offset = None if start_from_head else (meta.get("last_offset", {}) or {}).get("offset") or None
    
    # 调试信息：打印offset使用情况
    logger.info(f"[DEBUG] 抓取开始 host_mid={host_mid}")
    logger.info(f"[DEBUG] 元数据内容: {meta}")
    logger.info(f"[DEBUG] fully_fetched={meta.get('fully_fetched')}, start_from_head={start_from_head}")
    logger.info(f"[DEBUG] last_offset对象: {meta.get('last_offset', {})}")
    logger.info(f"[DEBUG] 将使用的next_offset: {next_offset}")
    if start_from_head:
        logger.info(f"[DEBUG] 模式: 从头开始抓取 (因为fully_fetched=True)")
    elif next_offset:
        logger.info(f"[DEBUG] 模式: 从offset继续抓取 (offset={next_offset})")
    else:
        logger.info(f"[DEBUG] 模式: 从头开始抓取 (无有效offset)")

    # DB 连接
    if save_to_db:
        try:
            conn = get_connection()
        except Exception as e:
            logger.error(f"打开动态数据库失败: {e}")
            raise HTTPException(status_code=500, detail=f"打开动态数据库失败: {str(e)}")
    else:
        conn = None

    all_items = []
    consecutive_duplicates = 0

    # 页计数
    current_page = 0
    
    # 自动重置停止信号：每次开始抓取前都清除之前的停止状态
    logger.info(f"[DEBUG] 自动重置停止信号 host_mid={host_mid}")
    _clear_event(host_mid)  # 确保清除任何遗留的停止信号
    stop_event = _get_or_create_event(host_mid)  # 创建新的事件对象
    
    # 验证重置结果
    logger.info(f"[DEBUG] 重置后停止事件状态: is_set={stop_event.is_set()}")
    
    _set_progress(host_mid, current_page, 0, next_offset or "", "准备开始抓取动态")

    try:
        while True:
            # 调试信息：打印每页请求的参数
            logger.info(f"[DEBUG] === 第 {current_page + 1} 页请求 ===")
            logger.info(f"[DEBUG] 当前next_offset: {next_offset}")

            # 基础参数 + 当页 offset
            params = dict(base_params)
            if next_offset:
                params["offset"] = next_offset
                logger.info(f"[DEBUG] 设置offset参数: {next_offset}")
            else:
                logger.info(f"[DEBUG] 本次请求不带offset（从头开始或已到底）")

            # 为参数添加 WBI 签名
            signed_params = get_wbi_sign(params)
            logger.info(f"[DEBUG] 最终请求参数（已签名）: {signed_params}")

            # 更新进度：准备抓取下一页
            if current_page > 0:
                _set_progress(host_mid, current_page, len(all_items), next_offset or "", f"准备抓取第 {current_page + 1} 页...")
            
            # 随机延迟3-5秒
            await asyncio.sleep(random.uniform(3, 5))

            data = await fetch_dynamic_data(api_url, signed_params)
            
            # 调试信息：打印API响应中的offset信息
            logger.info(f"[DEBUG] API响应结构检查:")
            logger.info(f"[DEBUG] - response.code: {data.get('code')}")
            logger.info(f"[DEBUG] - response.data存在: {bool(data.get('data'))}")
            
            # 兼容B站原始结构：从data.data中获取items和offset
            data_section = data.get("data", {}) if isinstance(data, dict) else {}
            items = data_section.get("items", []) if isinstance(data_section, dict) else []
            # offset 既可能是字符串，也可能在对象中
            off = data_section.get("offset") if isinstance(data_section, dict) else None
            
            logger.info(f"[DEBUG] - data_section.offset原始值: {off} (类型: {type(off)})")
            
            if isinstance(off, dict):
                next_offset = off.get("offset")
                logger.info(f"[DEBUG] - 从offset对象提取: {next_offset}")
            else:
                next_offset = off
                logger.info(f"[DEBUG] - 直接使用offset: {next_offset}")
            
            logger.info(f"[DEBUG] - 本页获取items数量: {len(items)}")
            logger.info(f"[DEBUG] - 下一页的offset: {next_offset}")

            # 若从头开始，并且出现连续10条都已存在，则停止
            if start_from_head and conn is not None:
                for item in items:
                    id_str = item.get("id_str") or item.get("basic", {}).get("id_str") or str(item.get("id"))
                    if id_str and dynamic_core_exists(conn, host_mid, str(id_str)):
                        consecutive_duplicates += 1
                        if consecutive_duplicates >= 10:
                            next_offset = None  # 触发终止
                            items = []  # 不保存这10条
                            break
                    else:
                        consecutive_duplicates = 0

            all_items.extend(items)
            current_page += 1
            _set_progress(host_mid, current_page, len(all_items), next_offset or "", f"第 {current_page} 页抓取完成，本页获取 {len(items)} 条动态，累计 {len(all_items)} 条")

            # 保存页面数据（去掉item.json保存，只有包含多媒体文件时才创建文件夹）
            if save_to_db and items:
                base_output_dir = os.path.dirname(get_output_path("__base__"))
                
                # 头像保存：仅保存一次到 output/dynamic/{host_mid}/face.(ext)
                try:
                    # 尝试从items提取用户头像
                    face_url = None
                    for item in items:
                        modules_raw = item.get("modules")
                        if isinstance(modules_raw, dict):
                            face_url = modules_raw.get("module_author", {}).get("face")
                        elif isinstance(modules_raw, list):
                            for mod in modules_raw:
                                if isinstance(mod, dict) and mod.get("module_type") == "MODULE_TYPE_AUTHOR":
                                    face_url = mod.get("module_author", {}).get("user", {}).get("face") or mod.get("module_author", {}).get("face")
                                    if face_url:
                                        break
                        if not face_url:
                            face_url = item.get("user", {}).get("face")
                        if face_url:
                            break

                    if face_url:
                        # 若已存在头像文件则跳过
                        host_dir = os.path.dirname(get_output_path("dynamic", str(host_mid), "__host_meta.json"))
                        os.makedirs(host_dir, exist_ok=True)

                        # 检查是否已有任何文件以 face.* 命名
                        exists = any(
                            name.lower().startswith("face.")
                            for name in os.listdir(host_dir)
                            if os.path.isfile(os.path.join(host_dir, name))
                        )
                        if not exists:
                            # 下载头像一次
                            results = await download_images([face_url], host_dir)
                            # 将下载的哈希文件重命名为 face.扩展名
                            for url, local_path, ok in results:
                                if ok:
                                    _, ext = os.path.splitext(local_path)
                                    new_path = os.path.join(host_dir, f"face{ext}")
                                    try:
                                        if os.path.exists(new_path):
                                            os.remove(new_path)
                                    except Exception:
                                        pass
                                    try:
                                        os.replace(local_path, new_path)
                                    except Exception:
                                        pass
                                    break
                except Exception as e:
                    logger.warning(f"保存头像失败（忽略）：{e}")
                
                for item in items:
                    try:
                        id_str = (
                            item.get("id_str")
                            or item.get("basic", {}).get("id_str")
                            or str(item.get("id"))
                        )
                        if not id_str:
                            continue

                        # 检查是否有多媒体文件需要下载
                        has_media = False
                        predicted_locals = []
                        live_predicted_locals = []
                        if save_media:
                            # 处理普通图片
                            image_urls = collect_image_urls(item)
                            if image_urls:
                                has_media = True
                                # 只有当包含多媒体文件时才创建文件夹
                                item_dir = os.path.dirname(
                                    get_output_path("dynamic", str(host_mid), str(id_str), "media")
                                )
                                os.makedirs(item_dir, exist_ok=True)
                                
                                # 预测本地路径
                                for u in image_urls:
                                    predicted_locals.append(os.path.relpath(predict_image_path(u, item_dir), base_output_dir))
                                
                                results = await download_images(image_urls, item_dir)
                                media_records = []
                                for media_url, local_path, ok in results:
                                    if ok:
                                        rel_path = os.path.relpath(local_path, base_output_dir)
                                        media_records.append((media_url, rel_path, "image"))
                            
                            # 处理实况媒体（live图片+视频）
                            live_media_pairs = collect_live_media_urls(item)
                            if live_media_pairs:
                                has_media = True
                                # 创建文件夹（如果还未创建）
                                if not image_urls:
                                    item_dir = os.path.dirname(
                                        get_output_path("dynamic", str(host_mid), str(id_str), "media")
                                    )
                                    os.makedirs(item_dir, exist_ok=True)
                                
                                live_results = await download_live_media(live_media_pairs, item_dir)
                                for image_url, video_url, image_path, video_path, ok in live_results:
                                    if ok:
                                        # 将实况媒体路径分别记录
                                        image_rel = os.path.relpath(image_path, base_output_dir)
                                        video_rel = os.path.relpath(video_path, base_output_dir)
                                        live_predicted_locals.extend([image_rel, video_rel])
                            
                            # 处理表情
                            emoji_pairs = collect_emoji_urls(item)
                            if emoji_pairs:
                                has_media = True
                                # 创建文件夹（如果还未创建）
                                if not image_urls and not live_media_pairs:
                                    item_dir = os.path.dirname(
                                        get_output_path("dynamic", str(host_mid), str(id_str), "media")
                                    )
                                    os.makedirs(item_dir, exist_ok=True)
                                
                                emoji_results = await download_emojis(emoji_pairs, item_dir)
                                for emoji_url, emoji_path, ok in emoji_results:
                                    if ok:
                                        # 将表情路径记录到普通媒体中
                                        emoji_rel = os.path.relpath(emoji_path, base_output_dir)
                                        predicted_locals.append(emoji_rel)

                        # 规范化保存到数据库
                        logger.info(f"normalize.core.call begin host_mid={host_mid} id_str={id_str}")
                        try:
                            save_normalized_dynamic_item(conn, host_mid, item)
                            logger.info(f"normalize.core.call done host_mid={host_mid} id_str={id_str}")
                            # 回写本地路径逗号串（只有当有多媒体文件时）
                            if predicted_locals or live_predicted_locals:
                                cursor = conn.cursor()
                                cursor.execute(
                                    """
                                    UPDATE dynamic_core SET
                                        media_locals = CASE
                                            WHEN media_locals IS NULL OR media_locals = '' THEN ?
                                            ELSE media_locals
                                        END,
                                        live_media_locals = CASE
                                            WHEN live_media_locals IS NULL OR live_media_locals = '' THEN ?
                                            ELSE live_media_locals
                                        END,
                                        live_media_count = ?
                                    WHERE host_mid = ? AND id_str = ?
                                    """,
                                    (
                                        ",".join(predicted_locals) if predicted_locals else "",
                                        ",".join(live_predicted_locals) if live_predicted_locals else "",
                                        len(live_predicted_locals),
                                        str(host_mid),
                                        str(id_str),
                                    ),
                                )
                                conn.commit()
                        except Exception as norm_err:
                            logger.warning(f"规范化保存失败（忽略）: {norm_err}")
                    except Exception as perr:
                        logger.warning(f"保存页面数据失败: {perr}")

            # 更新 meta
            meta["last_fetch_time"] = int(time.time())
            meta["last_offset"] = {"offset": next_offset or "", "update_baseline": "", "update_num": 0}
            meta["fully_fetched"] = not bool(next_offset)
            
            # 调试信息：保存状态
            logger.info(f"[DEBUG] 保存元数据:")
            logger.info(f"[DEBUG] - last_offset.offset: {next_offset or ''}")
            logger.info(f"[DEBUG] - fully_fetched: {meta['fully_fetched']}")
            
            try:
                async with aiofiles.open(meta_path, "w", encoding="utf-8") as wf:
                    await wf.write(json.dumps(meta, ensure_ascii=False, indent=2))
                logger.info(f"[DEBUG] 元数据已保存到: {meta_path}")
            except Exception as e:
                logger.error(f"[DEBUG] 保存元数据失败: {e}")

            # 终止条件：offset 为空
            logger.info(f"[DEBUG] 检查终止条件: next_offset={next_offset}, 是否为空: {not bool(next_offset)}")
            if not next_offset:
                _set_progress(host_mid, current_page, len(all_items), next_offset or "", f"[全部抓取完毕] 抓取完成！共获取 {len(all_items)} 条动态，总计 {current_page} 页")
                break

            # 页级停止：如收到停止信号，则抓取完本页后停止并记录 offset
            logger.info(f"[DEBUG] 检查停止信号: is_set={stop_event.is_set()}")
            if stop_event.is_set():
                logger.warning(f"[DEBUG] 🛑 收到停止信号，停止抓取")
                _set_progress(host_mid, current_page, len(all_items), next_offset or "", f"用户停止抓取，已完成 {current_page} 页，共获取 {len(all_items)} 条动态")
                break

        # 返回B站原始结构，合并所有items
        return {
            "code": 0,
            "message": "0",
            "ttl": 1,
            "data": {
                "has_more": bool(next_offset),
                "items": all_items,
                "offset": next_offset or "",
                "update_baseline": "",
                "update_num": 0,
                "fully_fetched": meta.get("fully_fetched", False),
            }
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        # 关闭后保持最后一次进度


@router.get("/space/{host_mid}", summary="获取用户空间动态")
async def get_space_dynamic(
    host_mid: int,
    pages: int = Query(1, description="获取页数，0 表示获取全部"),
    need_top: bool = Query(False, description="是否需要置顶动态"),
    save_to_db: bool = Query(True, description="是否保存到数据库"),
    save_media: bool = Query(True, description="是否保存图片等多媒体")
):
    """
    获取指定用户空间的动态列表
    
    Args:
        host_mid: 目标用户的UID
        offset: 分页偏移量
        need_top: 是否获取置顶动态
    """
    try:
        api_url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

        params = {
            "host_mid": host_mid,
            "need_top": 1 if need_top else 0,
            "features": "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,forwardListHidden,decorationCard,commentsNewVersion,onlyfansAssetsV2,ugcDelete,onlyfansQaCard",
        }
        
        logger.info(f"请求用户 {host_mid} 的空间动态，参数: {params}, pages={pages}")

        # 多页抓取：至多 pages 页；若 pages=0 则直到 offset 为空
        all_items = []
        next_offset: Optional[str] = None
        current_page = 0
        while True:
            # 注入偏移
            if next_offset:
                params["offset"] = next_offset
            
            data = await fetch_dynamic_data(api_url, params)
            # 兼容B站原始结构：从data.data中获取items和offset
            data_section = data.get("data", {}) if isinstance(data, dict) else {}
            items = data_section.get("items", []) if isinstance(data_section, dict) else []
            off = data_section.get("offset") if isinstance(data_section, dict) else None
            if isinstance(off, dict):
                next_offset = off.get("offset")
            else:
                next_offset = off

            all_items.extend(items)
            current_page += 1

            # 终止条件
            if pages == 0:
                if not next_offset:
                    break
            else:
                if current_page >= max(1, pages):
                    break
                if not next_offset:
                    break

        # 可选保存
        if save_to_db:
            try:
                conn = get_connection()
            except Exception as e:
                logger.error(f"打开动态数据库失败: {e}")
                raise HTTPException(status_code=500, detail=f"打开动态数据库失败: {str(e)}")

            items: List[Dict[str, Any]] = all_items

            base_output_dir = os.path.dirname(get_output_path("__base__"))

            # 头像保存：仅保存一次到 output/dynamic/{host_mid}/face.(ext)
            try:
                # 尝试从items提取用户头像
                face_url = None
                for item in items:
                    modules_raw = item.get("modules")
                    if isinstance(modules_raw, dict):
                        face_url = modules_raw.get("module_author", {}).get("face")
                    elif isinstance(modules_raw, list):
                        for mod in modules_raw:
                            if isinstance(mod, dict) and mod.get("module_type") == "MODULE_TYPE_AUTHOR":
                                face_url = mod.get("module_author", {}).get("user", {}).get("face") or mod.get("module_author", {}).get("face")
                                if face_url:
                                    break
                    if not face_url:
                        face_url = item.get("user", {}).get("face")
                    if face_url:
                        break

                if face_url:
                    # 若已存在头像文件则跳过
                    host_dir = os.path.dirname(get_output_path("dynamic", str(host_mid), "__host_meta.json"))
                    os.makedirs(host_dir, exist_ok=True)

                    # 检查是否已有任何文件以 face.* 命名
                    exists = any(
                        name.lower().startswith("face.")
                        for name in os.listdir(host_dir)
                        if os.path.isfile(os.path.join(host_dir, name))
                    )
                    if not exists:
                        # 下载头像一次
                        results = await download_images([face_url], host_dir)
                        # 将下载的哈希文件重命名为 face.扩展名
                        for url, local_path, ok in results:
                            if ok:
                                _, ext = os.path.splitext(local_path)
                                new_path = os.path.join(host_dir, f"face{ext}")
                                try:
                                    if os.path.exists(new_path):
                                        os.remove(new_path)
                                except Exception:
                                    pass
                                try:
                                    os.replace(local_path, new_path)
                                except Exception:
                                    pass
                                break
            except Exception as e:
                logger.warning(f"保存头像失败（忽略）：{e}")

            # 写 host_mid 元数据：最后一次获取的时间与offset
            try:
                import json, time
                host_dir = os.path.dirname(get_output_path("dynamic", str(host_mid), "__host_meta.json"))
                meta_path = os.path.join(host_dir, "__host_meta.json")

                last_offset_obj = {"offset": next_offset or "", "update_baseline": "", "update_num": 0}
                meta = {
                    "host_mid": str(host_mid),
                    "last_fetch_time": int(time.time()),
                    "last_offset": last_offset_obj,
                    "fully_fetched": False,
                }

                # 合并旧值（保留 fully_fetched 等状态）
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as rf:
                            old = json.load(rf)
                        if isinstance(old, dict):
                            meta.update({k: old.get(k, meta.get(k)) for k in ("fully_fetched",)})
                    except Exception:
                        pass

                async with aiofiles.open(meta_path, "w", encoding="utf-8") as wf:
                    await wf.write(json.dumps(meta, ensure_ascii=False, indent=2))
            except Exception as e:
                logger.warning(f"写入 host_mid 元数据失败（忽略）：{e}")

            for item in items:
                try:
                    id_str = (
                        item.get("id_str")
                        or item.get("basic", {}).get("id_str")
                        or str(item.get("id"))
                    )
                    if not id_str:
                        # 跳过无法定位ID的记录
                        continue

                    # 检查是否有多媒体文件需要下载
                    has_media = False
                    predicted_locals = []
                    live_predicted_locals = []
                    if save_media:
                        # 处理普通图片
                        image_urls = collect_image_urls(item)
                        if image_urls:
                            has_media = True
                            # 只有当包含多媒体文件时才创建文件夹
                            item_dir = os.path.dirname(
                                get_output_path("dynamic", str(host_mid), str(id_str), "media")
                            )
                            os.makedirs(item_dir, exist_ok=True)
                            
                            # 预测本地路径
                            for u in image_urls:
                                predicted_locals.append(os.path.relpath(predict_image_path(u, item_dir), base_output_dir))
                            
                            # 下载多媒体文件
                            results = await download_images(image_urls, item_dir)
                            media_records = []
                            for media_url, local_path, ok in results:
                                if ok:
                                    rel_path = os.path.relpath(local_path, base_output_dir)
                                    media_records.append((media_url, rel_path, "image"))
                        
                        # 处理实况媒体（live图片+视频）
                        live_media_pairs = collect_live_media_urls(item)
                        if live_media_pairs:
                            has_media = True
                            # 创建文件夹（如果还未创建）
                            if not image_urls:
                                item_dir = os.path.dirname(
                                    get_output_path("dynamic", str(host_mid), str(id_str), "media")
                                )
                                os.makedirs(item_dir, exist_ok=True)
                            
                            live_results = await download_live_media(live_media_pairs, item_dir)
                            for image_url, video_url, image_path, video_path, ok in live_results:
                                if ok:
                                    # 将实况媒体路径分别记录
                                    image_rel = os.path.relpath(image_path, base_output_dir)
                                    video_rel = os.path.relpath(video_path, base_output_dir)
                                    live_predicted_locals.extend([image_rel, video_rel])
                        
                        # 处理表情
                        emoji_pairs = collect_emoji_urls(item)
                        if emoji_pairs:
                            has_media = True
                            # 创建文件夹（如果还未创建）
                            if not image_urls and not live_media_pairs:
                                item_dir = os.path.dirname(
                                    get_output_path("dynamic", str(host_mid), str(id_str), "media")
                                )
                                os.makedirs(item_dir, exist_ok=True)
                            
                            emoji_results = await download_emojis(emoji_pairs, item_dir)
                            for emoji_url, emoji_path, ok in emoji_results:
                                if ok:
                                    # 将表情路径记录到普通媒体中
                                    emoji_rel = os.path.relpath(emoji_path, base_output_dir)
                                    predicted_locals.append(emoji_rel)

                    # 规范化保存到数据库
                    logger.info(f"normalize.core.call begin host_mid={host_mid} id_str={id_str}")
                    try:
                        save_normalized_dynamic_item(conn, host_mid, item)
                        logger.info(f"normalize.core.call done host_mid={host_mid} id_str={id_str}")
                        # 回写本地路径逗号串（只有当有多媒体文件时）
                        if predicted_locals or live_predicted_locals:
                            cursor = conn.cursor()
                            cursor.execute(
                                """
                                UPDATE dynamic_core SET
                                    media_locals = CASE
                                        WHEN media_locals IS NULL OR media_locals = '' THEN ?
                                        ELSE media_locals
                                    END,
                                    live_media_locals = CASE
                                        WHEN live_media_locals IS NULL OR live_media_locals = '' THEN ?
                                        ELSE live_media_locals
                                    END,
                                    live_media_count = ?
                                WHERE host_mid = ? AND id_str = ?
                                """,
                                (
                                    ",".join(predicted_locals) if predicted_locals else "",
                                    ",".join(live_predicted_locals) if live_predicted_locals else "",
                                    len(live_predicted_locals),
                                    str(host_mid),
                                    str(id_str),
                                ),
                            )
                            conn.commit()
                    except Exception as norm_err:
                        logger.warning(f"规范化保存失败（忽略）: {norm_err}")
                except Exception as perr:
                    logger.error(f"保存动态项失败 id_str={item.get('id_str')}: {perr}")

            try:
                conn.close()
            except Exception:
                pass

        # 返回B站原始结构，合并所有items
        return {
            "code": 0,
            "message": "0",
            "ttl": 1,
            "data": {
                "has_more": bool(next_offset),
                "items": all_items,
                "offset": next_offset or "",
                "update_baseline": "",
                "update_num": 0
            }
        }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户空间动态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取用户空间动态失败: {str(e)}")


@router.get("/detail/{dynamic_id}", summary="获取动态详情")
async def get_dynamic_detail(
    dynamic_id: str,
    save_to_db: bool = Query(True, description="是否保存到数据库"),
    save_media: bool = Query(True, description="是否保存图片等多媒体")
):
    """
    获取单条动态的详细信息
    
    Args:
        dynamic_id: 动态ID
    """
    try:
        api_url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
        
        params = {
            "id": dynamic_id
        }
        
        logger.info(f"请求动态详情，ID: {dynamic_id}")
        
        data = await fetch_dynamic_data(api_url, params)
        
        if save_to_db:
            try:
                conn = get_connection()
            except Exception as e:
                logger.error(f"打开动态数据库失败: {e}")
                raise HTTPException(status_code=500, detail=f"打开动态数据库失败: {str(e)}")

            # detail 接口通常返回一个 item
            data_section = data.get("data", {}) if isinstance(data, dict) else {}
            item = data_section.get("item") or data_section.get("card") or data_section

            if isinstance(item, dict):
                try:
                    id_str = (
                        item.get("id_str")
                        or item.get("basic", {}).get("id_str")
                        or str(item.get("id") or dynamic_id)
                    )

                    # 尝试从作者信息解析 host_mid，失败则用 0
                    host_mid_val = (
                        item.get("modules", {})
                        .get("module_author", {})
                        .get("mid")
                    )
                    try:
                        host_mid_int = int(host_mid_val) if host_mid_val is not None else 0
                    except Exception:
                        host_mid_int = 0

                    # 检查是否有多媒体文件需要下载
                    base_output_dir = os.path.dirname(get_output_path("__base__"))
                    has_media = False
                    predicted_locals = []
                    live_predicted_locals = []
                    if save_media:
                        # 处理普通图片
                        image_urls = collect_image_urls(item)
                        if image_urls:
                            has_media = True
                            # 只有当包含多媒体文件时才创建文件夹
                            item_dir = os.path.dirname(
                                get_output_path("dynamic", str(host_mid_int), str(id_str), "media")
                            )
                            os.makedirs(item_dir, exist_ok=True)
                            
                            # 预测本地路径
                            for u in image_urls:
                                predicted_locals.append(os.path.relpath(predict_image_path(u, item_dir), base_output_dir))
                            
                            # 下载多媒体文件
                            results = await download_images(image_urls, item_dir)
                            media_records = []
                            for media_url, local_path, ok in results:
                                if ok:
                                    rel_path = os.path.relpath(local_path, base_output_dir)
                                    media_records.append((media_url, rel_path, "image"))
                        
                        # 处理实况媒体（live图片+视频）
                        live_media_pairs = collect_live_media_urls(item)
                        if live_media_pairs:
                            has_media = True
                            # 创建文件夹（如果还未创建）
                            if not image_urls:
                                item_dir = os.path.dirname(
                                    get_output_path("dynamic", str(host_mid_int), str(id_str), "media")
                                )
                                os.makedirs(item_dir, exist_ok=True)
                            
                            live_results = await download_live_media(live_media_pairs, item_dir)
                            for image_url, video_url, image_path, video_path, ok in live_results:
                                if ok:
                                    # 将实况媒体路径分别记录
                                    image_rel = os.path.relpath(image_path, base_output_dir)
                                    video_rel = os.path.relpath(video_path, base_output_dir)
                                    live_predicted_locals.extend([image_rel, video_rel])
                        
                        # 处理表情
                        emoji_pairs = collect_emoji_urls(item)
                        if emoji_pairs:
                            has_media = True
                            # 创建文件夹（如果还未创建）
                            if not image_urls and not live_media_pairs:
                                item_dir = os.path.dirname(
                                    get_output_path("dynamic", str(host_mid_int), str(id_str), "media")
                                )
                                os.makedirs(item_dir, exist_ok=True)
                            
                            emoji_results = await download_emojis(emoji_pairs, item_dir)
                            for emoji_url, emoji_path, ok in emoji_results:
                                if ok:
                                    # 将表情路径记录到普通媒体中
                                    emoji_rel = os.path.relpath(emoji_path, base_output_dir)
                                    predicted_locals.append(emoji_rel)

                    # 保存头像一次（若存在）
                    try:
                        face_url = None
                        modules_raw = item.get("modules")
                        if isinstance(modules_raw, dict):
                            face_url = modules_raw.get("module_author", {}).get("face")
                        elif isinstance(modules_raw, list):
                            for mod in modules_raw:
                                if isinstance(mod, dict) and mod.get("module_type") == "MODULE_TYPE_AUTHOR":
                                    face_url = mod.get("module_author", {}).get("user", {}).get("face") or mod.get("module_author", {}).get("face")
                                    if face_url:
                                        break
                        if not face_url:
                            face_url = item.get("user", {}).get("face")
                        if face_url and host_mid_int:
                            host_dir = os.path.dirname(get_output_path("dynamic", str(host_mid_int), "__host_meta.json"))
                            os.makedirs(host_dir, exist_ok=True)
                            exists = any(
                                name.lower().startswith("face.")
                                for name in os.listdir(host_dir)
                                if os.path.isfile(os.path.join(host_dir, name))
                            )
                            if not exists:
                                results = await download_images([face_url], host_dir)
                                for media_url, local_path, ok in results:
                                    if ok:
                                        _, ext = os.path.splitext(local_path)
                                        new_path = os.path.join(host_dir, f"face{ext}")
                                        try:
                                            if os.path.exists(new_path):
                                                os.remove(new_path)
                                        except Exception:
                                            pass
                                        try:
                                            os.replace(local_path, new_path)
                                        except Exception:
                                            pass
                                        break
                    except Exception as e:
                        logger.warning(f"保存头像失败（忽略）：{e}")

                    # 规范化保存 + 回写预测路径（逗号分隔）
                    try:
                        save_normalized_dynamic_item(conn, host_mid_int, item)
                        if predicted_locals or live_predicted_locals:
                            cursor = conn.cursor()
                            cursor.execute(
                                """
                                UPDATE dynamic_core SET
                                    media_locals = CASE
                                        WHEN media_locals IS NULL OR media_locals = '' THEN ?
                                        ELSE media_locals
                                    END,
                                    live_media_locals = CASE
                                        WHEN live_media_locals IS NULL OR live_media_locals = '' THEN ?
                                        ELSE live_media_locals
                                    END,
                                    live_media_count = ?
                                WHERE host_mid = ? AND id_str = ?
                                """,
                                (
                                    ",".join(predicted_locals) if predicted_locals else "",
                                    ",".join(live_predicted_locals) if live_predicted_locals else "",
                                    len(live_predicted_locals),
                                    str(host_mid_int),
                                    str(id_str),
                                ),
                            )
                            conn.commit()
                    except Exception as norm_err:
                        logger.warning(f"规范化保存失败（忽略）: {norm_err}")
                except Exception as perr:
                    logger.error(f"保存动态详情失败 dynamic_id={dynamic_id}: {perr}")

            try:
                conn.close()
            except Exception:
                pass
        
        # 直接返回B站API的原始响应数据
        return data
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取动态详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取动态详情失败: {str(e)}")


@router.get("/types", summary="获取动态类型说明")
async def get_dynamic_types():
    """
    获取动态类型的说明信息
    """
    dynamic_types = {
        "DYNAMIC_TYPE_NONE": "无类型",
        "DYNAMIC_TYPE_FORWARD": "转发动态",
        "DYNAMIC_TYPE_AV": "视频动态",
        "DYNAMIC_TYPE_PGC": "番剧/影视动态",
        "DYNAMIC_TYPE_COURSES": "课程动态",
        "DYNAMIC_TYPE_WORD": "文字动态",
        "DYNAMIC_TYPE_DRAW": "图片动态",
        "DYNAMIC_TYPE_ARTICLE": "文章动态",
        "DYNAMIC_TYPE_MUSIC": "音频动态",
        "DYNAMIC_TYPE_COMMON_SQUARE": "普通方形动态",
        "DYNAMIC_TYPE_COMMON_VERTICAL": "普通竖版动态",
        "DYNAMIC_TYPE_LIVE": "直播动态",
        "DYNAMIC_TYPE_MEDIALIST": "收藏夹动态",
        "DYNAMIC_TYPE_COURSES_SEASON": "课程合集动态",
        "DYNAMIC_TYPE_COURSES_BATCH": "课程批次动态",
        "DYNAMIC_TYPE_AD": "广告动态",
        "DYNAMIC_TYPE_APPLET": "小程序动态",
        "DYNAMIC_TYPE_SUBSCRIPTION": "订阅动态",
        "DYNAMIC_TYPE_LIVE_RCMD": "直播推荐动态",
        "DYNAMIC_TYPE_BANNER": "横幅动态",
        "DYNAMIC_TYPE_UGC_SEASON": "合集动态",
        "DYNAMIC_TYPE_SUBSCRIPTION_NEW": "新订阅动态"
    }
    
    return {"types": dynamic_types}


@router.delete("/space/{host_mid}", summary="删除指定UP的动态数据（文件+数据库）")
async def delete_space_data(host_mid: int) -> Dict[str, Any]:
    """
    删除指定 host_mid 的本地动态数据目录以及数据库中所有关联记录。
    - 文件夹: output/dynamic/{host_mid}
    - 数据库表: dynamic_core / dynamic_author / dynamic_stat / dynamic_topic / major_opus_pics / major_archive_jump_urls
    """
    # 发送停止信号（若存在正在抓取的任务，页级停止）
    try:
        ev = _get_or_create_event(host_mid)
        ev.set()
    except Exception as e:
        logger.warning(f"[purge] 发送停止信号失败（忽略） host_mid={host_mid}: {e}")

    # 定位并删除文件夹
    dir_path: Optional[str] = None
    dir_existed = False
    dir_deleted = False
    try:
        dir_path = os.path.dirname(get_output_path("dynamic", str(host_mid), "__host_meta.json"))
        dir_existed = os.path.isdir(dir_path)
        if dir_existed:
            shutil.rmtree(dir_path, ignore_errors=True)
            dir_deleted = not os.path.exists(dir_path)
    except Exception as e:
        logger.error(f"[purge] 删除目录失败 host_mid={host_mid}: {e}")

    # 删除数据库记录
    try:
        conn = get_connection()
    except Exception as e:
        logger.error(f"[purge] 打开动态数据库失败: {e}")
        raise HTTPException(status_code=500, detail=f"打开动态数据库失败: {str(e)}")

    try:
        db_stats = purge_host(conn, host_mid)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {
        "host_mid": str(host_mid),
        "dir": {
            "path": dir_path,
            "existed": dir_existed,
            "deleted": dir_deleted,
        },
        "db_deleted": db_stats,
    }