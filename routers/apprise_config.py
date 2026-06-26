from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import yaml
import os
import re

from scripts.utils import load_config
from scripts.apprise_notify import test_apprise_urls

router = APIRouter()


def get_config_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'config', 'config.yaml')


def update_yaml_section(content: str, section: str, data: dict) -> str:
    """更新YAML文件中的整个section"""
    lines = content.split('\n')
    section_indent = '  '

    # 查找section起始位置
    start_idx = -1
    for i, line in enumerate(lines):
        if re.match(rf'^{section}:', line.strip()):
            start_idx = i
            break

    # 构建新section内容
    new_lines = [f'{section}:']
    for key, value in data.items():
        if value is None:
            new_lines.append(f'{section_indent}{key}:')
        elif isinstance(value, list):
            new_lines.append(f'{section_indent}{key}:')
            for item in value:
                new_lines.append(f'{section_indent}  - "{item}"')
        elif isinstance(value, bool):
            new_lines.append(f'{section_indent}{key}: {str(value).lower()}')
        elif isinstance(value, str):
            new_lines.append(f'{section_indent}{key}: "{value}"')
        else:
            new_lines.append(f'{section_indent}{key}: {value}')

    if start_idx == -1:
        if lines and lines[-1].strip() != '':
            lines.append('')
        lines.extend(new_lines)
    else:
        end_idx = start_idx + 1
        while end_idx < len(lines):
            if lines[end_idx].strip() == '' or lines[end_idx].startswith(' '):
                end_idx += 1
            else:
                break
        if end_idx < len(lines) and lines[end_idx].strip() != '':
            new_lines.append('')
        lines = lines[:start_idx] + new_lines + lines[end_idx:]

    return '\n'.join(lines)


class AppriseConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    urls: Optional[str] = None


class AppriseTestRequest(BaseModel):
    urls: str


@router.get("/apprise-config", summary="获取Apprise推送配置")
async def get_apprise_config():
    """获取当前Apprise推送配置"""
    try:
        config = load_config()
        apprise_config = config.get('apprise', {})
        urls = apprise_config.get('urls', [])
        return {
            "enabled": apprise_config.get('enabled', True),
            "urls": '\n'.join(urls) if isinstance(urls, list) else str(urls or '')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取Apprise配置失败: {str(e)}")


@router.post("/apprise-config", summary="更新Apprise推送配置")
async def update_apprise_config(request: AppriseConfigUpdate):
    """更新Apprise推送配置"""
    try:
        config_path = get_config_path()
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()

        config = yaml.safe_load(content) or {}
        apprise_config = config.get('apprise', {})

        if request.enabled is not None:
            apprise_config['enabled'] = request.enabled

        if request.urls is not None:
            urls = [line.strip() for line in request.urls.splitlines() if line.strip()]
            apprise_config['urls'] = urls

        content = update_yaml_section(content, 'apprise', apprise_config)
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return {
            "status": "success",
            "message": "Apprise配置更新成功",
            "config": {
                "enabled": apprise_config.get('enabled', True),
                "urls": '\n'.join(apprise_config.get('urls', []))
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新Apprise配置失败: {str(e)}")


@router.post("/test-apprise", summary="测试Apprise推送")
async def send_test_apprise(request: AppriseTestRequest):
    """测试Apprise推送配置"""
    try:
        urls = [line.strip() for line in request.urls.splitlines() if line.strip()]
        if not urls:
            raise ValueError("请至少填写一个推送地址")

        result = await test_apprise_urls(urls)
        if result['status'] == 'error':
            raise HTTPException(status_code=400, detail=result['message'])
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试推送失败: {str(e)}")
