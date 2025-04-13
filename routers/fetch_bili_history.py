from typing import Optional, Union
import logging

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, Field
import time
import json
import asyncio
import os

from scripts.bilibili_history import fetch_history, find_latest_local_history, fetch_and_compare_history, save_history, \
    load_cookie, fetch_video_details_only, get_invalid_videos_from_db, get_video_details_stats
from scripts.import_sqlite import import_all_history_files
from scripts.utils import load_config

# 配置日志记录
logger = logging.getLogger(__name__)

router = APIRouter()

config = load_config()

# 定义请求体模型
class FetchHistoryRequest(BaseModel):
    sessdata: Optional[str] = Field(None, description="用户的 SESSDATA")


# 定义响应模型
class ResponseModel(BaseModel):
    status: str
    message: str
    data: Optional[Union[list, dict]] = None


def get_headers():
    """获取请求头"""
    # 动态读取配置文件，获取最新的SESSDATA
    current_config = load_config()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Cookie': f'SESSDATA={current_config["SESSDATA"]}'
    }
    return headers


@router.get("/bili-history", summary="获取B站历史记录")
async def get_bili_history(output_dir: Optional[str] = "history_by_date", skip_exists: bool = True, process_video_details: bool = False):
    """获取B站历史记录"""
    try:
        result = await fetch_history(output_dir, skip_exists, process_video_details)
        return {
            "status": "success",
            "message": "历史记录获取成功",
            "data": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取历史记录失败: {str(e)}"
        }


@router.get("/bili-history-realtime", summary="实时获取B站历史记录", response_model=ResponseModel)
async def get_bili_history_realtime(sync_deleted: bool = False, process_video_details: bool = False):
    """实时获取B站历史记录"""
    try:
        # 获取最新的本地历史记录时间戳
        latest_history = find_latest_local_history()
        if not latest_history:
            return {"status": "error", "message": "未找到本地历史记录"}

        # 获取cookie
        cookie = load_cookie()
        if not cookie:
            return {"status": "error", "message": "未找到有效的cookie"}

        # 获取新的历史记录 - 使用await，因为fetch_and_compare_history现在是异步函数
        new_records = await fetch_and_compare_history(cookie, latest_history, True, process_video_details)  # 传递process_video_details参数
        
        # 保存新历史记录的结果信息
        history_result = {"new_records_count": 0, "inserted_count": 0}
        video_details_result = {"processed": False}

        if new_records:
            # 保存新记录
            save_result = save_history(new_records)
            logger.info("成功保存新记录到本地文件")
            history_result["new_records_count"] = len(new_records)

            # 更新SQLite数据库
            logger.info("=== 开始更新SQLite数据库 ===")
            logger.info(f"同步已删除记录: {sync_deleted}")
            db_result = import_all_history_files(sync_deleted=sync_deleted)
            
            if db_result["status"] == "success":
                history_result["inserted_count"] = db_result['inserted_count']
                history_result["status"] = "success"
            else:
                history_result["status"] = "error"
                history_result["message"] = db_result["message"]
        else:
            history_result["status"] = "success"
            history_result["message"] = "没有新记录"
        
        # 处理视频详情 - 已经在fetch_and_compare_history中处理过，这里不需要重复处理
        # 只需生成结果信息
        if process_video_details:
            logger.info("视频详情已在历史记录获取过程中处理")
            video_details_result = {
                "status": "success", 
                "message": "视频详情已在历史记录获取过程中处理",
                "processed": True
            }
        
        # 返回综合结果
        if history_result.get("status") == "success" and (not process_video_details or video_details_result.get("status") == "success"):
            message = "实时更新成功"
            if history_result.get("new_records_count", 0) > 0:
                message += f"，获取到 {history_result['new_records_count']} 条新记录"
                if history_result.get("inserted_count", 0) > 0:
                    message += f"，成功导入 {history_result['inserted_count']} 条记录到SQLite数据库"
            else:
                message += "，暂无新历史记录"
                
            if process_video_details:
                message += "。视频详情已在历史记录获取过程中处理"
            
            return {
                "status": "success", 
                "message": message, 
                "data": {
                    "history": history_result,
                    "video_details": video_details_result.get("data", {})
                }
            }
        else:
            # 有一个失败就返回错误
            error_message = []
            if history_result.get("status") == "error":
                error_message.append(f"历史记录处理失败: {history_result.get('message', '未知错误')}")
            if process_video_details and video_details_result.get("status") == "error":
                error_message.append(f"视频详情处理失败: {video_details_result.get('message', '未知错误')}")
                
            return {
                "status": "error", 
                "message": " | ".join(error_message), 
                "data": {
                    "history": history_result,
                    "video_details": video_details_result.get("data", {})
                }
            }

    except Exception as e:
        error_msg = f"实时更新失败: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())  # 添加详细的堆栈跟踪
        return {"status": "error", "message": error_msg}


