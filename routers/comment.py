from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from scripts.comment_fetcher import fetch_and_save_comments, get_user_comments
from enum import Enum

router = APIRouter()

class CommentType(str, Enum):
    ALL = "all"
    ROOT = "root"
    REPLY = "reply"

@router.post("/fetch/{uid}", summary="获取用户评论")
async def fetch_user_comments(uid: str):
    """
    获取并保存用户的评论数据
    
    Args:
        uid: 用户ID
        
    Returns:
        dict: 包含操作结果、评论总数和最新评论时间的字典
    """
    try:
        result = fetch_and_save_comments(uid)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/query/{uid}", summary="查询用户评论")
async def query_user_comments(
    uid: str,
    page: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(20, description="每页数量"),
    comment_type: CommentType = Query(CommentType.ALL, description="评论类型：all-全部, root-一级评论, reply-二级评论"),
    keyword: Optional[str] = Query(None, description="关键词，用于模糊匹配评论内容"),
    type_filter: Optional[int] = Query(None, description="评论类型筛选，例如：1(视频评论)，17(动态评论)等")
):
    """
    查询用户的评论数据，如果数据库中没有该用户的数据会自动获取
    
    Args:
        uid: 用户ID
        page: 页码，从1开始
        page_size: 每页数量
        comment_type: 评论类型，可选值：all（全部）, root（一级评论）, reply（二级评论）
        keyword: 关键词，用于模糊匹配评论内容
        type_filter: 评论类型筛选，例如：1(视频评论)，17(动态评论)等
        
    Returns:
        dict: 包含评论列表和分页信息的字典
    """
    try:
        result = get_user_comments(
            uid=uid,
            page=page,
            page_size=page_size,
            comment_type=comment_type,
            keyword=keyword or "",
            comment_type_filter=type_filter
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 