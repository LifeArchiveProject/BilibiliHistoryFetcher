import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body

from scripts.send_log_email import send_email
from scripts.utils import get_logs_path

router = APIRouter()

@router.post("/send-email", summary="发送日志邮件")
async def send_log_email(
    subject: str = Body(..., description="邮件主题"),
    content: Optional[str] = Body(None, description="邮件内容，如果为None则发送当天的日志内容"),
    to_email: Optional[str] = Body(None, description="收件人邮箱，不填则使用配置文件中的默认收件人")
):
    """发送日志邮件"""
    try:
        # 如果没有提供内容，则读取当天的日志文件
        if content is None:
            log_file = get_logs_path()
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = "今日暂无日志记录"

        # 格式化内容，添加时间戳
        formatted_content = f"""
时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

=== 执行日志 ===
{content}
=============
"""
        
        result = await send_email(
            subject=subject,
            content=formatted_content,
            to_email=to_email
        )
        return {"status": "success", "message": "邮件发送成功"}
    except Exception as e:
        return {"status": "error", "message": f"邮件发送失败: {str(e)}"}