# 全局变量，用于存储处理进度
video_details_progress = {
    "is_processing": False,
    "total_videos": 0,
    "processed_videos": 0,
    "success_count": 0,
    "failed_count": 0,
    "error_videos": [],
    "skipped_invalid_count": 0,
    "start_time": 0,
    "last_update_time": 0,
    "is_complete": False
}

@router.get("/fetch-video-details", summary="获取历史记录中的视频详情")
async def fetch_video_details(
    max_videos: int = Query(100, description="本次最多处理的视频数量，0表示不限制"),
    specific_videos: Optional[str] = Query(None, description="要获取的特定视频ID列表，用逗号分隔"),
    batch_size: int = Query(20, description="批处理大小，每批处理的视频数量，0表示使用默认值20"),
    background_tasks: BackgroundTasks = None
):
    """从历史记录中获取视频ID，批量获取视频详情"""
    try:
        # 确保参数合法
        if batch_size <= 0:
            batch_size = 20  # 如果传入0或负数，使用默认值
            
        # 解析特定视频列表
        video_list = None
        if specific_videos:
            video_list = [video_id.strip() for video_id in specific_videos.split(',') if video_id.strip()]
            if not video_list:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": "提供的视频ID列表为空"
                    }
                )
        
        # 重置进度信息
        global video_details_progress
        video_details_progress = {
            "is_processing": True,
            "total_videos": len(video_list) if video_list else 0,
            "processed_videos": 0,
            "success_count": 0,
            "failed_count": 0,
            "error_videos": [],
            "skipped_invalid_count": 0,
            "start_time": time.time(),
            "last_update_time": time.time(),
            "is_complete": False
        }
        
        # 使用后台任务异步执行详情获取，不阻塞API响应
        if background_tasks:
            background_tasks.add_task(fetch_video_details_only, batch_size, max_videos, video_list)
            
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "视频详情获取已在后台启动，请使用进度API监控进度",
                    "data": {
                        "is_processing": True,
                        "total_videos": video_details_progress["total_videos"],
                        "processed_videos": 0,
                        "progress_percentage": 0,
                        "elapsed_time": "0.00秒"
                    }
                }
            )
        else:
            # 如果没有传入background_tasks，则同步执行
            result = await fetch_video_details_only(batch_size, max_videos, video_list)
            
            return JSONResponse(
                status_code=200,
                content={
                    "status": result["status"],
                    "message": result["message"],
                    "data": result.get("data", {})
                }
            )
    except Exception as e:
        # 更新进度为失败
        video_details_progress["is_processing"] = False
        video_details_progress["is_complete"] = True
        video_details_progress["last_update_time"] = time.time()
        
        error_msg = f"获取视频详情失败: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": error_msg
            }
        )

