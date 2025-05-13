import logging
import os
from typing import Optional

import yaml
from fastapi import APIRouter, Header
from pydantic import BaseModel

from scripts.utils import load_config, get_config_path

router = APIRouter()
logger = logging.getLogger(__name__)

class ApiKeyResponse(BaseModel):
    """API密钥验证响应模型"""
    is_valid: bool
    message: str

class ApiKeyUpdateRequest(BaseModel):
    """API密钥更新请求模型"""
    api_key: str

class ApiKeyUpdateResponse(BaseModel):
    """API密钥更新响应模型"""
    success: bool
    message: str

class ApiKeyVerifyAndUpdateRequest(BaseModel):
    """验证当前密钥并更新为新密钥的请求模型"""
    current_api_key: str
    new_api_key: str

@router.get("/check", response_model=ApiKeyResponse, summary="验证API密钥")
async def check_api_key(x_api_key: Optional[str] = Header(None)):
    """
    验证API密钥是否有效

    Args:
        x_api_key: 请求头中的API密钥

    Returns:
        包含验证结果的响应对象
    """
    # 加载配置
    config = load_config()
    api_security = config.get('server', {}).get('api_security', {})

    # 检查API安全是否启用
    if not api_security.get('enabled', False):
        return ApiKeyResponse(
            is_valid=True,
            message="API安全验证未启用"
        )

    # 获取配置中的API密钥
    expected_api_key = api_security.get('api_key', '')

    # 如果没有设置API密钥，返回错误
    if not expected_api_key:
        return ApiKeyResponse(
            is_valid=False,
            message="服务器未配置API密钥"
        )

    # 检查是否使用默认API密钥
    DEFAULT_API_KEY = 'your-secret-api-key-change-this'
    if expected_api_key == DEFAULT_API_KEY:
        return ApiKeyResponse(
            is_valid=False,
            message=f"服务器正在使用默认API密钥: {DEFAULT_API_KEY}"
        )

    # 如果没有提供API密钥，返回错误
    if not x_api_key:
        return ApiKeyResponse(
            is_valid=False,
            message="未提供API密钥"
        )

    # 验证API密钥
    if x_api_key != expected_api_key:
        return ApiKeyResponse(
            is_valid=False,
            message="API密钥无效，请使用正确的API密钥"
        )

    # API密钥有效
    return ApiKeyResponse(
        is_valid=True,
        message="API密钥有效"
    )

@router.post("/update_key", response_model=ApiKeyUpdateResponse, summary="更新API密钥")
async def update_api_key(request: ApiKeyUpdateRequest):
    """
    更新配置文件中的API密钥

    Args:
        request: 包含新API密钥的请求对象

    Returns:
        包含更新结果的响应对象
    """
    try:
        # 获取配置文件路径（使用utils.py中的方法，保持路径一致性）
        config_path = get_config_path('config.yaml')
        logger.info(f"更新API密钥，使用配置文件路径: {config_path}")

        # 检查配置文件是否存在
        if not os.path.exists(config_path):
            logger.error(f"配置文件不存在: {config_path}")
            return ApiKeyUpdateResponse(
                success=False,
                message="配置文件不存在"
            )

        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()

        # 解析YAML
        config = yaml.safe_load(config_content)

        # 检查API安全配置是否存在
        if 'server' not in config:
            config['server'] = {}
        if 'api_security' not in config['server']:
            config['server']['api_security'] = {
                'enabled': True,
                'api_key': '',
                'excluded_paths': ['/health', '/login', '/api/security']
            }

        # 获取当前API密钥
        current_api_key = config['server']['api_security'].get('api_key', '')

        # 如果新API密钥与当前API密钥相同，则不需要更新
        if current_api_key == request.api_key:
            return ApiKeyUpdateResponse(
                success=True,
                message="API密钥未更改"
            )

        # 读取配置文件的所有行
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 查找并更新API密钥行
        api_key_updated = False
        for i, line in enumerate(lines):
            if 'api_key:' in line:
                # 保留缩进和注释
                indent = line[:line.find('api_key:')]
                comment = line[line.find('#'):] if '#' in line else ''

                # 更新API密钥，确保使用引号
                lines[i] = f'{indent}api_key: "{request.api_key}"{comment}\n'
                api_key_updated = True
                break

        # 如果没有找到API密钥行，但配置中有API密钥，则添加API密钥行
        if not api_key_updated and 'api_security' in str(lines):
            for i, line in enumerate(lines):
                if 'api_security:' in line:
                    # 找到api_security部分，在下一行添加api_key
                    indent = line[:line.find('api_security:')] + '  '  # 增加缩进
                    lines.insert(i + 1, f'{indent}api_key: "{request.api_key}"\n')
                    api_key_updated = True
                    break

        # 如果仍然没有更新成功，则使用简单的字符串替换
        if not api_key_updated:
            # 更新API密钥（保留引号格式）
            new_content = config_content.replace(
                f'api_key: "{current_api_key}"',
                f'api_key: "{request.api_key}"'
            )

            # 如果没有找到带引号的格式，尝试不带引号的格式
            if new_content == config_content:
                new_content = config_content.replace(
                    f"api_key: {current_api_key}",
                    f'api_key: "{request.api_key}"'
                )

            # 写入配置文件
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        else:
            # 写入更新后的行
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

        logger.info(f"API密钥已更新")

        return ApiKeyUpdateResponse(
            success=True,
            message="API密钥已更新"
        )
    except Exception as e:
        logger.error(f"更新API密钥时出错: {str(e)}")
        return ApiKeyUpdateResponse(
            success=False,
            message=f"更新API密钥时出错: {str(e)}"
        )

