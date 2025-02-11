from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
import os

from scripts.image_downloader import ImageDownloader
from scripts.utils import get_output_path

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

@router.get("/local/{image_type}/{file_hash}")
async def get_local_image(image_type: str, file_hash: str):
    """获取本地图片
    
    Args:
        image_type: 图片类型 (covers 或 avatars)
        file_hash: 图片文件的哈希值
        
    Returns:
        FileResponse: 图片文件响应
    """
    print(f"\n=== 获取本地图片 ===")
    print(f"图片类型: {image_type}")
    print(f"文件哈希: {file_hash}")
    
    # 验证图片类型
    if image_type not in ('covers', 'avatars'):
        raise HTTPException(
            status_code=400,
            detail=f"无效的图片类型: {image_type}"
        )
    
    try:
        # 构建图片路径
        base_path = get_output_path('images')
        type_path = os.path.join(base_path, image_type)
        sub_dir = file_hash[:2]  # 使用哈希的前两位作为子目录
        img_dir = os.path.join(type_path, sub_dir)
        
        # 查找匹配的图片文件
        if not os.path.exists(img_dir):
            raise HTTPException(
                status_code=404,
                detail=f"图片不存在: {file_hash}"
            )
            
        # 查找所有可能的图片文件扩展名
        for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            img_path = os.path.join(img_dir, f"{file_hash}{ext}")
            if os.path.exists(img_path):
                print(f"找到图片文件: {img_path}")
                return FileResponse(
                    img_path,
                    media_type=f"image/{ext[1:]}" if ext != '.jpg' else "image/jpeg"
                )
        
        # 如果没有找到任何匹配的文件
        raise HTTPException(
            status_code=404,
            detail=f"图片不存在: {file_hash}"
        )
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print(f"获取本地图片时出错: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取图片失败: {str(e)}"
        ) 