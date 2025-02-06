import os
import subprocess
import sys
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from scripts.utils import load_config
import requests

router = APIRouter()
config = load_config()

class DownloadRequest(BaseModel):
    url: str
    sessdata: Optional[str] = Field(None, description="用户的 SESSDATA")

async def stream_process_output(process: subprocess.Popen):
    """实时流式输出进程的输出"""
    try:
        # 创建异步迭代器来读取输出
        async def read_output():
            while True:
                line = await asyncio.get_event_loop().run_in_executor(None, process.stdout.readline)
                if not line:
                    break
                yield line.strip()

        # 实时读取并发送标准输出
        async for line in read_output():
            if line:
                yield f"data: {line}\n\n"
                # 立即刷新输出
                await asyncio.sleep(0)
        
        # 等待进程完成
        return_code = await asyncio.get_event_loop().run_in_executor(None, process.wait)
        
        # 读取可能的错误输出
        stderr_output = await asyncio.get_event_loop().run_in_executor(None, process.stderr.read)
        if stderr_output:
            yield f"data: ERROR: {stderr_output.strip()}\n\n"
            await asyncio.sleep(0)
        
        # 发送完成事件
        if return_code == 0:
            yield "data: 下载完成\n\n"
        else:
            yield f"data: 下载失败，错误码: {return_code}\n\n"
            
    except Exception as e:
        yield f"data: 处理过程出错: {str(e)}\n\n"
    finally:
        # 确保进程已结束
        if process.poll() is None:
            process.terminate()
            await asyncio.get_event_loop().run_in_executor(None, process.wait)
        yield "event: close\ndata: close\n\n"

@router.post("/download_video", summary="下载B站视频")
async def download_video(request: DownloadRequest):
    """
    下载B站视频
    
    Args:
        request: 包含视频URL和可选SESSDATA的请求对象
    """
    try:
        # 检查登录状态
        if config['yutto']['basic']['login_strict']:
            sessdata = request.sessdata or config.get('SESSDATA')
            if not sessdata:
                raise HTTPException(
                    status_code=401,
                    detail="未登录：当前设置要求必须登录才能下载视频"
                )
            
            # 验证SESSDATA是否有效
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Cookie': f'SESSDATA={sessdata}'
            }
            
            response = requests.get(
                'https://api.bilibili.com/x/web-interface/nav',
                headers=headers,
                timeout=10
            )
            
            data = response.json()
            if data.get('code') != 0:
                raise HTTPException(
                    status_code=401,
                    detail="登录已失效：请重新登录"
                )
        
        # 获取 yutto 可执行文件路径
        if getattr(sys, 'frozen', False):
            # 如果是打包后的exe运行
            base_path = os.path.dirname(sys.executable)
            paths_to_try = [
                os.path.join(base_path, 'yutto.exe'),  # 尝试主目录
                os.path.join(base_path, '_internal', 'yutto.exe'),  # 尝试 _internal 目录
                os.path.join(os.getcwd(), 'yutto.exe'),  # 尝试当前工作目录
                os.path.join(os.getcwd(), '_internal', 'yutto.exe')  # 尝试当前工作目录的 _internal
            ]
            
            yutto_path = None
            for path in paths_to_try:
                print(f"尝试路径: {path}")
                if os.path.exists(path):
                    yutto_path = path
                    print(f"找到 yutto.exe: {path}")
                    break
            
            if yutto_path is None:
                raise FileNotFoundError(f"找不到 yutto.exe，已尝试的路径: {', '.join(paths_to_try)}")
        else:
            # 如果是直接运行python脚本
            yutto_path = 'yutto'
            print(f"使用命令: {yutto_path}")

        if not os.path.exists(yutto_path) and getattr(sys, 'frozen', False):
            raise FileNotFoundError(f"找不到 yutto.exe，已尝试的路径: {yutto_path}")

        # 构建命令
        command = [
            yutto_path,
            request.url,
            '--dir', config['yutto']['basic']['dir'],
            '--tmp-dir', config['yutto']['basic']['tmp_dir'],
            # 添加路径模板，格式: 视频标题_作者_下载时间
            '--subpath-template', '{title}_{username}_{download_date@%Y%m%d_%H%M%S}/{title}'
        ]
        
        # 添加其他 yutto 配置
        if not config['yutto']['resource']['require_subtitle']:
            command.append('--no-subtitle')
            
        if config['yutto']['danmaku']['font_size']:
            command.extend(['--danmaku-font-size', str(config['yutto']['danmaku']['font_size'])])
            
        if config['yutto']['batch']['with_section']:
            command.append('--with-section')
            
        # 如果提供了SESSDATA，添加到命令中
        if request.sessdata:
            command.extend(['--sessdata', request.sessdata])
        elif config.get('SESSDATA'):  # 使用配置文件中的 SESSDATA
            command.extend(['--sessdata', config['SESSDATA']])

        # 设置环境变量
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        # 执行命令，使用流式输出
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace',
            universal_newlines=True,
            env=env,
            bufsize=1,  # 行缓冲
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        # 返回SSE响应
        return StreamingResponse(
            stream_process_output(process),
            media_type="text/event-stream"
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="找不到 yutto 命令，请确保已正确安装"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"下载过程出错: {str(e)}"
        ) 