@router.get("/fetch-video-details-progress", summary="获取视频详情处理进度(流式)")
async def fetch_video_details_progress(
    request: Request,
    update_interval: float = Query(0.1, description="更新间隔, 单位秒")
):
    """
    使用SSE(Server-Sent Events)获取视频详情处理的实时进度
    """
    async def event_generator():
        while True:
            # 检查客户端是否已断开连接
            if await request.is_disconnected():
                break
                
            # 如果处理已完成且最后更新时间超过5秒，结束流
            if video_details_progress["is_complete"] and (time.time() - video_details_progress["last_update_time"]) > 5:
                # 发送最后一次完整进度
                current_time = time.time()
                elapsed_time = current_time - video_details_progress["start_time"]
                
                progress_data = {
                    "is_processing": False,
                    "total_videos": video_details_progress["total_videos"],
                    "processed_videos": video_details_progress["processed_videos"],
                    "success_count": video_details_progress["success_count"],
                    "failed_count": video_details_progress["failed_count"],
                    "error_videos": video_details_progress["error_videos"][-10:],  # 只返回最后10个错误
                    "skipped_invalid_count": video_details_progress.get("skipped_invalid_count", 0),
                    "progress_percentage": 100 if video_details_progress["total_videos"] > 0 
                                           else 0,
                    "elapsed_time": f"{elapsed_time:.2f}秒",
                    "is_complete": True
                }
                
                yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
                break
            
            # 计算处理进度百分比
            progress_percentage = 0
            if video_details_progress["total_videos"] > 0:
                progress_percentage = (video_details_progress["processed_videos"] / 
                                      video_details_progress["total_videos"]) * 100
            
            # 计算经过的时间
            current_time = time.time()
            elapsed_time = current_time - video_details_progress["start_time"]
            
            # 创建进度数据
            progress_data = {
                "is_processing": video_details_progress["is_processing"],
                "total_videos": video_details_progress["total_videos"],
                "processed_videos": video_details_progress["processed_videos"],
                "success_count": video_details_progress["success_count"],
                "failed_count": video_details_progress["failed_count"],
                "error_videos": video_details_progress["error_videos"][-10:],  # 只返回最后10个错误
                "skipped_invalid_count": video_details_progress.get("skipped_invalid_count", 0),
                "progress_percentage": round(progress_percentage, 2),
                "elapsed_time": f"{elapsed_time:.2f}秒",
                "is_complete": video_details_progress["is_complete"]
            }
            
            # 发送事件
            yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
            
            # 等待指定的更新间隔
            await asyncio.sleep(update_interval)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

