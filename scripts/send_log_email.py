import os
import smtplib
from datetime import datetime, timedelta
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict

from loguru import logger

from scripts.utils import load_config, get_logs_path, setup_logger

# 确保日志系统已初始化
setup_logger()


def get_task_execution_logs() -> str:
    """
    获取任务执行期间的日志

    通过查找日志文件中的任务执行标记，提取出任务执行期间的日志内容

    Returns:
        str: 任务执行期间的日志内容
    """
    log_file = get_logs_path()
    if not os.path.exists(log_file):
        return "今日暂无日志记录"

    with open(log_file, 'r', encoding='utf-8') as f:
        log_lines = f.readlines()

    # 查找最近一次任务执行的开始和结束位置
    start_index = -1
    end_index = len(log_lines)

    # 从后向前查找最近的任务执行开始标记
    for i in range(len(log_lines) - 1, -1, -1):
        line = log_lines[i]
        if "=== 执行任务链:" in line or "=== 执行任务:" in line:
            start_index = i
            break

    # 如果找不到任务执行标记，则返回空字符串
    if start_index == -1:
        return "未找到任务执行记录"

    # 提取任务执行期间的日志
    task_logs = log_lines[start_index:end_index]
    return "".join(task_logs)


async def send_email(subject: str, content: Optional[str] = None, to_email: Optional[str] = None) -> Dict:
    """
    发送邮件

    Args:
        subject: 邮件主题
        content: 邮件内容，如果为None则发送当天的任务执行日志
        to_email: 收件人邮箱，如果为None则使用配置文件中的默认收件人

    Returns:
        dict: 发送结果，包含status和message
    """
    logger.info(f"准备发送邮件: {subject}")
    try:
        config = load_config()
        smtp_server = config.get('email', {}).get('smtp_server', 'smtp.qq.com')
        smtp_port = config.get('email', {}).get('smtp_port', 587)
        sender_email = config.get('email', {}).get('sender')
        sender_password = config.get('email', {}).get('password')
        receiver_email = to_email or config.get('email', {}).get('receiver')

        if not all([sender_email, sender_password, receiver_email]):
            logger.error("邮件配置不完整，请检查配置文件")
            raise ValueError("邮件配置不完整，请检查配置文件")

        # 如果没有提供内容，则获取任务执行期间的日志
        if content is None:
            content = get_task_execution_logs()

        # 格式化主题（替换时间占位符）
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = subject.format(current_time=current_time)

        # 创建邮件对象
        message = MIMEMultipart()
        message['From'] = Header(sender_email)
        message['To'] = Header(receiver_email)
        message['Subject'] = Header(subject)

        # 添加邮件内容
        message.attach(MIMEText(content, 'plain', 'utf-8'))

        # 连接SMTP服务器并发送
        server = None
        email_sent = False

        try:
            # 不使用 with 语句，以便更好地控制异常处理流程
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(message)
            email_sent = True  # 标记邮件已成功发送
        except smtplib.SMTPException as e:
            raise Exception(f"SMTP错误: {str(e)}")
        except TimeoutError:
            raise Exception("SMTP服务器连接超时")
        finally:
            # 安全关闭连接
            if server:
                try:
                    server.quit()
                except Exception as e:
                    # 如果邮件已经发送成功，则忽略关闭连接时的错误
                    if email_sent:
                        return {"status": "success", "message": "邮件发送成功（服务器连接关闭时出现非致命错误）"}
                    else:
                        # 如果邮件未发送成功，则抛出关闭连接时的错误
                        raise Exception(f"关闭SMTP连接时出错: {str(e)}")

        # 如果执行到这里，说明邮件发送成功且连接正常关闭
        logger.info(f"邮件发送成功: {subject}")
        return {"status": "success", "message": "邮件发送成功"}

    except Exception as e:
        error_msg = f"邮件发送失败: {str(e)}"
        logger.error(f"邮件发送失败: {str(e)}")

        # 检查特定的错误情况，如 \x00\x00\x00，这可能表示邮件实际已发送
        if "\\x00\\x00\\x00" in str(e):
            logger.info("邮件可能已成功发送（出现特殊错误码但通常不影响邮件传递）")
            return {"status": "success", "message": "邮件可能已成功发送（出现特殊错误码但通常不影响邮件传递）"}

        return {"status": "error", "message": error_msg}

def get_today_logs():
    """获取今日日志"""
    current_date = datetime.now().strftime("%Y/%m/%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")

    logs = []

    # 检查昨天的日志（如果在0点前后）
    yesterday_log = f'output/logs/{yesterday}.log'
    if os.path.exists(yesterday_log):
        with open(yesterday_log, 'r', encoding='utf-8') as f:
            content = f.read()
            # 只获取最后一天的日志
            logs.extend([line for line in content.splitlines()
                        if line.startswith(datetime.now().strftime("%Y-%m-%d"))])

    # 检查今天的日志
    today_log = f'output/logs/{current_date}.log'
    if os.path.exists(today_log):
        with open(today_log, 'r', encoding='utf-8') as f:
            logs.extend(f.read().splitlines())

    return logs

# 测试代码
if __name__ == '__main__':
    import asyncio

    async def test_send():
        try:
            await send_email(
                subject="测试日志邮件",
                content=None  # 测试发送当天的日志
            )
            print("测试邮件发送成功")
        except Exception as e:
            print(f"测试邮件发送失败: {e}")

    asyncio.run(test_send())
