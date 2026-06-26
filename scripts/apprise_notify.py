import asyncio
from typing import Dict, Optional
from loguru import logger

try:
    import apprise
except ImportError:
    apprise = None

from scripts.utils import load_config


def _get_apprise_config() -> dict:
    """从配置文件读取 Apprise 配置"""
    config = load_config()
    return config.get('apprise', {})


def _get_apprise_urls() -> list[str]:
    """获取启用的 Apprise URL 列表"""
    apprise_config = _get_apprise_config()
    if not apprise_config.get('enabled', False):
        return []
    urls = apprise_config.get('urls', [])
    return [str(u).strip() for u in urls if str(u).strip()]


async def send_apprise_notification(
    title: str,
    body: str,
    urls: Optional[list[str]] = None
) -> Dict:
    """
    通过 Apprise 发送通知

    Args:
        title: 通知标题
        body: 通知内容
        urls: 可选，直接指定URL列表（用于测试）

    Returns:
        {
            "status": "success"|"partial"|"error"|"skipped",
            "message": "...",
            "summary": {"total": 0, "success": 0, "failed": 0},
            "results": []
        }
    """
    target_urls = urls or _get_apprise_urls()

    if not target_urls:
        return {
            "status": "skipped",
            "message": "未配置Apprise推送地址",
            "summary": {"total": 0, "success": 0, "failed": 0},
            "results": []
        }

    if apprise is None:
        return {
            "status": "error",
            "message": "未安装apprise库，请运行: pip install apprise",
            "summary": {"total": len(target_urls), "success": 0, "failed": len(target_urls)},
            "results": []
        }

    def _notify_one(url: str) -> Dict:
        notifier = apprise.Apprise()
        notifier.add(url)
        try:
            success = bool(notifier.notify(title=title, body=body))
            return {
                "url": url,
                "status": "success" if success else "error",
                "message": "发送成功" if success else "发送失败，请检查地址是否正确"
            }
        except Exception as e:
            return {
                "url": url,
                "status": "error",
                "message": f"发送异常: {str(e)}"
            }

    try:
        logger.info(f"Apprise 开始发送，共 {len(target_urls)} 个地址")
        results = []
        success_count = 0
        failed_count = 0

        for url in target_urls:
            result = await asyncio.to_thread(_notify_one, url)
            results.append(result)
            if result['status'] == 'success':
                success_count += 1
                logger.info(f"Apprise 推送成功: {url}")
            else:
                failed_count += 1
                logger.warning(f"Apprise 推送失败: {url} - {result['message']}")

        total = len(results)
        summary = {"total": total, "success": success_count, "failed": failed_count}

        if success_count == total:
            status = "success"
            message = f"Apprise推送发送成功（{success_count}/{total}）"
        elif success_count > 0:
            status = "partial"
            message = f"Apprise推送部分成功（成功 {success_count} 条，失败 {failed_count} 条）"
        else:
            status = "error"
            message = "Apprise推送全部失败，请检查地址是否正确"

        logger.info(f"Apprise 发送结果: 成功 {success_count} 条，失败 {failed_count} 条")
        return {
            "status": status,
            "message": message,
            "summary": summary,
            "results": results
        }
    except Exception as e:
        logger.exception(f"Apprise 推送异常: {str(e)}")
        return {
            "status": "error",
            "message": f"Apprise推送异常: {str(e)}",
            "summary": {"total": len(target_urls), "success": 0, "failed": len(target_urls)},
            "results": []
        }


async def test_apprise_urls(urls: list[str]) -> Dict:
    """测试指定的Apprise URL列表"""
    return await send_apprise_notification(
        title="Bilibili历史记录 - 测试推送",
        body="这是一条测试通知，用于验证Apprise配置是否有效。",
        urls=urls
    )
