from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from scripts.utils import load_config
import logging

logger = logging.getLogger(__name__)

class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    API密钥验证中间件

    验证请求中的API密钥是否有效，如果无效则拒绝请求
    """

    def __init__(self, app):
        super().__init__(app)
        self.config = load_config()
        self.api_security = self.config.get('server', {}).get('api_security', {})
        self.enabled = self.api_security.get('enabled', False)
        self.api_key = self.api_security.get('api_key', '')
        self.excluded_paths = self.api_security.get('excluded_paths', [])

        # 记录中间件初始化状态
        if self.enabled:
            logger.info(f"API密钥验证已启用")
            logger.info(f"排除路径: {', '.join(self.excluded_paths)}")
        else:
            logger.info(f"API密钥验证未启用")

    async def dispatch(self, request: Request, call_next):
        """
        处理请求并验证API密钥

        Args:
            request: 请求对象
            call_next: 下一个处理函数

        Returns:
            响应对象
        """
        # 每次请求时重新加载配置，确保使用最新的API密钥
        try:
            config = load_config()
            api_security = config.get('server', {}).get('api_security', {})
            enabled = api_security.get('enabled', False)
            api_key = api_security.get('api_key', '')
            excluded_paths = api_security.get('excluded_paths', [])
        except Exception as e:
            logger.error(f"重新加载配置失败: {str(e)}")
            # 如果重新加载失败，使用初始化时的配置
            enabled = self.enabled
            api_key = self.api_key
            excluded_paths = self.excluded_paths

        # 如果API密钥验证未启用，直接处理请求
        if not enabled:
            return await call_next(request)

        # 检查请求路径是否在排除列表中
        path = request.url.path

        # FastAPI文档路径白名单
        fastapi_docs_paths = ['/docs', '/redoc', '/openapi.json']

        # 检查是否是FastAPI文档路径
        if path in fastapi_docs_paths:
            return await call_next(request)

        # 检查是否在配置的排除路径中
        for excluded_path in excluded_paths:
            if path.startswith(excluded_path):
                return await call_next(request)

        # 始终允许OPTIONS请求通过（用于CORS预检）
        if request.method == "OPTIONS":
            return await call_next(request)

        # 检查是否是内部调用
        is_internal_call = request.headers.get('X-Internal-Call') == 'true'
        if is_internal_call:
            logger.info(f"检测到内部调用请求，路径: {path}")
            return await call_next(request)
            
        # 检查请求的Accept头是否包含text/event-stream（SSE请求）
        accept_header = request.headers.get('Accept', '')
        if 'text/event-stream' in accept_header:
            logger.info(f"检测到SSE请求，自动放行，路径: {path}")
            return await call_next(request)

        # 从请求头中获取API密钥
        request_api_key = request.headers.get('X-API-Key')

        # 如果没有提供API密钥或API密钥无效，返回401错误
        if not request_api_key or request_api_key != api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "code": 401,
                    "message": "未授权：无效的API密钥",
                    "detail": "请提供有效的API密钥"
                }
            )

        # API密钥有效，继续处理请求
        return await call_next(request)
