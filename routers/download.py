import asyncio
import os
import subprocess
import sys
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from scripts.utils import load_config

router = APIRouter()
config = load_config()

class DownloadRequest(BaseModel):
    url: str
    sessdata: Optional[str] = Field(None, description="用户的 SESSDATA")
    download_cover: Optional[bool] = Field(True, description="是否下载视频封面")

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
            # 将错误输出按行分割并发送
            for line in stderr_output.strip().split('\n'):
                yield f"data: ERROR: {line}\n\n"
                await asyncio.sleep(0)
        
        # 发送完成事件
        if return_code == 0:
            yield "data: 下载完成\n\n"
        else:
            # 如果有错误码，发送更详细的错误信息
            yield f"data: 下载失败，错误码: {return_code}\n\n"
            # 尝试获取更多错误信息
            try:
                if process.stderr:
                    process.stderr.seek(0)
                    full_error = process.stderr.read()
                    if full_error:
                        yield f"data: 完整错误信息:\n{full_error}\n\n"
            except Exception as e:
                yield f"data: 无法获取完整错误信息: {str(e)}\n\n"
            
    except Exception as e:
        yield f"data: 处理过程出错: {str(e)}\n\n"
        import traceback
        yield f"data: 错误堆栈:\n{traceback.format_exc()}\n\n"
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
        # 确保下载目录和临时目录存在且有正确的权限
        download_dir = os.path.normpath(config['yutto']['basic']['dir'])
        tmp_dir = os.path.normpath(config['yutto']['basic']['tmp_dir'])
        
        # 创建目录（如果不存在）
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(tmp_dir, exist_ok=True)
        
        # 检查目录权限
        if not os.access(download_dir, os.W_OK):
            raise HTTPException(
                status_code=500,
                detail=f"没有下载目录的写入权限: {download_dir}"
            )
        if not os.access(tmp_dir, os.W_OK):
            raise HTTPException(
                status_code=500,
                detail=f"没有临时目录的写入权限: {tmp_dir}"
            )
        
        command = [
            yutto_path,
            request.url,
            '--dir', download_dir,
            '--tmp-dir', tmp_dir,
            '--subpath-template', '{title}_{username}_{download_date@%Y%m%d_%H%M%S}/{title}',
        ]
        
        # 根据用户选择决定是否下载封面
        if not request.download_cover:
            command.append('--no-cover')
        
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
        elif config.get('SESSDATA'):
            command.extend(['--sessdata', config['SESSDATA']])

        # 设置环境变量
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        env['PYTHONUNBUFFERED'] = '1'  # 确保Python输出不被缓存
        
        # 在Linux上确保PATH包含python环境
        if sys.platform != 'win32':
            env['PATH'] = f"{os.path.dirname(sys.executable)}:{env.get('PATH', '')}"
            # 添加virtualenv的site-packages路径（如果存在）
            site_packages = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), 'lib', 'python*/site-packages')
            env['PYTHONPATH'] = f"{site_packages}:{env.get('PYTHONPATH', '')}"

        # 准备进程参数
        popen_kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'encoding': 'utf-8',
            'errors': 'replace',
            'universal_newlines': True,
            'env': env,
            'bufsize': 1,  # 行缓冲
            'shell': sys.platform != 'win32'  # 在非Windows系统上使用shell
        }
        
        # 在Windows系统上添加CREATE_NO_WINDOW标志
        if sys.platform == 'win32':
            popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            popen_kwargs['shell'] = False  # Windows上不使用shell

        # 在Linux上将命令列表转换为字符串，同时处理特殊字符
        command_str = None
        if sys.platform != 'win32':
            command_str = ' '.join(f"'{arg}'" if ((' ' in arg) or ("'" in arg) or ('"' in arg)) else arg for arg in command)

        try:
            # 执行命令，使用流式输出
            if sys.platform != 'win32':
                # 检查FFmpeg是否安装
                try:
                    ffmpeg_process = subprocess.run(['which', 'ffmpeg'], capture_output=True, text=True)
                    if ffmpeg_process.returncode != 0:
                        print("FFmpeg未安装，需要手动安装...")
                        print(f"which ffmpeg 返回值: {ffmpeg_process.returncode}")
                        print(f"which ffmpeg 输出: {ffmpeg_process.stdout}")
                        print(f"which ffmpeg 错误: {ffmpeg_process.stderr}")
                        
                        # 检测系统类型
                        os_release = ""
                        try:
                            with open('/etc/os-release', 'r') as f:
                                os_release = f.read().lower()
                        except Exception as e:
                            print(f"读取/etc/os-release失败: {str(e)}")
                        
                        # 准备安装指南
                        install_guide = "请按照以下步骤安装FFmpeg:\n\n"
                        
                        if os.path.exists('/etc/centos-release') or 'centos' in os_release:
                            install_guide += "CentOS 7安装步骤:\n\n"
                            install_guide += "1. 安装EPEL仓库:\n"
                            install_guide += "yum install -y epel-release\n\n"
                            install_guide += "2. 安装RPM Fusion仓库:\n"
                            install_guide += "yum localinstall -y --nogpgcheck https://download1.rpmfusion.org/free/el/rpmfusion-free-release-7.noarch.rpm\n\n"
                            install_guide += "3. 安装FFmpeg:\n"
                            install_guide += "yum install -y ffmpeg ffmpeg-devel"
                            
                        elif os.path.exists('/etc/debian_version') or 'ubuntu' in os_release or 'debian' in os_release:
                            install_guide += "Ubuntu/Debian安装步骤:\n"
                            install_guide += "1. 更新包列表:\n"
                            install_guide += "apt-get update\n\n"
                            install_guide += "2. 安装FFmpeg:\n"
                            install_guide += "apt-get install -y ffmpeg"
                            
                        else:
                            install_guide += "未能识别的Linux发行版，请访问FFmpeg官网获取安装指南：\n"
                            install_guide += "https://ffmpeg.org/download.html"
                        
                        raise HTTPException(
                            status_code=500,
                            detail=f"FFmpeg未安装\n\n{install_guide}"
                        )
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"检查FFmpeg失败: {str(e)}\n请确保FFmpeg已正确安装并添加到系统PATH中"
                    )
                
                print(f"\n=== 执行命令 ===")
                print(f"命令: {command_str}")
                print(f"工作目录: {os.getcwd()}")
                print(f"yutto路径: {yutto_path}")
                print(f"yutto是否存在: {os.path.exists(yutto_path)}")
                print(f"yutto是否可执行: {os.access(yutto_path, os.X_OK)}")
                print(f"\n环境变量:")
                for key, value in env.items():
                    print(f"{key}: {value}")
                
                # 检查yutto命令
                try:
                    version_process = subprocess.run(['yutto', '--version'], capture_output=True, text=True)
                    print(f"\nyutto版本信息:")
                    print(version_process.stdout)
                    if version_process.stderr:
                        print(f"yutto版本检查错误: {version_process.stderr}")
                except Exception as e:
                    print(f"检查yutto版本失败: {str(e)}")
                
                process = subprocess.Popen(
                    command_str,
                    **popen_kwargs
                )
            else:
                process = subprocess.Popen(
                    command,
                    **popen_kwargs
                )

            # 返回SSE响应
            return StreamingResponse(
                stream_process_output(process),
                media_type="text/event-stream"
            )
        except Exception as e:
            # 记录详细的错误信息
            error_msg = f"命令执行失败: {str(e)}\n"
            error_msg += f"命令: {command if sys.platform == 'win32' else (command_str if command_str else ' '.join(command))}\n"
            error_msg += f"环境变量:\n"
            error_msg += f"PATH: {env.get('PATH')}\n"
            error_msg += f"PYTHONPATH: {env.get('PYTHONPATH')}\n"
            error_msg += f"下载目录: {download_dir} (可写: {os.access(download_dir, os.W_OK)})\n"
            error_msg += f"临时目录: {tmp_dir} (可写: {os.access(tmp_dir, os.W_OK)})"
            
            # 添加系统信息
            import platform
            error_msg += f"\n\n系统信息:\n"
            error_msg += f"操作系统: {platform.system()} {platform.release()}\n"
            error_msg += f"Python版本: {sys.version}\n"
            error_msg += f"工作目录: {os.getcwd()}\n"
            error_msg += f"yutto路径: {yutto_path}\n"
            error_msg += f"yutto是否存在: {os.path.exists(yutto_path)}\n"
            error_msg += f"yutto是否可执行: {os.access(yutto_path, os.X_OK)}"
            
            # 添加FFmpeg信息
            try:
                ffmpeg_process = subprocess.run(['which', 'ffmpeg'], capture_output=True, text=True)
                error_msg += f"\n\nFFmpeg信息:\n"
                if ffmpeg_process.returncode == 0:
                    ffmpeg_path = ffmpeg_process.stdout.strip()
                    error_msg += f"FFmpeg路径: {ffmpeg_path}\n"
                    # 获取FFmpeg版本
                    version_process = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
                    if version_process.returncode == 0:
                        error_msg += f"FFmpeg版本: {version_process.stdout.splitlines()[0]}\n"
            except Exception as ffmpeg_error:
                error_msg += f"\n\nFFmpeg检查失败: {str(ffmpeg_error)}"
            
            raise HTTPException(
                status_code=500,
                detail=error_msg
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

@router.get("/check_ffmpeg", summary="检查FFmpeg版本")
async def check_ffmpeg():
    """
    检查FFmpeg是否安装及其版本信息
    
    Returns:
        如果安装了FFmpeg，返回版本信息
        如果未安装，返回安装指南
    """
    try:
        # 获取系统信息
        import platform
        system = platform.system().lower()
        release = platform.release()
        os_info = {
            "system": system,
            "release": release,
            "platform": platform.platform()
        }
        
        # 根据不同系统使用不同的命令检查FFmpeg
        if system == 'windows':
            ffmpeg_check_cmd = 'where ffmpeg'
        else:
            ffmpeg_check_cmd = 'which ffmpeg'
            
        # 检查FFmpeg是否安装
        ffmpeg_process = subprocess.run(
            ffmpeg_check_cmd.split(),
            capture_output=True,
            text=True
        )
        
        if ffmpeg_process.returncode == 0:
            # FFmpeg已安装，获取版本信息
            version_process = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
            if version_process.returncode == 0:
                version_info = version_process.stdout.splitlines()[0]
                return {
                    "status": "success",
                    "installed": True,
                    "version": version_info,
                    "path": ffmpeg_process.stdout.strip(),
                    "os_info": os_info
                }
        
        # FFmpeg未安装，准备安装指南
        os_release = ""
        try:
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release', 'r') as f:
                    os_release = f.read().lower()
        except Exception as e:
            print(f"读取/etc/os-release失败: {str(e)}")
        
        install_guide = "请按照以下步骤安装FFmpeg:\n\n"
        
        if system == 'darwin':  # macOS
            install_guide += "macOS安装步骤:\n\n"
            install_guide += "1. 使用Homebrew安装:\n"
            install_guide += "brew install ffmpeg\n\n"
            install_guide += "如果没有安装Homebrew，请先安装Homebrew:\n"
            install_guide += '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            
        elif system == 'linux':
            if os.path.exists('/etc/centos-release') or 'centos' in os_release:
                install_guide += "CentOS 7安装步骤:\n\n"
                install_guide += "1. 安装EPEL仓库:\n"
                install_guide += "yum install -y epel-release\n\n"
                install_guide += "2. 安装RPM Fusion仓库:\n"
                install_guide += "yum localinstall -y --nogpgcheck https://download1.rpmfusion.org/free/el/rpmfusion-free-release-7.noarch.rpm\n\n"
                install_guide += "3. 安装FFmpeg:\n"
                install_guide += "yum install -y ffmpeg ffmpeg-devel"
                
            elif os.path.exists('/etc/debian_version') or 'ubuntu' in os_release or 'debian' in os_release:
                install_guide += "Ubuntu/Debian安装步骤:\n"
                install_guide += "1. 更新包列表:\n"
                install_guide += "apt-get update\n\n"
                install_guide += "2. 安装FFmpeg:\n"
                install_guide += "apt-get install -y ffmpeg"
                
            else:
                install_guide += "未能识别的Linux发行版，请访问FFmpeg官网获取安装指南：\n"
                install_guide += "https://ffmpeg.org/download.html"
                
        elif system == 'windows':
            install_guide += "Windows安装步骤:\n\n"
            install_guide += "1. 使用Scoop安装(推荐):\n"
            install_guide += "scoop install ffmpeg\n\n"
            install_guide += "如果没有安装Scoop，请先安装Scoop:\n"
            install_guide += "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser\n"
            install_guide += 'irm get.scoop.sh | iex\n\n'
            install_guide += "2. 或者访问FFmpeg官网下载可执行文件:\n"
            install_guide += "https://ffmpeg.org/download.html#build-windows"
            
        else:
            install_guide += "未能识别的操作系统，请访问FFmpeg官网获取安装指南：\n"
            install_guide += "https://ffmpeg.org/download.html"
        
        return {
            "status": "error",
            "installed": False,
            "message": "FFmpeg未安装",
            "install_guide": install_guide,
            "os_info": os_info
        }
        
    except Exception as e:
        return {
            "status": "error",
            "installed": False,
            "message": f"检查FFmpeg失败: {str(e)}",
            "error": str(e),
            "os_info": os_info if 'os_info' in locals() else {
                "system": platform.system().lower(),
                "release": platform.release(),
                "platform": platform.platform()
            }
        } 