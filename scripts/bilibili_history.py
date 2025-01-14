import json
import logging
import os
import time
from datetime import datetime, timedelta
import requests
from scripts.utils import load_config, get_base_path, get_output_path

config = load_config()

def load_cookie():
    """从配置文件读取 SESSDATA"""
    print("\n=== 读取 Cookie 配置 ===")
    print(f"配置内容: {config}")
    sessdata = config.get('SESSDATA', '')
    if not sessdata:
        print("警告: 配置文件中未找到 SESSDATA")
        return ''
    
    # 移除可能存在的引号
    sessdata = sessdata.strip('"')
    if not sessdata:
        print("警告: SESSDATA 为空")
        return ''
        
    print(f"获取到的 SESSDATA: {sessdata}")
    return sessdata

def find_latest_local_history(base_folder='history_by_date'):
    """查找本地最新的历史记录"""
    print("正在查找本地最新的历史记录...")
    full_base_folder = get_output_path(base_folder)  # 使用 get_output_path
    
    print(f"\n=== 查找历史记录 ===")
    print(f"查找路径: {full_base_folder}")
    print(f"路径存在: {os.path.exists(full_base_folder)}")
    
    if not os.path.exists(full_base_folder):
        print("本地历史记录文件夹不存在，将从头开始同步。")
        return None

    latest_date = None
    try:
        latest_year = max([int(year) for year in os.listdir(full_base_folder) if year.isdigit()], default=None)
        if latest_year:
            latest_month = max(
                [int(month) for month in os.listdir(os.path.join(full_base_folder, str(latest_year))) if month.isdigit()],
                default=None
            )
            if latest_month:
                latest_day = max([
                    int(day.split('.')[0]) for day in
                    os.listdir(os.path.join(full_base_folder, str(latest_year), f"{latest_month:02}"))
                    if day.endswith('.json')
                ], default=None)
                if latest_day:
                    latest_file = os.path.join(full_base_folder, str(latest_year), f"{latest_month:02}",
                                             f"{latest_day:02}.json")
                    print(f"找到最新历史记录文件: {latest_file}")
                    with open(latest_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        latest_date = datetime.fromtimestamp(data[-1]['view_at']).date()
    except ValueError:
        print("历史记录目录格式不正确，可能尚未创建任何文件。")

    if latest_date:
        print(f"本地最新的观看日期: {latest_date}")
    return latest_date

def save_history(history_data, base_folder='history_by_date'):
    """保存历史记录"""
    logging.info(f"开始保存{len(history_data)}条新历史记录...")
    full_base_folder = get_output_path(base_folder)
    saved_count = 0

    print(f"\n=== 保存历史记录 ===")
    print(f"保存路径: {full_base_folder}")
    
    for entry in history_data:
        timestamp = entry['view_at']
        dt_object = datetime.fromtimestamp(timestamp)
        year = dt_object.strftime('%Y')
        month = dt_object.strftime('%m')
        day = dt_object.strftime('%d')

        folder_path = os.path.join(full_base_folder, year, month)
        os.makedirs(folder_path, exist_ok=True)

        file_path = os.path.join(folder_path, f"{day}.json")

        existing_oids = set()
        if os.path.exists(file_path):
            try:
                # 尝试不同的编码方式读取
                for encoding in ['utf-8', 'gbk', 'utf-8-sig']:
                    try:
                        with open(file_path, 'r', encoding=encoding) as f:
                            daily_data = json.load(f)
                            existing_oids = {item['history']['oid'] for item in daily_data}
                            break
                    except UnicodeDecodeError:
                        continue
                    except json.JSONDecodeError:
                        continue
            except Exception as e:
                logging.warning(f"警告: 读取文件 {file_path} 失败: {e}，将创建新文件")
                daily_data = []
        else:
            daily_data = []

        if entry['history']['oid'] not in existing_oids:
            daily_data.append(entry)
            existing_oids.add(entry['history']['oid'])
            saved_count += 1

        # 保存时使用 utf-8 编码
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(daily_data, f, ensure_ascii=False, indent=4)
            
    logging.info(f"历史记录保存完成，共保存了{saved_count}条新记录。")
    return {"status": "success", "message": f"历史记录获取成功", "data": history_data}

def fetch_and_compare_history(cookie, latest_date):
    """获取并比较历史记录"""
    print("\n=== API 请求信息 ===")
    print(f"使用的 Cookie: {cookie}")
    
    url = 'https://api.bilibili.com/x/web-interface/history/cursor'
    
    # 添加更多必要的 cookie 字段
    headers = {
        'Cookie': f"SESSDATA={cookie}; buvid3=random_string; b_nut=1234567890; buvid4=random_string",
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://www.bilibili.com',
        'Origin': 'https://www.bilibili.com',
        'Accept': 'application/json, text/plain, */*',
        'Connection': 'keep-alive'
    }
    print(f"请求头: {headers}")
    
    params = {
        'ps': 30,
        'max': '',
        'view_at': '',
        'business': '',
    }
    
    # 测试 API 连接
    response = requests.get(url, headers=headers, params=params)
    print(f"\n=== API 响应信息 ===")
    print(f"状态码: {response.status_code}")
    try:
        response_data = response.json()
        if response_data.get('code') == -101:
            print("Cookie 已失效，请更新 SESSDATA")
            return []
    except:
        print(f"响应内容: {response.text}")
    
    all_new_data = []
    page_count = 0

    if latest_date:
        cutoff_date = latest_date - timedelta(days=1)
        cutoff_timestamp = int(datetime.combine(cutoff_date, datetime.min.time()).timestamp())
        print(f"设置停止条件：view_at <= {cutoff_timestamp} ({cutoff_date})")
    else:
        cutoff_timestamp = 0
        print("没有本地数据，抓取所有可用的历史记录。")

    while True:
        page_count += 1
        print(f"发送请求获取数据... (第{page_count}页)")
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            try:
                data = response.json()
                if data['code'] != 0:
                    print(f"API请求失败，错误码: {data['code']}, 错误信息: {data['message']}")
                    break

                if 'data' in data and 'list' in data['data']:
                    fetched_list = data['data']['list']
                    print(f"获取到{len(fetched_list)}条记录，进行对比...")

                    for entry in fetched_list:
                        print(f"标题: {entry['title']}, 观看时间: {datetime.fromtimestamp(entry['view_at'])}")

                    new_entries = []
                    should_stop = False

                    for entry in fetched_list:
                        view_at = entry['view_at']
                        if view_at > cutoff_timestamp:
                            new_entries.append(entry)
                        else:
                            should_stop = True

                    if new_entries:
                        all_new_data.extend(new_entries)
                        print(f"找到{len(new_entries)}条新记录。")

                    if should_stop:
                        print("达到停止条件，停止请求。")
                        break

                    if 'cursor' in data['data']:
                        current_max = data['data']['cursor']['max']
                        params['max'] = current_max
                        params['view_at'] = data['data']['cursor']['view_at']
                        print(f"请求游标更新：max={params['max']}, view_at={params['view_at']}")
                    else:
                        print("未能获取游标信息，停止请求。")
                        break

                    time.sleep(1)
                else:
                    print("没有更多的数据或数据结构错误。")
                    break

            except json.JSONDecodeError:
                print("JSON Decode Error: 无法解析服务器响应")
                break
        else:
            print(f"请求失败，状态码: {response.status_code}")
            break

    return all_new_data

async def fetch_history(output_dir: str = "history_by_date") -> dict:
    """主函数：获取B站历史记录"""
    try:
        # 修改这里：直接使用 output_dir 而不是拼接 output 路径
        full_output_dir = get_output_path(output_dir)  # 这里 get_output_path 已经会添加 output 前缀
        
        print("\n=== 路径信息 ===")
        print(f"输出目录: {full_output_dir}")
        print(f"目录存在: {os.path.exists(full_output_dir)}")
        
        cookie = config.get('SESSDATA', '')
        if not cookie:
            return {"status": "error", "message": "未找到SESSDATA配置"}

        latest_date = find_latest_local_history(output_dir)  # 传入相对路径
        new_history = fetch_and_compare_history(cookie, latest_date)

        if new_history:
            return save_history(new_history, output_dir)  # 传入相对路径
        else:
            return {"status": "success", "message": "没有新记录需要更新"}

    except Exception as e:
        logging.error(f"获取历史记录时发生错误: {e}")
        return {"status": "error", "message": str(e)}
