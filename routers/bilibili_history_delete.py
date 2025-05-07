"""
B站历史记录删除API
实现B站历史记录的删除功能，支持单条和批量删除
"""

from typing import List

import requests
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from scripts.utils import load_config

router = APIRouter()

class DeleteHistoryItem(BaseModel):
    """删除历史记录项目模型"""
    kid: str = Field(..., description="删除的目标记录，格式为{业务类型}_{目标id}")
    sync_to_bilibili: bool = Field(True, description="是否同步删除B站服务器上的记录")

class BatchDeleteRequest(BaseModel):
    """批量删除请求模型"""
    items: List[DeleteHistoryItem] = Field(..., description="要删除的历史记录列表")

def get_headers():
    """获取请求头"""
    # 动态读取配置文件，获取最新的SESSDATA
    current_config = load_config()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://www.bilibili.com/',
        'Origin': 'https://www.bilibili.com',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    # 添加Cookie
    cookies = []
    if 'SESSDATA' in current_config:
        cookies.append(f"SESSDATA={current_config['SESSDATA']}")
    if 'bili_jct' in current_config:
        cookies.append(f"bili_jct={current_config['bili_jct']}")
    if 'DedeUserID' in current_config:
        cookies.append(f"DedeUserID={current_config['DedeUserID']}")

    if cookies:
        headers['Cookie'] = '; '.join(cookies)

    return headers

@router.delete("/single", summary="删除单条历史记录")
async def delete_single_history(
    kid: str = Query(..., description="删除的目标记录，格式为{业务类型}_{目标id}"),
    sync_to_bilibili: bool = Query(True, description="是否同步删除B站服务器上的记录")
):
    """
    删除单条历史记录

    - **kid**: 删除的目标记录，格式为{业务类型}_{目标id}
      - 视频：archive_{稿件bvid}
      - 直播：live_{直播间id}
      - 专栏：article_{专栏cvid}
      - 剧集：pgc_{剧集ssid}
      - 文集：article-list_{文集rlid}
    - **sync_to_bilibili**: 是否同步删除B站服务器上的记录
    """
    try:
        # 如果需要同步删除B站服务器上的记录
        if sync_to_bilibili:
            # 获取配置
            current_config = load_config()
            bili_jct = current_config.get("bili_jct", "")

            if not bili_jct:
                return {
                    "status": "error",
                    "message": "缺少CSRF Token (bili_jct)，请先使用QR码登录并确保已正确获取bili_jct"
                }

            # 准备请求参数
            data = {
                "kid": kid,
                "csrf": bili_jct
            }

            # 发送请求
            headers = get_headers()
            response = requests.post(
                "https://api.bilibili.com/x/v2/history/delete",
                data=data,  # 使用form-urlencoded格式
                headers=headers
            )

            # 解析响应
            result = response.json()

            if result.get("code") != 0:
                return {
                    "status": "error",
                    "message": f"删除B站历史记录失败: {result.get('message', '未知错误')}",
                    "code": result.get("code"),
                    "data": result
                }

        # 返回成功结果
        return {
            "status": "success",
            "message": "历史记录删除成功",
            "data": {
                "kid": kid,
                "sync_to_bilibili": sync_to_bilibili
            }
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"删除历史记录失败: {str(e)}"
        }

@router.delete("/batch", summary="批量删除历史记录")
async def batch_delete_history(request: BatchDeleteRequest):
    """
    批量删除历史记录

    - **items**: 要删除的历史记录列表，每个记录包含kid和是否同步删除B站服务器上的记录的标志
    """
    try:
        # 获取配置
        current_config = load_config()
        bili_jct = current_config.get("bili_jct", "")

        if not bili_jct:
            return {
                "status": "error",
                "message": "缺少CSRF Token (bili_jct)，请先使用QR码登录并确保已正确获取bili_jct"
            }

        # 处理结果
        results = []
        success_count = 0
        error_count = 0

        # 需要同步删除B站服务器上的记录的项目
        sync_items = [item for item in request.items if item.sync_to_bilibili]

        # 如果有需要同步删除的记录
        if sync_items:
            # 准备请求参数 - 支持批量删除，用逗号分隔多个kid
            kids = ",".join([item.kid for item in sync_items])
            data = {
                "kid": kids,
                "csrf": bili_jct
            }

            # 发送请求
            headers = get_headers()
            response = requests.post(
                "https://api.bilibili.com/x/v2/history/delete",
                data=data,  # 使用form-urlencoded格式
                headers=headers
            )

            # 解析响应
            result = response.json()

            if result.get("code") == 0:
                success_count += len(sync_items)
                for item in sync_items:
                    results.append({
                        "kid": item.kid,
                        "sync_to_bilibili": True,
                        "status": "success"
                    })
            else:
                error_count += len(sync_items)
                error_message = result.get('message', '未知错误')
                for item in sync_items:
                    results.append({
                        "kid": item.kid,
                        "sync_to_bilibili": True,
                        "status": "error",
                        "message": error_message
                    })

        # 处理不需要同步删除的记录
        for item in request.items:
            if not item.sync_to_bilibili:
                success_count += 1
                results.append({
                    "kid": item.kid,
                    "sync_to_bilibili": False,
                    "status": "success"
                })

        # 返回结果
        return {
            "status": "success" if error_count == 0 else "partial_success",
            "message": f"成功删除 {success_count} 条历史记录，失败 {error_count} 条",
            "data": {
                "success_count": success_count,
                "error_count": error_count,
                "results": results
            }
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"批量删除历史记录失败: {str(e)}"
        }
