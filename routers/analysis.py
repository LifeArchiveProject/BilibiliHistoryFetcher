from fastapi import APIRouter

from scripts.analyze_bilibili_history import get_daily_and_monthly_counts

router = APIRouter()

@router.post("/analyze", summary="分析历史数据")
async def analyze_history():
    """分析历史数据"""
    result = get_daily_and_monthly_counts()
    if "error" in result:
        return {"status": "error", "message": result["error"]}
    return {
        "status": "success",
        "message": "分析完成",
        "data": result
    }
