import os
import time
import json
import qrcode
import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from loguru import logger
from scripts.utils import load_config, get_output_path, setup_logger
from datetime import datetime
from scripts.send_log_email import send_email

# 确保日志系统已初始化
setup_logger()

router = APIRouter()

def get_current_config():
    """获取当前配置"""
    return load_config()

def save_cookies(cookies):
    """保存cookies到配置文件"""
    try:
        # 使用绝对路径
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.yaml')
        logger.info(f"配置文件路径: {config_path}")

        if not os.path.exists(config_path):
            logger.error(f"配置文件不存在: {config_path}")
            raise HTTPException(
                status_code=500,
                detail="配置文件不存在"
            )

        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = f.read()
            logger.info("成功读取配置文件")

        # 要更新的Cookie字段列表
        cookie_fields = ['SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5']

        lines = config_data.split('\n')
        updated_fields = set()

        # 更新已存在的字段
        for i, line in enumerate(lines):
            for field in cookie_fields:
                if line.strip().startswith(f'{field}:'):
                    if field in cookies:
                        lines[i] = f'{field}: {cookies[field]}'
                        updated_fields.add(field)
                        print(f"更新配置 {field}: {cookies[field]}")
                    break

        # 添加不存在的字段
        for field in cookie_fields:
            if field in cookies and field not in updated_fields:
                lines.append(f'{field}: {cookies[field]}')
                print(f"添加配置 {field}: {cookies[field]}")

        # 保存更新后的配置
        config_data = '\n'.join(lines)
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
        logger.info("开始生成二维码...")

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

        logger.info(f"API响应状态码: {response.status_code}")
        logger.debug(f"API响应内容: {response.text}")

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
            print(f"响应头: {response.headers}")
            print(f"响应Cookies: {response.cookies}")

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

                # 从set-cookie头和响应cookies中提取信息
                cookies = {}

                # 从响应cookie中获取
                for cookie in response.cookies:
                    cookies[cookie.name] = cookie.value
                    print(f"从响应cookies获取到: {cookie.name}={cookie.value}")

                # 从响应头中获取（有些Cookie可能在响应头的set-cookie中，但不在cookies中）
                if 'set-cookie' in response.headers:
                    # 修复: 使用正确的方法获取set-cookie头
                    # CaseInsensitiveDict不支持getlist方法
                    set_cookie_header = response.headers.get('set-cookie', '')
                    print(f"从响应头获取到set-cookie: {set_cookie_header}")

                    # 如果是单个cookie
                    if set_cookie_header:
                        parts = set_cookie_header.split(';')[0].split('=', 1)
                        if len(parts) == 2:
                            name, value = parts
                            cookies[name.strip()] = value.strip()
                            print(f"解析出cookie: {name.strip()}={value.strip()}")

                    # 可能多个cookie在不同的Set-Cookie头中
                    # 遍历所有响应头来查找所有的Set-Cookie
                    for key, value in response.headers.items():
                        if key.lower() == 'set-cookie':
                            cookie_parts = value.split(';')[0].split('=', 1)
                            if len(cookie_parts) == 2:
                                cookie_name, cookie_value = cookie_parts
                                cookies[cookie_name.strip()] = cookie_value.strip()
                                print(f"从头部遍历解析出cookie: {cookie_name.strip()}={cookie_value.strip()}")

                # 如果响应数据中包含cookie_info字段（TV端QR登录模式），从中提取cookies
                if 'cookie_info' in scan_data:
                    cookie_info = scan_data.get('cookie_info', {})
                    for cookie in cookie_info.get('cookies', []):
                        if 'name' in cookie and 'value' in cookie:
                            cookies[cookie['name']] = cookie['value']
                            print(f"从cookie_info获取到: {cookie['name']}={cookie['value']}")

                # 如果必要的cookie不在响应中，从url中解析
                if 'url' in scan_data and scan_data['url'] and ('SESSDATA' not in cookies or 'bili_jct' not in cookies):
                    url = scan_data['url']
                    print(f"从url中解析cookie: {url}")
                    if '?' in url:
                        query = url.split('?', 1)[1]
                        for param in query.split('&'):
                            if '=' in param:
                                name, value = param.split('=', 1)
                                if name in ['DedeUserID', 'DedeUserID__ckMd5', 'SESSDATA', 'bili_jct']:
                                    cookies[name] = value
                                    print(f"从URL解析出cookie: {name}={value}")

                # 记录找到的所有cookie
                print(f"找到的所有cookies: {cookies}")

                # 检查是否有必要的鉴权字段
                if 'SESSDATA' not in cookies:
                    print("警告: 未获取到SESSDATA")

                if 'bili_jct' not in cookies:
                    print("警告: 未获取到bili_jct (CSRF Token)")

                # 保存cookies
                save_cookies(cookies)
                print("cookies已保存")

                # 记录获取到的鉴权信息
                auth_info = {
                    "SESSDATA": cookies.get("SESSDATA", "未获取"),
                    "bili_jct": cookies.get("bili_jct", "未获取"),
                    "DedeUserID": cookies.get("DedeUserID", "未获取"),
                    "DedeUserID__ckMd5": cookies.get("DedeUserID__ckMd5", "未获取")
                }
                print(f"鉴权信息摘要: {auth_info}")

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
        logger.info("开始退出登录...")

        # 使用绝对路径
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.yaml')
        logger.info(f"配置文件路径: {config_path}")

        if not os.path.exists(config_path):
            logger.error(f"配置文件不存在: {config_path}")
            raise HTTPException(
                status_code=500,
                detail="配置文件不存在"
            )

        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = f.read()
            logger.info("成功读取配置文件")

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
                    "code": -101,
                    "message": "未登录",
                    "ttl": 1,
                    "data": None
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

        # 直接返回B站API的原始响应数据
        return JSONResponse(
            status_code=200,
            content=response.json()
        )

    except Exception as e:
        print(f"检查登录状态时发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"检查登录状态失败: {str(e)}"
        )
