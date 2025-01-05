from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime

from scripts.analyze_bilibili_history import get_daily_and_monthly_counts, get_available_years

router = APIRouter()

@router.post("/analyze", summary="分析历史数据")
async def analyze_history(
    year: Optional[int] = Query(None, description="要分析的年份，不传则使用当前年份")
):
    """分析历史数据
    
    Args:
        year: 要分析的年份，不传则使用当前年份
    """
    # 获取可用年份列表
    available_years = get_available_years()
    if not available_years:
        return {
            "status": "error",
            "message": "未找到任何历史记录数据"
        }
    
    # 如果未指定年份，使用最新的年份
    target_year = year if year is not None else available_years[0]
    
    # 检查指定的年份是否可用
    if year is not None and year not in available_years:
        return {
            "status": "error",
            "message": f"未找到 {year} 年的历史记录数据。可用的年份有：{', '.join(map(str, available_years))}"
        }
    
    result = get_daily_and_monthly_counts(target_year)
    if "error" in result:
        return {"status": "error", "message": result["error"]}
    return {
        "status": "success",
        "message": "分析完成",
        "data": result,
        "year": target_year,
        "available_years": available_years
    }
