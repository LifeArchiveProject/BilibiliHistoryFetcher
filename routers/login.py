import os
import time
import json
import qrcode
import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from scripts.utils import load_config, get_output_path

router = APIRouter()

def get_current_config():
    """获取当前配置"""
    return load_config()

def save_cookies(cookies):
    """保存cookies到配置文件"""
    try:
        # 使用绝对路径
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.yaml')
        print(f"配置文件路径: {config_path}")
        
        if not os.path.exists(config_path):
            print(f"配置文件不存在: {config_path}")
            raise HTTPException(
                status_code=500,
                detail="配置文件不存在"
            )
        
        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = f.read()
            print("成功读取配置文件")
        
        # 更新SESSDATA
        if 'SESSDATA' in cookies:
            print(f"准备更新SESSDATA: {cookies['SESSDATA']}")
            if 'SESSDATA:' in config_data:
                # 替换现有的SESSDATA
                lines = config_data.split('\n')
                for i, line in enumerate(lines):
                    if line.strip().startswith('SESSDATA:'):
                        lines[i] = f'SESSDATA: {cookies["SESSDATA"]}'
                        break
                config_data = '\n'.join(lines)
            else:
                # 添加新的SESSDATA
                config_data += f'\nSESSDATA: {cookies["SESSDATA"]}'
        
        # 保存更新后的配置
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_data)
            print("配置文件已更新")
            
    except Exception as e:
        print(f"保存cookies时发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"保存cookies失败: {str(e)}"
        )

@router.get("/qrcode/generate", summary="生成B站登录二维码")
async def generate_qrcode():
    """生成二维码登录的URL和密钥"""
    try:
        print("开始生成二维码...")
        
        # 设置请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # 调用B站API获取二维码URL
        response = requests.get(
            'https://passport.bilibili.com/x/passport-login/web/qrcode/generate',
            headers=headers,
            timeout=10  # 添加超时设置
        )
        
        print(f"API响应状态码: {response.status_code}")
        print(f"API响应内容: {response.text}")
        
        # 检查响应状态码
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"B站API请求失败: {response.text}"
            )
        
        # 尝试解析JSON响应
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {str(e)}")
            print(f"响应内容: {response.text}")
            raise HTTPException(
                status_code=500,
                detail=f"解析B站API响应失败: {str(e)}"
            )
        
        if data.get('code') != 0:
            raise HTTPException(
                status_code=400,
                detail=f"B站API返回错误: {data.get('message', '未知错误')}"
            )
        
        # 确保返回的数据包含必要的字段
        if 'data' not in data or 'url' not in data['data'] or 'qrcode_key' not in data['data']:
            raise HTTPException(
                status_code=500,
                detail="B站API返回的数据格式不正确"
            )
        
        print("成功获取二维码URL和密钥")
        
        # 生成二维码图片
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data['data']['url'])
        qr.make(fit=True)
        
        # 保存二维码图片
        img = qr.make_image(fill_color="black", back_color="white")
        qr_path = get_output_path('temp/qrcode.png')
        os.makedirs(os.path.dirname(qr_path), exist_ok=True)
        img.save(qr_path)
        
        print("二维码图片已生成")
        
        return {
            "status": "success",
            "data": {
                "qrcode_key": data['data']['qrcode_key'],
                "url": data['data']['url']
            }
        }
    except requests.RequestException as e:
        print(f"网络请求错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"网络请求失败: {str(e)}"
        )
    except Exception as e:
        print(f"发生未知错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"生成二维码失败: {str(e)}"
        )

@router.get("/qrcode/image", summary="获取登录二维码图片")
async def get_qrcode_image():
    """获取生成的二维码图片"""
    try:
        print("尝试获取二维码图片...")
        qr_path = get_output_path('temp/qrcode.png')
        
        if not os.path.exists(qr_path):
            print(f"二维码图片不存在: {qr_path}")
            raise HTTPException(
                status_code=404, 
                detail="二维码图片不存在，请先调用 /login/qrcode/generate 接口生成二维码"
            )
            
        print(f"成功找到二维码图片: {qr_path}")
        return FileResponse(
            qr_path,
            media_type="image/png",
            filename="qrcode.png"
        )
    except Exception as e:
        print(f"获取二维码图片时发生错误: {str(e)}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500,
            detail=f"获取二维码图片失败: {str(e)}"
        )

