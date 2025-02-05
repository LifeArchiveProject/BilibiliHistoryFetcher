from typing import Optional
from fastapi import APIRouter, BackgroundTasks

from scripts.image_downloader import ImageDownloader

router = APIRouter()
downloader = ImageDownloader()

@router.post("/start")
async def start_download(
    background_tasks: BackgroundTasks,
    year: Optional[int] = None
):
    """开始下载图片
    
    Args:
        year: 指定年份，不指定则下载所有年份
    """
    # 在后台任务中执行下载
    background_tasks.add_task(downloader.start_download, year)
    
    return {
        "status": "success",
        "message": f"开始下载{'所有年份' if year is None else f'{year}年'}的图片"
    }

@router.get("/status")
async def get_status():
    """获取下载状态"""
    stats = downloader.get_download_stats()
    
    return {
        "status": "success",
        "data": stats
    }

@router.post("/clear")
async def clear_images():
    """清空所有图片和下载状态"""
    try:
        success = downloader.clear_all_images()
        if success:
            return {
                "status": "success",
                "message": "已清空所有图片和下载状态",
                "data": {
                    "cleared_paths": [
                        "output/images/covers",
                        "output/images/avatars",
                        "output/images/orphaned_covers",
                        "output/images/orphaned_avatars"
                    ],
                    "status_file": "output/download_status.json"
                }
            }
        else:
            return {
                "status": "error",
                "message": "清空图片失败，请查看日志了解详细信息"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"清空图片时发生错误: {str(e)}"
        } 