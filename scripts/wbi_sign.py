import hashlib
import json
import time
import urllib.parse
from typing import Dict, Any

import requests

# 混淆用的字符表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

# 缓存的WBI密钥
_cached_wbi_keys = {
    "img_key": "",
    "sub_key": "",
    "time": 0
}

def get_mixin_key(orig: str) -> str:
    """
    对 imgKey 和 subKey 进行字符顺序打乱编码
    取MIXIN_KEY_ENC_TAB中的前32个字符
    """
    mixed_key = ""
    for i in MIXIN_KEY_ENC_TAB:
        if i < len(orig):
            mixed_key += orig[i]
    return mixed_key[:32]

def fetch_wbi_keys() -> Dict[str, str]:
    """
    获取最新的 WBI 签名密钥
    """
    global _cached_wbi_keys
    
    # 检查缓存是否过期（1小时）
    current_time = int(time.time())
    if _cached_wbi_keys["time"] > 0 and current_time - _cached_wbi_keys["time"] < 3600:
        return {
            "img_key": _cached_wbi_keys["img_key"],
            "sub_key": _cached_wbi_keys["sub_key"]
        }
    
    try:
        # 从配置中读取SESSDATA
        from scripts.utils import load_config
        config = load_config()
        sessdata = config.get('SESSDATA', '')
        
        # 设置请求头，解决412错误，添加Cookie认证
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.bilibili.com/"
        }
        
        # 如果有SESSDATA，添加到Cookie
        if sessdata:
            headers["Cookie"] = f"SESSDATA={sessdata}"
        
        # 从B站首页获取最新的 wbi_img 和 wbi_sub
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/nav", 
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        json_content = resp.json()
        
        if json_content["code"] != 0:
            raise Exception(f"获取WBI密钥失败: {json_content['message']}")
        
        img_url = json_content["data"]["wbi_img"]["img_url"]
        sub_url = json_content["data"]["wbi_img"]["sub_url"]
        
        img_key = img_url.split("/")[-1].split(".")[0]
        sub_key = sub_url.split("/")[-1].split(".")[0]
        
        # 更新缓存
        _cached_wbi_keys = {
            "img_key": img_key,
            "sub_key": sub_key,
            "time": current_time
        }
        
        return {
            "img_key": img_key,
            "sub_key": sub_key
        }
    except Exception as e:
        print(f"获取WBI密钥时出错: {e}")
        # 如果有缓存，返回缓存的密钥
        if _cached_wbi_keys["img_key"] and _cached_wbi_keys["sub_key"]:
            return {
                "img_key": _cached_wbi_keys["img_key"],
                "sub_key": _cached_wbi_keys["sub_key"]
            }
        # 否则返回空值
        return {"img_key": "", "sub_key": ""}

def get_wbi_sign(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    对参数进行 WBI 签名
    """
    # 获取 WBI 密钥
    keys = fetch_wbi_keys()
    img_key, sub_key = keys["img_key"], keys["sub_key"]
    
    # 如果获取密钥失败，返回原始参数
    if not img_key or not sub_key:
        print("获取WBI密钥失败，返回未签名的参数")
        return params
    
    # 返回签名后的参数
    return enc_wbi(params, img_key, sub_key)

def enc_wbi(params: Dict[str, Any], img_key: str, sub_key: str) -> Dict[str, Any]:
    """
    为请求参数进行 wbi 签名
    """
    # 合并密钥并进行混淆
    mixin_key = get_mixin_key(img_key + sub_key)
    
    # 添加 wts 参数（当前时间戳）
    params_with_wts = dict(params)
    curr_time = int(time.time())
    params_with_wts["wts"] = curr_time
    
    # 按照参数名排序
    params_sorted = dict(sorted(params_with_wts.items()))
    
    # 过滤 value 中的 "!'()*" 字符
    filtered_params = {}
    for k, v in params_sorted.items():
        filtered_value = str(v)
        for char in "!'()*":
            filtered_value = filtered_value.replace(char, '')
        filtered_params[k] = filtered_value
    
    # 构造待签名的字符串
    query = urllib.parse.urlencode(filtered_params)
    
    # 计算 w_rid
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    
    # 添加签名参数
    result_params = dict(params)
    result_params["wts"] = curr_time
    result_params["w_rid"] = w_rid
    
    return result_params

# 测试函数
if __name__ == "__main__":
    # 测试参数
    test_params = {
        "bvid": "BV1L94y1H7CV",
        "cid": 1335073288,
        "up_mid": 297242063
    }
    
    # 获取签名后的参数
    signed_params = get_wbi_sign(test_params)
    
    print("原始参数:", test_params)
    print("签名后的参数:", signed_params)
    
    # 测试请求
    url = "https://api.bilibili.com/x/web-interface/view/conclusion/get"
    
    # 添加请求头
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.bilibili.com/"
    }
    
    response = requests.get(url, params=signed_params, headers=headers)
    
    print("\n请求URL:", response.url)
    print("响应状态码:", response.status_code)
    
    try:
        data = response.json()
        print("响应内容:", json.dumps(data, ensure_ascii=False, indent=2))
    except:
        print("响应内容解析失败:", response.text) 