@router.get("/check-and-notify", summary="检查SESSDATA并在失效时发送邮件")
async def check_and_notify():
    """检查SESSDATA有效性；若失效则发送邮件告警（状态变为失效时仅告警一次）"""
    try:
        print("检查SESSDATA并发送告警（如失效）...")

        # 获取配置与SESSDATA
        current_config = get_current_config()
        sessdata = current_config.get('SESSDATA', '')

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Cookie': f'SESSDATA={sessdata}'
        }

        valid = False
        detail = {}
        error_message = None

        if not sessdata:
            error_message = "SESSDATA 未配置或为空"
        else:
            try:
                resp = requests.get(
                    'https://api.bilibili.com/x/web-interface/nav',
                    headers=headers,
                    timeout=10
                )
                status_code = resp.status_code
                print(f"API响应状态码: {status_code}")
                try:
                    data = resp.json() if status_code == 200 else {}
                except Exception:
                    data = {}
                detail = data

                # code == 0 表示已登录有效
                if status_code == 200 and isinstance(data, dict) and data.get('code') == 0:
                    valid = True
                else:
                    err_msg = ""
                    if isinstance(data, dict):
                        err_msg = data.get('message', '') or (data.get('data', {}) or {}).get('message', '')
                    if not err_msg:
                        err_msg = f"HTTP {status_code}"
                    error_message = f"登录失效或异常: {err_msg}"
            except Exception as e:
                error_message = f"请求验证接口失败: {str(e)}"

        # 状态文件（用于去重，仅在状态从有效->失效时告警一次）
        state_path = get_output_path('state/sessdata_monitor.json')
        last_alert_ts = 0
        last_status = "unknown"
        try:
            if os.path.exists(state_path):
                with open(state_path, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                    last_alert_ts = st.get('last_alert_ts', 0)
                    last_status = st.get('last_status', 'unknown')
        except Exception:
            pass

        now_ts = int(time.time())
        notified = False

        if valid:
            # 更新状态为有效
            try:
                os.makedirs(os.path.dirname(state_path), exist_ok=True)
                with open(state_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'last_status': 'valid',
                        'last_valid_ts': now_ts
                    }, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"写入状态文件失败: {e}")

            return {
                "status": "success",
                "message": "SESSDATA 有效",
                "data": {"valid": True, "detail": detail}
            }

        # 若失效则发送邮件（仅当上次状态不是 invalid 时触发）
        if last_status != 'invalid':
            subject = "B站登录状态失效，请尽快重新登录"
            body = "\n".join([
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"原因: {error_message or '未知'}",
                f"原始返回: {json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else str(detail)}"
            ])

            try:
                send_res = await send_email(subject=subject, content=body)
                print(f"告警邮件发送结果: {send_res}")
                notified = (send_res or {}).get("status") == "success"
            except Exception as e:
                print(f"发送告警邮件失败: {e}")

            # 更新为失效状态
            try:
                os.makedirs(os.path.dirname(state_path), exist_ok=True)
                with open(state_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'last_status': 'invalid',
                        'last_alert_ts': now_ts,
                        'last_error': error_message
                    }, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"写入状态文件失败: {e}")
        else:
            print("状态已为失效，跳过重复告警")

        return {
            "status": "success",
            "message": "SESSDATA 已失效" + ("（已发送邮件）" if notified else "（未重复发送）"),
            "data": {"valid": False, "notified": notified, "detail": detail}
        }

    except Exception as e:
        print(f"检查与告警流程失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"检查与告警流程失败: {str(e)}"
        )