@router.post("/verify_and_update", response_model=ApiKeyUpdateResponse, summary="验证当前密钥并更新为新密钥")
async def verify_and_update_api_key(request: ApiKeyVerifyAndUpdateRequest):
    """
    验证当前API密钥并更新为新密钥

    Args:
        request: 包含当前API密钥和新API密钥的请求对象

    Returns:
        包含更新结果的响应对象
    """
    try:
        # 加载配置
        config = load_config()
        api_security = config.get('server', {}).get('api_security', {})

        # 检查API安全是否启用
        if not api_security.get('enabled', False):
            return ApiKeyUpdateResponse(
                success=False,
                message="API安全验证未启用，无需更新密钥"
            )

        # 获取配置中的API密钥
        expected_api_key = api_security.get('api_key', '')

        # 如果没有设置API密钥，返回错误
        if not expected_api_key:
            return ApiKeyUpdateResponse(
                success=False,
                message="服务器未配置API密钥"
            )

        # 验证当前API密钥
        if request.current_api_key != expected_api_key:
            return ApiKeyUpdateResponse(
                success=False,
                message="当前API密钥验证失败，无法更新"
            )

        # 如果新API密钥与当前API密钥相同，则不需要更新
        if request.new_api_key == expected_api_key:
            return ApiKeyUpdateResponse(
                success=True,
                message="新API密钥与当前API密钥相同，无需更新"
            )

        # 获取配置文件路径（使用utils.py中的方法，保持路径一致性）
        config_path = get_config_path('config.yaml')
        logger.info(f"验证并更新API密钥，使用配置文件路径: {config_path}")

        # 检查配置文件是否存在
        if not os.path.exists(config_path):
            logger.error(f"配置文件不存在: {config_path}")
            return ApiKeyUpdateResponse(
                success=False,
                message="配置文件不存在"
            )

        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()

        # 读取配置文件的所有行
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 查找并更新API密钥行
        api_key_updated = False
        for i, line in enumerate(lines):
            if 'api_key:' in line:
                # 保留缩进和注释
                indent = line[:line.find('api_key:')]
                comment = line[line.find('#'):] if '#' in line else ''

                # 更新API密钥，确保使用引号
                lines[i] = f'{indent}api_key: "{request.new_api_key}"{comment}\n'
                api_key_updated = True
                break

        # 如果没有找到API密钥行，但配置中有API密钥，则添加API密钥行
        if not api_key_updated and 'api_security' in str(lines):
            for i, line in enumerate(lines):
                if 'api_security:' in line:
                    # 找到api_security部分，在下一行添加api_key
                    indent = line[:line.find('api_security:')] + '  '  # 增加缩进
                    lines.insert(i + 1, f'{indent}api_key: "{request.new_api_key}"\n')
                    api_key_updated = True
                    break

        # 如果仍然没有更新成功，则使用简单的字符串替换
        if not api_key_updated:
            # 更新API密钥（保留引号格式）
            new_content = config_content.replace(
                f'api_key: "{expected_api_key}"',
                f'api_key: "{request.new_api_key}"'
            )

            # 如果没有找到带引号的格式，尝试不带引号的格式
            if new_content == config_content:
                new_content = config_content.replace(
                    f"api_key: {expected_api_key}",
                    f'api_key: "{request.new_api_key}"'
                )

            # 写入配置文件
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        else:
            # 写入更新后的行
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

        logger.info(f"API密钥已验证并更新")

        return ApiKeyUpdateResponse(
            success=True,
            message="API密钥已验证并更新"
        )
    except Exception as e:
        logger.error(f"验证并更新API密钥时出错: {str(e)}")
        return ApiKeyUpdateResponse(
            success=False,
            message=f"验证并更新API密钥时出错: {str(e)}"
        )