# 实现从scripts.bilibili_history导入的fetch_video_details_only函数
async def fetch_video_details_only(batch_size=20, max_videos=0, specific_videos=None):
    """从数据库中获取视频ID，批量获取视频详情，不重新获取历史记录"""
    try:
        # 确保参数是合法整数
        if max_videos is None:
            max_videos = 0
        if batch_size is None or batch_size <= 0:
            batch_size = 20
            
        print(f"开始获取视频详情 (batch_size={batch_size}, max_videos={max_videos})")
        start_time = time.time()
        
        # 获取history库中所有视频ID
        from scripts.bilibili_history import get_video_info_sync, batch_save_video_details, check_invalid_video, create_invalid_videos_table
        from scripts.utils import get_output_path, load_config
        import sqlite3
        import random
        import concurrent.futures
        
        # 获取cookie
        current_config = load_config()
        cookie = current_config.get('SESSDATA', '')
        if not cookie:
            raise Exception("未找到SESSDATA配置")
        
        # 更新总视频数
        global video_details_progress
        
        # 如果提供了specific_videos参数，直接使用，不查询数据库
        if specific_videos:
            videos_to_fetch = specific_videos
            total_videos_to_fetch = len(videos_to_fetch)
            print(f"使用指定的视频列表，共 {total_videos_to_fetch} 个视频")
            
            # 更新当前批次的目标数量
            video_details_progress["total_videos"] = total_videos_to_fetch
            video_details_progress["skipped_invalid_count"] = 0
            
            if not videos_to_fetch:
                print("指定的视频列表为空")
                video_details_progress["is_complete"] = True
                video_details_progress["last_update_time"] = time.time()
                return {
                    "status": "success",
                    "message": "指定的视频列表为空，无需处理",
                    "total_videos": 0,
                    "processed_videos": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_invalid_count": 0,
                    "execution_time": "0.00秒",
                    "error_videos": []
                }
        else:
            # 查询历史记录数据库中的所有bvid
            history_db_path = get_output_path("bilibili_history.db")
            video_db_path = get_output_path("video_library.db")
            
            conn_history = sqlite3.connect(history_db_path)
            cursor_history = conn_history.cursor()
            
            print("查询历史记录数据库中的视频ID...")
            
            # 首先获取所有年份的表
            cursor_history.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name LIKE 'bilibili_history_%'
            """)
            
            history_tables = cursor_history.fetchall()
            
            if not history_tables:
                raise Exception("未找到历史记录表")
            
            # 构建查询所有年份表的UNION查询
            all_bvids = []
            for table in history_tables:
                table_name = table[0]
                cursor_history.execute(f"""
                    SELECT DISTINCT bvid FROM {table_name} 
                    WHERE bvid IS NOT NULL AND bvid != ''
                """)
                bvids = [row[0] for row in cursor_history.fetchall()]
                all_bvids = list(set(all_bvids + bvids))
                print(f"从表 {table_name} 中找到 {len(bvids)} 个视频ID")
            
            conn_history.close()
            
            print(f"历史记录数据库中找到 {len(all_bvids)} 个视频ID")
            
            # 查询视频库中已有的bvid
            conn_video = sqlite3.connect(video_db_path)
            cursor_video = conn_video.cursor()
            
            try:
                cursor_video.execute("SELECT bvid FROM video_details")
                existing_bvids = {row[0] for row in cursor_video.fetchall()}
            except sqlite3.OperationalError:
                # 如果表不存在
                existing_bvids = set()
            
            # 确保失效视频表存在
            create_invalid_videos_table()
            
            # 查询已知的失效视频
            try:
                cursor_video.execute("SELECT bvid, error_type FROM invalid_videos")
                invalid_bvids = {row[0]: row[1] for row in cursor_video.fetchall()}
                print(f"已知失效视频数量: {len(invalid_bvids)}")
                
                # 按错误类型统计失效视频
                error_type_counts = {}
                for error_type in invalid_bvids.values():
                    if error_type not in error_type_counts:
                        error_type_counts[error_type] = 0
                    error_type_counts[error_type] += 1
                    
                print("失效视频类型统计:")
                for error_type, count in error_type_counts.items():
                    print(f"  - {error_type}: {count}个")
            except sqlite3.OperationalError:
                # 如果表不存在或查询错误
                invalid_bvids = {}
                print("未找到失效视频表或查询失败")
            
            conn_video.close()
            
            print(f"视频库中已有 {len(existing_bvids)} 个视频ID")
            
            # 找出需要获取详情的视频ID，排除已知失效视频
            videos_to_fetch = []
            skipped_invalid_videos = []
            
            for bvid in all_bvids:
                if bvid in existing_bvids:
                    # 已存在于视频库中，跳过
                    continue
                elif bvid in invalid_bvids:
                    # 已知失效视频，跳过并记录
                    skipped_invalid_videos.append({
                        "bvid": bvid,
                        "error_type": invalid_bvids[bvid]
                    })
                    continue
                else:
                    # 需要获取详情的视频
                    videos_to_fetch.append(bvid)
            
            total_videos_to_fetch = len(videos_to_fetch)
            print(f"需要获取详情的视频数量: {total_videos_to_fetch} (排除了 {len(skipped_invalid_videos)} 个已知失效视频)")
            
            # 更新当前批次的目标数量和跳过的无效视频信息
            video_details_progress["total_videos"] = total_videos_to_fetch
            video_details_progress["skipped_invalid_count"] = len(skipped_invalid_videos)
            
            if not videos_to_fetch:
                print("所有历史记录的视频详情都已获取或已知失效")
                video_details_progress["is_complete"] = True
                video_details_progress["last_update_time"] = time.time()
                return {
                    "status": "success",
                    "message": "无需处理新视频",
                    "total_videos": len(all_bvids),
                    "processed_videos": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_invalid_count": len(skipped_invalid_videos),
                    "skipped_invalid_videos": skipped_invalid_videos[:100],  # 只返回前100个，避免数据过大
                    "execution_time": "0.00秒",
                    "error_videos": []
                }
            
            # 限制每次处理的视频数量
            if max_videos > 0 and len(videos_to_fetch) > max_videos:
                print(f"限制处理的视频数量为 {max_videos} 个")
                videos_to_fetch = videos_to_fetch[:max_videos]
                # 更新当前批次的目标数量为实际要处理的数量
                video_details_progress["total_videos"] = len(videos_to_fetch)
            
            # 降低并发线程数，避免过高并发导致412错误
            max_workers = min(10, len(videos_to_fetch))  # 降低到10个线程，避免过多请求
            
            total_success = 0
            total_fail = 0
            error_videos = []
            
            # 分批处理
            batch_sizes = max(1, min(batch_size, 20))  # 确保批次大小至少为1，最大为20
            batches = [videos_to_fetch[i:i+batch_sizes] for i in range(0, len(videos_to_fetch), batch_sizes)]
            
            # 随机打乱视频顺序，避免按顺序请求被检测
            random.shuffle(videos_to_fetch)
            
            # 修改为批次处理，避免事件循环问题
            for batch_idx, batch in enumerate(batches):
                print(f"处理批次 {batch_idx+1}/{len(batches)}, 视频数量: {len(batch)}")
                
                # 创建线程池在后台执行同步函数
                batch_results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 映射函数与参数
                    future_to_bvid = {executor.submit(get_video_info_sync, bvid, cookie, False): bvid for bvid in batch}
                    
                    # 等待所有任务完成
                    for future in concurrent.futures.as_completed(future_to_bvid):
                        bvid = future_to_bvid[future]
                        try:
                            result = future.result()
                            if result and result.status == "success":
                                batch_results.append(result)
                                # 更新成功计数
                                video_details_progress["success_count"] += 1
                            else:
                                error_msg = result.message if result else "未知错误"
                                print(f"获取视频 {bvid} 的详情失败: {error_msg}")
                                error_videos.append(bvid)
                                video_details_progress["error_videos"].append(bvid)
                                video_details_progress["failed_count"] += 1
                        except Exception as e:
                            print(f"处理视频 {bvid} 时出错: {e}")
                            error_videos.append(bvid)
                            video_details_progress["error_videos"].append(bvid)
                            video_details_progress["failed_count"] += 1
                        
                        # 更新处理总数
                        video_details_progress["processed_videos"] += 1
                        video_details_progress["last_update_time"] = time.time()
                
                # 批量保存成功获取到的视频详情
                if batch_results:
                    batch_result = batch_save_video_details(batch_results)
                    # 调整成功/失败计数
                    success_count = batch_result.get("success", 0)
                    failed_count = batch_result.get("fail", 0)
                    total_success += success_count
                    total_fail += failed_count
                    
                    print(f"批次完成: 成功 {success_count}，失败 {failed_count}")
                
                # 批次之间暂停，避免请求过快
                if batch_idx < len(batches) - 1:  # 如果不是最后一批
                    batch_delay = 2 + random.random() * 3  # 2-5秒随机延迟
                    print(f"批次间暂停 {batch_delay:.2f} 秒...")
                    await asyncio.sleep(batch_delay)
            
            # 计算执行时间
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"视频详情获取完成，耗时: {execution_time:.2f}秒")
            
            # 更新进度为完成
            video_details_progress["is_complete"] = True
            video_details_progress["last_update_time"] = time.time()
            
            # 返回结果
            return {
                "status": "success",
                "message": "视频详情获取完成",
                "total_videos": video_details_progress["total_videos"],
                "processed_videos": video_details_progress["processed_videos"],
                "success_count": video_details_progress["success_count"],
                "failed_count": video_details_progress["failed_count"],
                "skipped_invalid_count": len(skipped_invalid_videos),
                "skipped_invalid_videos": skipped_invalid_videos[:20],  # 只返回部分示例
                "execution_time": f"{execution_time:.2f}秒",
                "error_videos": error_videos
            }
            
    except Exception as e:
        print(f"获取视频详情失败: {str(e)}")
        import traceback
        print(traceback.format_exc())
        # 更新进度为失败
        video_details_progress["is_complete"] = True
        video_details_progress["last_update_time"] = time.time()
        raise e

# 添加新的API端点用于查询失效视频列表
@router.get("/invalid-videos", summary="获取失效视频列表")
async def get_invalid_videos(
    page: int = Query(1, description="页码，从1开始"),
    limit: int = Query(50, description="每页返回数量，最大100"),
    error_type: Optional[str] = Query(None, description="按错误类型筛选")
):
    """获取失效视频列表"""
    try:
        result = await get_invalid_videos_from_db(page, limit, error_type)
        return result
    except Exception as e:
        print(f"获取失效视频列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取失效视频列表失败: {str(e)}"
        )

# 视频详情统计接口
@router.get("/video-details-stats", summary="获取视频详情统计数据")
async def video_details_statistics():
    """
    获取视频详情统计数据，包括总视频数、已获取详情数、失效视频数、待获取视频数
    """
    try:
        result = await get_video_details_stats()
        
        if result["status"] == "success":
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "成功获取视频详情统计数据",
                    "data": result["data"]
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": result["message"]
                }
            )
    except Exception as e:
        error_msg = f"获取视频详情统计数据失败: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": error_msg
            }
        )