@router.get("/qrcode/poll", summary="轮询二维码扫描状态")
async def poll_scan_status(qrcode_key: str):
    """轮询扫码状态"""
    try:
        print(f"开始轮询扫码状态，qrcode_key: {qrcode_key}")
        
        if not qrcode_key:
            raise HTTPException(
                status_code=400,
                detail="缺少必要的qrcode_key参数"
            )
        
        # 设置请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # 调用B站API检查扫码状态
        try:
            response = requests.get(
                'https://passport.bilibili.com/x/passport-login/web/qrcode/poll',
                params={'qrcode_key': qrcode_key},
                headers=headers,
                timeout=10
            )
            
            print(f"API响应状态码: {response.status_code}")
            print(f"API响应内容: {response.text}")
            
            # 检查响应状态码
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"B站API请求失败: {response.text}"
                )
            
            # 尝试解析JSON响应
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                print(f"JSON解析错误: {str(e)}")
                print(f"响应内容: {response.text}")
                raise HTTPException(
                    status_code=500,
                    detail=f"解析B站API响应失败: {str(e)}"
                )
            
            # 检查API返回的code
            if data.get('code') != 0:
                error_message = data.get('message', '未知错误')
                print(f"B站API返回错误: {error_message}")
                return {
                    "status": "error",
                    "data": {
                        "code": data.get('code'),
                        "message": error_message,
                        "timestamp": int(time.time())
                    }
                }
            
            scan_data = data.get('data', {})
            print(f"扫码状态数据: {scan_data}")
            
            # 如果登录成功，保存cookies
            if scan_data.get('code') == 0:
                print("登录成功，保存cookies...")
                cookies = {}
                for cookie in response.cookies:
                    cookies[cookie.name] = cookie.value
                    print(f"获取到cookie: {cookie.name}={cookie.value}")
                save_cookies(cookies)
                print("cookies已保存")
            
            return {
                "status": "success",
                "data": {
                    "code": scan_data.get('code', 86101),  # 默认未扫码
                    "message": scan_data.get('message', '等待扫码'),
                    "timestamp": int(time.time())
                }
            }
            
        except requests.RequestException as e:
            print(f"请求B站API时发生错误: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"网络请求失败: {str(e)}"
            )
            
    except Exception as e:
        print(f"发生未知错误: {str(e)}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500,
            detail=f"轮询扫码状态失败: {str(e)}"
        )

@router.post("/logout", summary="退出登录")
async def logout():
    """退出登录，清空SESSDATA"""
    try:
        print("开始退出登录...")
        
        # 使用绝对路径
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.yaml')
        print(f"配置文件路径: {config_path}")
        
        if not os.path.exists(config_path):
            print(f"配置文件不存在: {config_path}")
            raise HTTPException(
                status_code=500,
                detail="配置文件不存在"
            )
        
        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = f.read()
            print("成功读取配置文件")
        
        # 清空SESSDATA
        lines = config_data.split('\n')
        new_lines = []
        for line in lines:
            if line.strip().startswith('SESSDATA:'):
                new_lines.append('SESSDATA: ""')
            else:
                new_lines.append(line)
        
        new_config = '\n'.join(new_lines)
        
        # 保存更新后的配置
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_config)
            print("SESSDATA已清空")
        
        return {
            "status": "success",
            "message": "已成功退出登录"
        }
            
    except Exception as e:
        print(f"退出登录时发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"退出登录失败: {str(e)}"
        )

@router.get("/check", summary="检查登录状态")
async def check_login_status():
    """检查当前登录状态"""
    try:
        print("检查登录状态...")
        
        # 每次检查时重新加载配置
        current_config = get_current_config()
        
        # 从配置文件中获取SESSDATA
        if not current_config.get('SESSDATA'):
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "data": {
                        "is_logged_in": False,
                        "message": "未登录"
                    }
                }
            )
        
        # 设置请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Cookie': f'SESSDATA={current_config["SESSDATA"]}'
        }
        
        # 调用B站API验证登录状态
        response = requests.get(
            'https://api.bilibili.com/x/web-interface/nav',
            headers=headers,
            timeout=10
        )
        
        print(f"API响应状态码: {response.status_code}")
        print(f"API响应内容: {response.text}")
        
        data = response.json()
        
        if data.get('code') != 0:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "data": {
                        "is_logged_in": False,
                        "message": "登录已失效"
                    }
                }
            )
        
        user_data = data.get('data', {})
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": {
                    "is_logged_in": True,
                    "message": "已登录",
                    "user_info": {
                        "uid": user_data.get('mid'),
                        "uname": user_data.get('uname'),
                        "level": user_data.get('level_info', {}).get('current_level')
                    }
                }
            }
        )
        
    except Exception as e:
        print(f"检查登录状态时发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"检查登录状态失败: {str(e)}"
        ) 