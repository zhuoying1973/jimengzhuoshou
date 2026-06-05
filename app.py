from flask import Flask, request, jsonify
import urllib.request
import urllib.parse
import json
import re
import ssl
import socket
import os
import sys

app = Flask(__name__)

# 支持跨域响应（CORS），保证局域网其他设备能够顺利进行解析和代理下载
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# 强制忽略系统全局代理配置，防止发送到国内即梦网站的请求走海外代理导致被阻断/挂起
proxy_support = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(proxy_support)
urllib.request.install_opener(opener)

# 绕过全局 SSL 证书验证，防止某些本地网络环境下请求 HTTPS 报错
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 获取本机局域网 IP，供手机连接时使用
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# 1. 核心接口：单链接解析与自动建档
@app.route('/api/parse', methods=['POST'])
def parse_link():
    data = request.json or {}
    raw_text = data.get("url", "").strip()
    
    if not raw_text:
        return jsonify({"code": -1, "msg": "请输入链接"}), 400
        
    # A. 优先检测是否直接输入了创作者 sec_uid
    sec_uid_direct = re.search(r'MS4wLjABAAAA[a-zA-Z0-9_\-]+', raw_text)
    if sec_uid_direct:
        sec_uid = sec_uid_direct.group(0)
        print(f"直接匹配作者 ID (sec_uid): {sec_uid}")
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
        cache_path = os.path.join(cache_dir, "parsed_authors_cache.json")
        cache_data = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            except Exception:
                pass
        
        author_info = cache_data.get(sec_uid, {})
        author_name = author_info.get("author_name", "未知创作者")
        author_avatar = author_info.get("author_avatar", "")
        
        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "is_author_only": True,
                "sec_uid": sec_uid,
                "author": author_name,
                "avatar": author_avatar
            }
        })
        
    # B. 正则提取文本中的 URL 链接
    url_match = re.search(r'https?://[^\s]+', raw_text)
    if not url_match:
        return jsonify({"code": -1, "msg": "未在输入中找到有效的网址链接或作者ID"}), 400
        
    url = url_match.group(0)
    print(f"收到解析请求: {url}")
    
    # 第一步：追踪短链接重定向，获取真实 URL
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        req_redirect = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req_redirect, context=ctx, timeout=10) as resp:
            final_url = resp.geturl()
            
        print(f"重定向至真实地址: {final_url}")
        
        # 1. 尝试从真实 URL 中正则提取 id=xxxx 的数字
        id_match = re.search(r'id=(\d+)', final_url)
        # 2. 尝试从真实 URL 中正则提取 sec_uid=xxx 的作者 ID
        sec_uid_match = re.search(r'sec_uid=([a-zA-Z0-9_\-]+)', final_url)
        
        if not id_match and not sec_uid_match:
            return jsonify({"code": -1, "msg": "无法从链接中解析出作品 ID 或作者 ID，请确认是即梦APP生成的链接"}), 400
            
        # 如果是纯作者主页链接
        if not id_match and sec_uid_match:
            sec_uid = sec_uid_match.group(1)
            print(f"解析到作者主页，提取 sec_uid: {sec_uid}")
            cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
            cache_path = os.path.join(cache_dir, "parsed_authors_cache.json")
            cache_data = {}
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        cache_data = json.load(f)
                except Exception:
                    pass
            
            # 若数据库中没有这位新收录作者，为其初始化初始空档案，使其能直接展示在顶部名录中
            if sec_uid not in cache_data:
                cache_data[sec_uid] = {
                    "author_name": "新收录创作者",
                    "author_avatar": "",
                    "works": []
                }
                try:
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(cache_data, f, ensure_ascii=False, indent=2)
                    print(f"成功为全新创作者 {sec_uid} 建立初始本地缓存档案。")
                except Exception as e:
                    print(f"保存新作者初始缓存失败: {e}")
            
            author_info = cache_data.get(sec_uid, {})
            author_name = author_info.get("author_name", "新收录创作者")
            author_avatar = author_info.get("author_avatar", "")
            
            return jsonify({
                "code": 0,
                "msg": "success",
                "data": {
                    "is_author_only": True,
                    "sec_uid": sec_uid,
                    "author": author_name,
                    "avatar": author_avatar
                }
            })
            
        published_item_id = id_match.group(1)
        print(f"提取作品 ID: {published_item_id}")
    except Exception as e:
        return jsonify({"code": -1, "msg": f"解析重定向失败: {str(e)}"}), 500
        
    # 第二步：调用即梦官方后台 POST 接口拉取作品元数据
    api_url = "https://jimeng.jianying.com/mweb/v1/get_item_info"
    payload = {
        "published_item_id": published_item_id
    }
    
    # 伪装手机端以保障接口能够稳定返回元数据
    headers_api = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Referer': f'https://jimeng.jianying.com/detail?id={published_item_id}',
        'Origin': 'https://jimeng.jianying.com'
    }
    
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req_api = urllib.request.Request(api_url, headers=headers_api, data=data_bytes, method="POST")
        with urllib.request.urlopen(req_api, context=ctx, timeout=12) as resp_api:
            res_data = resp_api.read().decode('utf-8')
            res_json = json.loads(res_data)
            
        if res_json.get("ret") != "0":
            return jsonify({"code": -1, "msg": f"即梦官方接口返回错误: {res_json.get('message', '未知错误')}"}), 400
            
        item_data = res_json.get("data", {})
        common_attr = item_data.get("common_attr", {})
        
        # 提取关键信息
        description = common_attr.get("description", "").strip()
        author_name = item_data.get("author", {}).get("name", "未知创作者").strip()
        author_avatar = item_data.get("author", {}).get("avatar_url", "").strip()
        sec_uid = item_data.get("author", {}).get("sec_uid", "").strip()
        
        like_count = item_data.get("statistic", {}).get("favorite_num", 0)
        usage_count = item_data.get("statistic", {}).get("usage_num", 0)
        
        # 智能判定是否为首发作品
        is_original = True
        for key in ["template_item_id", "parent_item_id", "source_item_id", "original_item_id"]:
            if item_data.get(key) or common_attr.get(key):
                is_original = False
                break
        if item_data.get("template_item") or item_data.get("parent_item") or item_data.get("origin_item"):
            is_original = False
        
        # 视频直链
        video_info = item_data.get("video", {})
        video_url = ""
        if video_info:
            video_url = video_info.get("transcoded_video", {}).get("origin", {}).get("video_url", "")
            if not video_url:
                video_url = video_info.get("transcoded_video", {}).get("720p", {}).get("video_url", "")
                
        # 封面图直链
        cover_url = common_attr.get("cover_url_map", {}).get("1080", "")
        if not cover_url:
            cover_url = common_attr.get("cover_url", "")
            
        # 第三步：将解析后的单作品信息并入本地数据库，进行创作者建档
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, "parsed_authors_cache.json")
        
        cache_data = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            except Exception:
                pass
                
        if sec_uid:
            author_record = cache_data.setdefault(sec_uid, {
                "author_name": author_name,
                "author_avatar": author_avatar,
                "works": []
            })
            
            # 更新最新头像与名字
            if author_name:
                author_record["author_name"] = author_name
            if author_avatar:
                author_record["author_avatar"] = author_avatar
                
            # 去重合并作品
            work_exists = False
            for w in author_record["works"]:
                if w["id"] == published_item_id:
                    w["like_count"] = like_count
                    w["usage_count"] = usage_count
                    w["prompt"] = description
                    w["cover_url"] = cover_url
                    w["video_url"] = video_url
                    w["is_original"] = is_original
                    work_exists = True
                    break
                    
            if not work_exists:
                ep_cnt = 1
                collection_ids = common_attr.get("collection_ids", [])
                if collection_ids:
                    ep_cnt = len(collection_ids)
                    
                author_record["works"].append({
                    "id": published_item_id,
                    "title": description[:10] if description else "未命名作品",
                    "prompt": description,
                    "cover_url": cover_url,
                    "video_url": video_url,
                    "like_count": like_count,
                    "usage_count": usage_count,
                    "has_prompt": len(description.strip()) > 0,
                    "episodes_count": ep_cnt,
                    "is_original": is_original
                })
                
            # 存回本地
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                print(f"作品 {published_item_id} 已成功存入创作者 {author_name} ({sec_uid}) 的本地缓存。")
            except Exception as e:
                print(f"写入本地缓存失败: {e}")
        
        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "id": published_item_id,
                "author": author_name,
                "avatar": author_avatar,
                "sec_uid": sec_uid,
                "prompt": description,
                "video_url": video_url,
                "cover_url": cover_url,
                "like_count": like_count,
                "usage_count": usage_count,
                "is_original": is_original
            }
        })
        
    except Exception as e:
        return jsonify({"code": -1, "msg": f"请求即梦官方接口失败: {str(e)}"}), 500

# 2. 核心接口：获取某创作者在本地已收录的作品集
@app.route('/api/author/works', methods=['POST'])
def get_author_works():
    data = request.json or {}
    sec_uid = data.get("sec_uid", "").strip()
    if not sec_uid:
        return jsonify({"code": -1, "msg": "缺少参数"}), 400
        
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    cache_path = os.path.join(cache_dir, "parsed_authors_cache.json")
    
    if not os.path.exists(cache_path):
        return jsonify({"code": 0, "data": {"author_name": "无数据", "works": []}})
        
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except Exception:
        return jsonify({"code": -1, "msg": "读取本地数据库失败"}), 500
        
    author_info = cache_data.get(sec_uid, {"author_name": "未知创作者", "author_avatar": "", "works": []})
    
    # 按照作品 ID (即发布顺序的雪花大数) 倒序排列，保证最新的在网格最前
    if "works" in author_info:
        try:
            author_info["works"].sort(key=lambda x: int(x["id"]), reverse=True)
        except Exception:
            pass
            
    return jsonify({"code": 0, "data": author_info})

# 3.0.5 补全接口：获取已收录的创作者名录（修复此前大清洗误删的 Bug）
@app.route('/api/authors/list', methods=['GET'])
def get_authors_list():
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    cache_path = os.path.join(cache_dir, "parsed_authors_cache.json")
    
    if not os.path.exists(cache_path):
        return jsonify({"code": 0, "data": []})
        
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except Exception:
        return jsonify({"code": -1, "msg": "读取本地数据库失败"}), 500
        
    authors = []
    for sec_uid, info in cache_data.items():
        authors.append({
            "sec_uid": sec_uid,
            "author_name": info.get("author_name", "新收录创作者"),
            "author_avatar": info.get("author_avatar", ""),
            "works_count": len(info.get("works", []))
        })
        
    # 按照作品数量倒序，让作品多的作者排在前面
    authors.sort(key=lambda x: x["works_count"], reverse=True)
    return jsonify({"code": 0, "data": authors})

# 3.5 新增接口：获取用户收集的优秀提示词作品集
@app.route('/api/favorite/list', methods=['GET'])
def get_favorites_list():
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    fav_path = os.path.join(cache_dir, "favorites_cache.json")
    
    if not os.path.exists(fav_path):
        return jsonify({"code": 0, "data": []})
        
    try:
        with open(fav_path, "r", encoding="utf-8") as f:
            fav_data = json.load(f)
        return jsonify({"code": 0, "data": fav_data})
    except Exception:
        return jsonify({"code": -1, "msg": "读取收集夹失败"}), 500

# 3.5 新增接口：将指定作品收集到本地词库中
@app.route('/api/favorite/add', methods=['POST'])
def add_favorite():
    data = request.json or {}
    work = data.get("work")
    if not work or not work.get("id"):
        return jsonify({"code": -1, "msg": "收集作品参数无效"}), 400
        
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    os.makedirs(cache_dir, exist_ok=True)
    fav_path = os.path.join(cache_dir, "favorites_cache.json")
    
    fav_data = []
    if os.path.exists(fav_path):
        try:
            with open(fav_path, "r", encoding="utf-8") as f:
                fav_data = json.load(f)
        except Exception:
            pass
            
    # 查重，防止重复收集
    for item in fav_data:
        if item["id"] == work["id"]:
            return jsonify({"code": 0, "msg": "该作品已在您的收集夹中"})
            
    fav_data.append(work)
    
    try:
        with open(fav_path, "w", encoding="utf-8") as f:
            json.dump(fav_data, f, ensure_ascii=False, indent=2)
        return jsonify({"code": 0, "msg": "成功加入收集夹"})
    except Exception as e:
        return jsonify({"code": -1, "msg": f"写入收集数据库失败: {str(e)}"}), 500

# 3.5 新增接口：取消收集指定作品
@app.route('/api/favorite/remove', methods=['POST'])
def remove_favorite():
    data = request.json or {}
    work_id = data.get("id")
    if not work_id:
        return jsonify({"code": -1, "msg": "取消收集参数无效"}), 400
        
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    fav_path = os.path.join(cache_dir, "favorites_cache.json")
    
    if not os.path.exists(fav_path):
        return jsonify({"code": 0, "msg": "取消成功"})
        
    try:
        with open(fav_path, "r", encoding="utf-8") as f:
            fav_data = json.load(f)
    except Exception:
        return jsonify({"code": -1, "msg": "读取收集夹失败"}), 500
        
    new_fav_data = [item for item in fav_data if item["id"] != work_id]
    
    try:
        with open(fav_path, "w", encoding="utf-8") as f:
            json.dump(new_fav_data, f, ensure_ascii=False, indent=2)
        return jsonify({"code": 0, "msg": "已从收集夹移除"})
    except Exception as e:
        return jsonify({"code": -1, "msg": f"更新收集数据库失败: {str(e)}"}), 500

# 3.5 2.0 新增接口：AI 创意提示词工坊，将基本创意智能扩写为 15秒电影级短视频双版本词
@app.route('/api/prompt/generate', methods=['POST'])
def generate_prompt():
    data = request.json or {}
    inspiration = data.get("inspiration", "").strip()
    selected_style = data.get("style", "").strip()
    selected_camera = data.get("camera", "").strip()
    selected_lighting = data.get("lighting", "").strip()
    selected_quality = data.get("quality", "").strip()
    selected_audio = data.get("audio", "").strip()
    api_key = data.get("api_key", "").strip()
    
    if not inspiration:
        return jsonify({"code": -1, "msg": "请先输入您的创意基本要素"}), 400
    if not api_key:
        return jsonify({"code": -1, "msg": "请输入大模型的 API Key 以便进行润色"}), 400
        
    print(f"收到创意扩写请求: 创意={inspiration[:50]}, 风格={selected_style}, 运镜={selected_camera}, 光影={selected_lighting}, 细节={selected_quality}, 声音={selected_audio}")
    
    # 电影导演指令系统预设，定义好双版本输出格式和硬性字数控制
    director_system_prompt = (
        "你是一个顶级的 AI 视频生成提示词导演专家，擅长为即梦AI、Sora等模型创作 12-15秒电影级高品质短视频提示词。\n"
        "用户会提供一个视频的基本创意要素，并指定视频的风格、运镜、光影、细节画质以及声音配乐等专业标签。\n\n"
        "你的任务是将这些视听要素完美结合，并同时输出两个版本的视频专业提示词：【版本 A (分镜时间轴控制版)】和【版本 B (电影长句融合版)】。\n\n"
        "你必须严格按照以下格式输出，不要有任何多余的开头介绍、前言问候、分析解释或结尾寄语。输出格式为：\n\n"
        "====VERSION_A====\n"
        "[时长] 12秒\n"
        "[画质风格] 结合用户所选的风格与细节标签，例如：戏曲国风，电影级质感，极尽奢华的服饰纹理\n"
        "[音乐背景] 结合用户所选的声音配乐，例如：低沉悠扬的钢琴旋律，微风拂过树叶的沙沙声\n\n"
        "---\n\n"
        "时间 | 画面内容 | 运镜/剪辑 | 音乐节点\n"
        "0-3秒 | [描述开场画面主体人物/物体动作与环境细节，包含必要英文术语如 close-up] | [描述镜头运动方式，如 slow panning, zoom in] | [标明声音/配乐切入点，如 BGM 轻柔切入]\n"
        "3-6秒 | [描述动作推移、情绪过渡或材质光影变化] | [描述镜头轨迹，如 slow tracking, tilt up] | [标明声音/旁白变化或物理音效]\n"
        "6-9秒 | [描述动作的高潮蓄力、光影冲突或粒子特效] | [描述运镜，如 rapid pan, dynamic angle] | [声音在此处发生相应变化，或特定乐器切入]\n"
        "9-12秒 | [描述最后的爆发、卡点、碰撞与定格，如水花飞溅、碎片激荡] | [描述收尾运镜，如 freeze frame, sudden stop] | [声音在这一秒卡点爆破，与动作同步定格]\n\n"
        "结尾意境：[一句话概括全片极具诗意或张力的收尾意境，如：微风吹散最后一瓣花朵，留下一片空灵]\n"
        "整体节奏：[用箭头 -> 连接的情绪节奏链，如：炸裂开场 -> 疾速勾勒 -> 情感渐浓 -> 悠长收尾]\n\n"
        "====VERSION_B====\n"
        "[不要使用数字序号、Markdown列表，不要带任何分类标签前缀（如‘画面：’、‘声音：’等），将画面主体、动作、服装、材质细节、镜头运镜、光影色调与声音氛围（包括背景音乐节拍变化、人声旁白质感描述、关键画面发生时的物理撞击或破碎音效配合）完全融合在一整段连贯、画面感极强的中文叙事长句中。在此中文长句中要非常自然地夹带英文专业术语如 close-up, cinematic lighting, volumetric light, slow panning, sub-bass pulse 等，直接开始描述，无额外前缀。]\n\n"
        "【硬性约束】：\n"
        "1. 严格禁止在输出内容、表格标题、前缀标签以及双版本的分隔行中出现任何 Emoji 图标或表情符号。\n"
        "2. 版本 A 和版本 B 的总字数，必须各自独立控制在 600 字以内，精炼且富有电影视听张力。\n"
        "3. 严禁输出任何格式外的闲聊。必须以 ====VERSION_A==== 开头，以 ====VERSION_B==== 进行分隔。"
    )
    
    user_message = (
        f"视频基本创意要素：{inspiration}\n"
        f"指定画质风格：{selected_style}\n"
        f"指定镜头运镜：{selected_camera}\n"
        f"指定光影照明：{selected_lighting}\n"
        f"指定细节画质：{selected_quality}\n"
        f"指定声音配乐：{selected_audio}"
    )
    
    qwen_api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    
    payload = {
        "model": "qwen-plus",
        "input": {
            "messages": [
                {"role": "system", "content": director_system_prompt},
                {"role": "user", "content": user_message}
            ]
        },
        "parameters": {
            "result_format": "message"
        }
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(qwen_api_url, headers=headers, data=data_bytes, method="POST")
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            res_data = resp.read().decode('utf-8')
            res_json = json.loads(res_data)
            
        choices = res_json.get("output", {}).get("choices", [])
        if not choices:
            err_msg = res_json.get("message", "大模型接口未返回有效文本，请检查您的 API Key 是否有效")
            return jsonify({"code": -1, "msg": f"AI 润色失败: {err_msg}"}), 500
            
        text_content = choices[0].get("message", {}).get("content", "")
        
        # 将生成的两个版本拆分并做容错解析
        version_a = ""
        version_b = ""
        
        if "====VERSION_B====" in text_content:
            parts = text_content.split("====VERSION_B====")
            part_a = parts[0].replace("====VERSION_A====", "").strip()
            part_b = parts[1].strip() if len(parts) > 1 else ""
            version_a = part_a
            version_b = part_b
        else:
            # 容错降级
            version_a = text_content.replace("====VERSION_A====", "").strip()
            version_b = "提示：大模型未完美按分隔符生成双版本，请参考左侧完整输出。"
            
        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "version_a": version_a,
                "version_b": version_b
            }
        })
    except Exception as e:
        return jsonify({"code": -1, "msg": f"AI 创意生成失败: {str(e)}，请确认您的 API Key 输入无误，或者网络连接正常。"}), 500


# ================= 视频镜头检测自适应抽帧算法 (双锚点法) =================
def extract_video_keyframes(video_url, max_frames=8):
    """
    通过 OpenCV 检测视频的剪辑点/镜头切换点，并使用双锚点提取前后帧。
    返回: [{"time_offset": float, "image_base64": str, "description": str}, ...]
    """
    import base64
    import time
    
    # 动态导入 cv2，若未安装或不可用则在调用时抛出异常，由外层进行优雅降级
    import cv2
    
    # 1. 代理中转下载视频，伪装请求头以绕过即梦/字节跳动 CDN 403 防盗链限制
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://jimeng.jianying.com/',
        'Origin': 'https://jimeng.jianying.com'
    }
    
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    os.makedirs(cache_dir, exist_ok=True)
    temp_video_path = os.path.join(cache_dir, f"temp_detect_{int(time.time() * 1000)}.mp4")
    
    try:
        print(f"[抽帧助手] 后端代理下载视频中: {video_url[:80]}...")
        req = urllib.request.Request(video_url, headers=headers)
        # 绕过系统 SSL 限制进行直链下载
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            with open(temp_video_path, "wb") as f:
                f.write(resp.read())
        print(f"[抽帧助手] 视频临时下载完成，大小: {os.path.getsize(temp_video_path)} 字节")
    except Exception as e:
        print(f"[抽帧助手] 下载临时视频文件失败: {e}")
        if os.path.exists(temp_video_path):
            try: os.remove(temp_video_path)
            except Exception: pass
        return []

    cap = None
    keyframes = []
    try:
        cap = cv2.VideoCapture(temp_video_path)
        if not cap.isOpened():
            print("[抽帧助手] OpenCV 无法打开视频流")
            return []
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or total_frames <= 0:
            print("[抽帧助手] 视频元数据获取失败")
            return []
            
        duration = total_frames / fps
        print(f"[抽帧助手] 视频属性：帧率={fps:.2f}, 总帧数={total_frames}, 时长={duration:.2f}秒")
        
        # 2. 帧差异直方图扫描（降采样以提高计算性能，每2帧分析一次）
        histograms = []
        sampled_indices = []
        step = 2
        
        for idx in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                break
            # 转为 HSV 空间，计算 H-S 联合直方图以排除亮度和阴影干扰
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            histograms.append(hist)
            sampled_indices.append(idx)
            
        # 3. 计算相邻被采样帧之间的直方图相关性
        correlations = []
        for i in range(len(histograms) - 1):
            score = cv2.compareHist(histograms[i], histograms[i+1], cv2.HISTCMP_CORREL)
            correlations.append((sampled_indices[i], sampled_indices[i+1], score))
            
        # 4. 识别镜头突变剪辑点 (相关性得分低于 0.65 判定为切换点)
        cut_candidates = []
        for start_idx, end_idx, score in correlations:
            if score < 0.65:
                cut_candidates.append((start_idx, end_idx, score))
        print(f"[抽帧助手] 检测到 {len(cut_candidates)} 个剪辑切换转场点。")
        
        # 5. 双锚点帧索引确定：首帧 + 尾帧 + 每一个剪辑点的 N-1 和 N 帧
        frames_to_extract = set()
        frames_to_extract.add(0)
        frames_to_extract.add(total_frames - 1)
        for start_idx, end_idx, score in cut_candidates:
            frames_to_extract.add(start_idx)
            frames_to_extract.add(end_idx)
            
        sorted_extract_indices = sorted(list(frames_to_extract))
        
        # 6. 最大帧数熔断机制（超标时按显著度 score 筛选，始终保留首尾帧）
        if len(sorted_extract_indices) > max_frames:
            print(f"[抽帧助手] 待提取帧数 ({len(sorted_extract_indices)}) 超过上限 ({max_frames})，进行显著度裁剪...")
            essential_indices = {0, total_frames - 1}
            # 按直方图相关性得分从低到高（差异从大到小）排序
            cut_candidates.sort(key=lambda x: x[2])
            for start_idx, end_idx, score in cut_candidates:
                if len(essential_indices) + 2 <= max_frames:
                    essential_indices.add(start_idx)
                    essential_indices.add(end_idx)
                else:
                    break
            sorted_extract_indices = sorted(list(essential_indices))
            
        print(f"[抽帧助手] 最终确定抓取的关键帧集合: {sorted_extract_indices}")
        
        # 7. 提取帧图并进行 Base64 编码与尺寸等比例下采样
        for frame_idx in sorted_extract_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                continue
                
            time_offset = frame_idx / fps
            
            # 等比例缩放至最大边 800px 以节省大模型 Payload 带宽与 Token
            h, w = frame.shape[:2]
            max_size = 800
            if max(h, w) > max_size:
                scale = max_size / max(h, w)
                frame_resized = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            else:
                frame_resized = frame
                
            # 压缩编码为 JPEG
            success, encoded_img = cv2.imencode('.jpg', frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not success:
                continue
                
            img_b64 = base64.b64encode(encoded_img).decode('utf-8')
            
            # 命名帧的语义，辅助大模型理解时序
            if frame_idx == 0:
                desc = "视频开始（第 0 秒）起点画面"
            elif frame_idx == total_frames - 1:
                desc = f"视频结束（第 {time_offset:.1f} 秒）尾声定格画面"
            else:
                is_before = False
                is_after = False
                for s_idx, e_idx, _ in cut_candidates:
                    if frame_idx == s_idx:
                        is_before = True
                        break
                    if frame_idx == e_idx:
                        is_after = True
                        break
                if is_before:
                    desc = f"镜头切换前最后一帧（第 {time_offset:.1f} 秒，上一个分镜的结束画面）"
                elif is_after:
                    desc = f"镜头切换后第一帧（第 {time_offset:.1f} 秒，下一个新分镜的开始画面）"
                else:
                    desc = f"第 {time_offset:.1f} 秒关键帧画面"
                    
            keyframes.append({
                "time_offset": time_offset,
                "image_base64": f"data:image/jpeg;base64,{img_b64}",
                "description": desc
            })
            
    except Exception as e:
        print(f"[抽帧助手] 自适应镜头抽帧运行失败: {e}")
    finally:
        if cap is not None:
            try: cap.release()
            except Exception: pass
        # Released temp video deletion responsibility to main reverse_prompt loop.
                
    return keyframes


def download_temp_video(video_url):
    import time
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://jimeng.jianying.com/',
        'Origin': 'https://jimeng.jianying.com'
    }
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    os.makedirs(cache_dir, exist_ok=True)
    temp_video_path = os.path.join(cache_dir, f"temp_detect_{int(time.time() * 1000)}.mp4")
    try:
        print(f"[下载助手] 正在下载临时视频: {video_url[:80]}...")
        req = urllib.request.Request(video_url, headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            with open(temp_video_path, "wb") as f:
                f.write(resp.read())
        print(f"[下载助手] 临时视频下载完成，大小: {os.path.getsize(temp_video_path)} 字节")
        return temp_video_path
    except Exception as e:
        print(f"[下载助手] 下载视频失败: {e}")
        if os.path.exists(temp_video_path):
            try: os.remove(temp_video_path)
            except Exception: pass
        return ""


def extract_video_keyframes_local(temp_video_path, max_frames=8):
    import base64
    import cv2
    
    if not temp_video_path or not os.path.exists(temp_video_path):
        print("[抽帧助手] 本地临时视频文件不存在")
        return []
        
    cap = None
    keyframes = []
    try:
        cap = cv2.VideoCapture(temp_video_path)
        if not cap.isOpened():
            print("[抽帧助手] OpenCV 无法打开视频文件")
            return []
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or total_frames <= 0:
            print("[抽帧助手] 视频元数据获取失败")
            return []
            
        duration = total_frames / fps
        print(f"[抽帧助手] 视频属性：帧率={fps:.2f}, 总帧数={total_frames}, 时长={duration:.2f}秒")
        
        # 帧差异直方图扫描（每2帧采样一次）
        histograms = []
        sampled_indices = []
        step = 2
        
        for idx in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                break
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            histograms.append(hist)
            sampled_indices.append(idx)
            
        # 计算直方图相关性
        correlations = []
        for i in range(len(histograms) - 1):
            score = cv2.compareHist(histograms[i], histograms[i+1], cv2.HISTCMP_CORREL)
            correlations.append((sampled_indices[i], sampled_indices[i+1], score))
            
        # 镜头切换点判断
        cut_candidates = []
        for start_idx, end_idx, score in correlations:
            if score < 0.65:
                cut_candidates.append((start_idx, end_idx, score))
        print(f"[抽帧助手] 检测到 {len(cut_candidates)} 个剪辑转场点。")
        
        # 黄金双锚点组合
        frames_to_extract = set()
        frames_to_extract.add(0)
        frames_to_extract.add(total_frames - 1)
        for start_idx, end_idx, score in cut_candidates:
            frames_to_extract.add(start_idx)
            frames_to_extract.add(end_idx)
            
        sorted_extract_indices = sorted(list(frames_to_extract))
        
        if len(sorted_extract_indices) > max_frames:
            print(f"[抽帧助手] 待提取帧数超过上限 {max_frames}，进行显著度裁剪...")
            essential_indices = {0, total_frames - 1}
            cut_candidates.sort(key=lambda x: x[2])
            for start_idx, end_idx, score in cut_candidates:
                if len(essential_indices) + 2 <= max_frames:
                    essential_indices.add(start_idx)
                    essential_indices.add(end_idx)
                else:
                    break
            sorted_extract_indices = sorted(list(essential_indices))
            
        print(f"[抽帧助手] 最终关键帧集合: {sorted_extract_indices}")
        
        for frame_idx in sorted_extract_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                continue
                
            time_offset = frame_idx / fps
            
            h, w = frame.shape[:2]
            max_size = 800
            if max(h, w) > max_size:
                scale = max_size / max(h, w)
                frame_resized = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            else:
                frame_resized = frame
                
            success, encoded_img = cv2.imencode('.jpg', frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not success:
                continue
                
            img_b64 = base64.b64encode(encoded_img).decode('utf-8')
            
            if frame_idx == 0:
                desc = "视频开始（第 0 秒）起点画面"
            elif frame_idx == total_frames - 1:
                desc = f"视频结束（第 {time_offset:.1f} 秒）尾声定格画面"
            else:
                is_before = False
                is_after = False
                for s_idx, e_idx, _ in cut_candidates:
                    if frame_idx == s_idx:
                        is_before = True
                        break
                    if frame_idx == e_idx:
                        is_after = True
                        break
                if is_before:
                    desc = f"镜头切换前最后一帧（第 {time_offset:.1f} 秒，上一个分镜的结束画面）"
                elif is_after:
                    desc = f"镜头切换后第一帧（第 {time_offset:.1f} 秒，下一个新分镜的开始画面）"
                else:
                    desc = f"第 {time_offset:.1f} 秒关键帧画面"
                    
            keyframes.append({
                "time_offset": time_offset,
                "image_base64": f"data:image/jpeg;base64,{img_b64}",
                "description": desc
            })
            
    except Exception as e:
        print(f"[抽帧助手] 本地抽帧失败: {e}")
    finally:
        if cap is not None:
            try: cap.release()
            except Exception: pass
            
    return keyframes


def extract_video_audio_local(temp_video_path):
    import subprocess
    import time
    
    if not temp_video_path or not os.path.exists(temp_video_path):
        print("[AudioExtract] Temp video file not found")
        return ""
        
    cache_dir = os.path.dirname(temp_video_path)
    temp_audio_path = os.path.join(cache_dir, f"temp_audio_{int(time.time() * 1000)}.mp3")
    
    # ffmpeg arguments:
    cmd = [
        "ffmpeg", "-i", temp_video_path,
        "-vn", "-acodec", "libmp3lame",
        "-ar", "16000", "-ac", "1",
        "-y", temp_audio_path
    ]
    
    try:
        print("[AudioExtract] Extracting audio stream via ffmpeg command line...")
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15, startupinfo=startupinfo)
        if result.returncode == 0 and os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 0:
            print(f"[AudioExtract] Success, size: {os.path.getsize(temp_audio_path)} bytes")
            return temp_audio_path
        else:
            print(f"[AudioExtract] ffmpeg failed, code: {result.returncode}, error: {result.stderr}")
            if os.path.exists(temp_audio_path):
                try: os.remove(temp_audio_path)
                except Exception: pass
            return ""
    except Exception as e:
        print(f"[AudioExtract] Exception run: {e}")
        if os.path.exists(temp_audio_path):
            try: os.remove(temp_audio_path)
            except Exception: pass
        return ""


def recognize_audio_features(audio_path, api_key):
    import base64
    import json
    import urllib.request
    
    if not audio_path or not os.path.exists(audio_path):
        print("[AudioRecognize] Audio file not found")
        return ""
        
    try:
        print("[AudioRecognize] Reading audio file and converting to base64...")
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
        audio_input = f"data:audio/mp3;base64,{audio_b64}"
        
        qwen_api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        
        payload = {
            "model": "qwen-audio-turbo",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"audio": audio_input},
                            {"text": '你听到了什么BGM背景音乐、什么乐器、有无旁白、有么特定的物理音效（如爆炸、撞击、流水）或人声？请用纯中文在50字内枅简、专业地描述这段音频的声效特征，不要请废话。'}
                        ]
                    }
                ]
            },
            "parameters": {}
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        print("[AudioRecognize] Requesting Qwen-Audio-Turbo model...")
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(qwen_api_url, headers=headers, data=data_bytes, method="POST")
        
        with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
            res_data = resp.read().decode('utf-8')
            res_json = json.loads(res_data)
            
        choices = res_json.get("output", {}).get("choices", [])
        if not choices:
            err_msg = res_json.get("message", "No response text")
            print(f"[AudioRecognize] Model error: {err_msg}")
            return ""
            
        audio_desc = choices[0].get("message", {}).get("content", "")
        if isinstance(audio_desc, list):
            audio_desc = "\n".join([item.get("text", "") for item in audio_desc if isinstance(item, dict)])
            
        audio_desc = audio_desc.strip()
        print(f"[AudioRecognize] Success, desc: {audio_desc}")
        return audio_desc
        
    except Exception as e:
        print(f"[AudioRecognize] Exception: {e}")
        return ""


# 4. Core API: reverse video prompts (v1.2.0, support audio model reverse and VIP commercial cutoff)
@app.route('/api/reverse', methods=['POST'])
def reverse_prompt():
    import base64
    
    data = request.json or {}
    image_url = data.get("image_url", "").strip()
    image_base64 = data.get("image_base64", "").strip()
    api_key = data.get("api_key", "").strip()
    mode = data.get("mode", "2").strip()
    video_prompt = data.get("video_prompt", "").strip()
    video_url = data.get("video_url", "").strip()
    audio_mode = data.get("audio_mode", "visual").strip()
    
    if not image_url and not image_base64 and not video_url:
        return jsonify({"code": -1, "msg": '缺少图片连接、本å\x9c°图ç\x89\x87数据或视频连接'}), 400
    if not api_key:
        return jsonify({"code": -1, "msg": '请先配置大模型 API Key（可在设置中填写）'}), 400
        
    print(f"Reverse request, mode: {mode}, audio_mode: {audio_mode}, video_url: {bool(video_url)}")
    
    # === Commercial Cutoff Gateways (For Version and VIP Management) ===
    user_level = data.get("user_level", "free").strip()
    
    if video_url and user_level == "free":
        # Commercial cutoff logic for VIP:
        # return jsonify({"code": 1001, "msg": '自适应分镜抽帧反推为【VIP专业版】特权功能，请升级后使用！'}), 403
        pass
        
    if audio_mode == "listen" and user_level == "free":
        # Commercial cutoff logic for SVIP:
        # return jsonify({"code": 1002, "msg": s'自适应分镜抽帧反推为【VIP专业版】特权功能，请升级后使用！'}), 403
        pass
    # ====================================================================
    
    # 1. Download, keyframes extraction and audio extraction (One Download Multi Pipeline)
    keyframes = []
    audio_features_desc = ""
    temp_video_path = ""
    temp_audio_path = ""
    
    if video_url:
        try:
            temp_video_path = download_temp_video(video_url)
            if temp_video_path:
                try:
                    keyframes = extract_video_keyframes_local(temp_video_path, max_frames=8)
                except Exception as e:
                    print(f"Warning: extract_video_keyframes_local failed: {e}")
                
                if audio_mode == "listen":
                    try:
                        print("[Reverse] Enabled listening mode, extracting audio...")
                        temp_audio_path = extract_video_audio_local(temp_video_path)
                        if temp_audio_path:
                            audio_features_desc = recognize_audio_features(temp_audio_path, api_key)
                    except Exception as e:
                        print(f"Warning: extract_video_audio_local or recognize_audio_features failed: {e}")
                    finally:
                        if temp_audio_path and os.path.exists(temp_audio_path):
                            try:
                                os.remove(temp_audio_path)
                                print("[Reverse] Temp audio deleted successfully.")
                            except Exception:
                                pass
        except Exception as e:
            print(f"Warning: Video multimodal extraction failed: {e}")
        finally:
            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                    print("[Reverse] Temp video deleted successfully.")
                except Exception:
                    pass
            
    use_multi_images = len(keyframes) > 0
    content_list = []
    
    if use_multi_images:
        print(f"[Reverse] Multi-image reverse mode, keyframes: {len(keyframes)}")
        for kf in keyframes:
            content_list.append({"image": kf["image_base64"]})
            
        keyframes_guide = "You are provided with a sequence of keyframes in chronological order:\n"
        for idx, kf in enumerate(keyframes):
            keyframes_guide += f"- Keyframe {idx + 1}: {kf['description']}\n"
        keyframes_guide += "\n"
        
        audio_features_guide = ""
        if audio_mode == "listen" and audio_features_desc:
            audio_features_guide = '根据 AI 音频模型对å\x8e\x9f视频的听音分析，该视频å\x8e\x9f声配乐及音效特征为：【' + audio_features_desc + '】。在å\x8f\x8d推的音ä¹\x90背景与配乐节点中，你必须以此真实音频特征为依æ\x8d®，将其融å\x85¥到提ç¤º词的配乐/音效描述中（例如å¦\x82果是古é£\x8e音乐，提ç¤º词中音乐背景又要å\x86\x99å\x8f¤é£\x8e，并在对åº\x94时间点安æ\x8e\x92å\x8f¤é£\x8e乐å\x99¨å\x8d¡点）。\n\n'
        else:
            audio_features_guide = '目前为视觉脑补音效模式，你应当根æ\x8d®画面意境，脑补最贴合视频画é\x9d¢的背景é\x9f³乐及é\x9f³效风æ\xa0¼，不要受真å®\x9e声音限å\x88¶。\n\n'
            
        prompt_header = ""
        if video_prompt:
            prompt_header = '该视频作品的å\x8e\x9f版描述大纲提示词为：【' + video_prompt + '】。你必é¡»以此描述中包含的主题和å\x89§情为核心，不得偏离。\n\n'
            
        if mode == "1":
            prompt_text = (
                f"{prompt_header}"
                f"{keyframes_guide}"
                f"{audio_features_guide}"
                "请作为一名顶级的 AI 视频生成提示词导演专家，以上面这组按时序排列的静态关键帧为视觉参考，分析每个分镜里动作的变化与镜头转场逻辑（特别注意剪辑点‘变前最后一帧’与‘变后第一帧’的交界处），并严格结合视频的原版描述大纲作为剧情核心骨架，反向重构并脑补出用于直接在即梦里重新生成该动态视频的专业级 12秒 时序分镜剧本方案。\n\n"
                "你必须严格按照以下格式直接输出，不要有任何多余的开头介绍、前言分析或结尾寄语，严禁在任何地方使用 Emoji 图形符号。输出格式如下：\n\n"
                "[时长] 12秒\n"
                "[画质风格] [根据图片反推其整体画质、风格倾向、物理材质与细节表现]\n"
                "[音乐背景] [根据画面意境，脑补最贴合的背景音乐及音效风格]\n\n"
                "---\n\n"
                "时间 | 画面内容 | 运镜/剪辑 | 音乐节点\n"
                "0-3秒 | [描述开场分镜画面主体细节与动作，结合第0秒的画面，包含英文术语如 close-up] | [描述镜头运动方式，如 slow panning, zoom in] | [标明音效/音乐切入点]\n"
                "3-6秒 | [结合后续的时间点画面，描述接下来的动作延伸、分镜切换或光影过渡，并在切换处清晰说明如何转场] | [描述镜头轨迹，如 slow tracking, tilt up] | [标明声音/人声或背景乐的变化]\n"
                "6-9秒 | [结合后续的时间点画面，描述动作变化、分镜切换，体现物理光影的冲突或材质的高精细度呈现] | [描述运镜方式，如 quick pan, orbital shot] | [描述声音的高潮或器乐卡点]\n"
                "9-12秒 | [结合最后定格的尾声画面，描述最后的动作爆发、分镜结尾或定格，如碎片激荡、光芒定格] | [描述定格或收尾运镜，如 freeze frame, fade out] | [音效在此处强力卡点，与画面同步定格]\n\n"
                "结尾意境：[一句话概括全片极具诗意或画卷感的收尾意境]\n"
                "整体节奏：[用 -> 连结的情绪节奏链，如：炸裂开场 -> 镜头切换 -> 情感渐浓 -> 悠长收尾]\n\n"
                "【硬性约束】：\n"
                "1. 严格禁止在输出内容中带有任何 Emoji 字符。\n"
                "2. 输出总字数必须严格控制在 600 字以内，字字珠玑，去粗取精。"
            
            )
        else:
            prompt_text = (
                f"{prompt_header}"
                f"{keyframes_guide}"
                f"{audio_features_guide}"
                "请作为一名顶级的 AI 视频生成提示词导演专家，以上面这组按时序排列的静态关键帧为视觉参考，分析每个分镜里动作的变化与镜头转场逻辑，并严格结合视频的原版描述大纲作为核心剧情，反向重构并脑补出用于直接在即梦里生成视频的专业提示词。\n\n"
                "【输出格式与硬性约束】：\n"
                "1. 必须将画面主体、动作演变、分镜切换、衣服材质、镜头运镜、光影照明、色调氛围以及最契合该画面的声音配乐氛围，完全融合成一整段连贯、画面感极强的中文叙事长句。不得使用数字序号，不得带有任何分类标签前缀，不得使用 Markdown 列表或任何分段，必须是仅有一段的纯文本叙事。\n"
                "2. 中文长句中要非常自然地夹带英文专业术语或指令（如 close-up, cinematic lighting, volumetric light, slow panning, sub-bass pulse 等）。\n"
                "3. 整体提示词必须要融入对分镜切换时序（如 0秒、3秒、6秒、9秒等镜头如何切换和过渡）的动作连贯性描述。\n"
                "4. 严格禁止在输出文本中出现任何 Emoji 图标符号。\n"
                "5. 整体总字数必须严格控制在 600 字以内，文字需展现出电影美感与高度视觉张力，短小精悍，无任何闲聊或前后缀说明，直接输出这一整段提示词内容。"
            
            )
            
        content_list.append({"text": prompt_text})
        
    else:
        print("Entering single image fallback branch.")
        if image_base64:
            image_input = image_base64
            print("Using front-end base64 image data.")
        else:
            image_input = image_url
            try:
                img_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://jimeng.jianying.com/'
                }
                print("Downloading network image for base64 conversion...")
                img_req = urllib.request.Request(image_url, headers=img_headers)
                with urllib.request.urlopen(img_req, context=ctx, timeout=15) as img_resp:
                    img_data = img_resp.read()
                    content_type = img_resp.headers.get('Content-Type', 'image/jpeg')
                base64_data = base64.b64encode(img_data).decode('utf-8')
                image_input = f"data:{content_type};base64,{base64_data}"
                print("Image base64 converted successfully.")
            except Exception as e:
                print(f"Warning: image base64 conversion failed: {e}")
                image_input = image_url
                
        content_list.append({"image": image_input})
        
        prompt_header = ""
        if video_prompt:
            prompt_header = '该视频作品的å\x8e\x9f版描述大纲提示词为：【' + video_prompt + '】。你必é¡»以此描述中包含的主题和å\x89§情为核心，不得偏离。\n\n'
            
        if mode == "1":
            prompt_text = (
                f"{prompt_header}"
                "你看到的这张图片是一段由 AI 生成的动态视频的核心封面或第一帧。\n"
                f"{prompt_header}"
                "请作为一名顶级的 AI 视频生成提示词导演专家，以此静态画面为视觉参考，并严格结合该视频的原版描述提示词作为剧情核心骨架，反向重构并脑补扩展出用于生成该动态视频的专业级 12秒 时序分镜剧本方案。\n\n"
                "你必须严格按照以下格式直接输出，不要有任何多余的开头介绍、前言分析或结尾寄语，严禁在任何地方使用 Emoji 图形符号。输出格式如下：\n\n"
                "[时长] 12秒\n"
                "[画质风格] [根据图片反推其画质、风格倾向、物理材质与细节表现]\n"
                "[音乐背景] [根据画面意境，脑补最贴合的背景音乐及音效风格]\n\n"
                "---\n\n"
                "时间 | 画面内容 | 运镜/剪辑 | 音乐节点\n"
                "0-3秒 | [描述开场时承接本图的画面主体细节与动作演变，包含英文术语如 close-up] | [描述本阶段运镜，如 slow panning, zoom in] | [标明音效/音乐切入点]\n"
                "3-6秒 | [脑补描述接下来的动作延伸、主体位置变化或光影色调过渡] | [描述镜头轨迹，如 slow tracking, tilt up] | [标明声音/人声或背景乐的变化]\n"
                "6-9秒 | [脑补描述动作的蓄力、物理光影的冲突或材质的高精细度呈现] | [描述运镜方式，如 quick pan, orbital shot] | [描述声音的高潮或器乐卡点]\n"
                "9-12秒 | [脑补描述最终的爆发、物理碰撞、卡点或定格，如碎片激荡、光芒绽放] | [描述定格或收尾运镜，如 freeze frame, fade out] | [音效在此处强力卡点，与画面同步定格]\n\n"
                "结尾意境：[一句话概括全片极具诗意或画卷感的收尾意境]\n"
                "整体节奏：[用 -> 连结的情绪节奏链，如：炸裂开场 -> 疾速勾勒 -> 情感渐浓 -> 悠长收尾]\n\n"
                "【硬性约束】：\n"
                "1. 严格禁止在输出内容中带有任何 Emoji 字符。\n"
                "2. 输出总字数必须严格控制在 600 字以内，字字珠玑，去粗取精。"
            
            )
        else:
            prompt_text = (
                f"{prompt_header}"
                "你看到的这张图片是一段由 AI 生成的动态视频的核心封面或第一帧。\n"
                f"{prompt_header}"
                "请作为一名顶级的 AI 视频生成提示词导演专家，以此静态画面为视觉参考，并严格结合该视频的原版描述提示词作为剧情核心，反向重构并脑补出用于直接生成视频的专业提示词。\n\n"
                "【输出格式与硬性约束】：\n"
                "1. 必须将画面主体、动作演变、衣服材质、镜头运镜、光影照明、色调氛围以及最契合该画面的声音配乐氛围，完全融合成一整段连贯、画面感极强的中文叙述文字。不得使用数字序号，不得带有任何分类标签前缀（如‘画面：’、‘运镜：’等），不得使用 Markdown 列表或任何分段，必须是仅有一段的纯文本叙事。\n"
                "2. 中文长句中要非常自然地夹带英文专业术语或指令（如 close-up, cinematic lighting, volumetric light, slow panning, sub-bass pulse 等）。\n"
                "3. 严格禁止在输出文本中出现任何 Emoji 图标符号。\n"
                "4. 整体总字数必须严格控制在 600 字以内，文字需展现出电影美感与高度视觉张力，短小精悍，无 any 闲聊或前后缀说明，直接输出这一整段提示词内容。"
            
            )
            
        content_list.append({"text": prompt_text})
        
    qwen_api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    payload = {
        "model": "qwen-vl-max",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": content_list
                }
            ]
        },
        "parameters": {}
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(qwen_api_url, headers=headers, data=data_bytes, method="POST")
        with urllib.request.urlopen(req, context=ctx, timeout=35) as resp:
            res_data = resp.read().decode('utf-8')
            res_json = json.loads(res_data)
            
        choices = res_json.get("output", {}).get("choices", [])
        if not choices:
            err_msg = res_json.get("message", "No text returned from API")
            return jsonify({"code": -1, "msg": f"AI reverse failed: {err_msg}"}), 500
            
        reversed_text = choices[0].get("message", {}).get("content", "")
        if isinstance(reversed_text, list):
            reversed_text = "\n".join([item.get("text", "") for item in reversed_text if isinstance(item, dict)])
            
        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "reversed_prompt": reversed_text
            }
        })
    except Exception as e:
        return jsonify({"code": -1, "msg": f"Failed requesting Alibaba model: {str(e)}"}), 500

# 5. 核心接口：代理中转下载接口（穿透字节 CDN 403 拦截）
@app.route('/api/download', methods=['GET'])
def download_media():
    from flask import Response
    import time
    
    media_url = request.args.get("url", "").strip()
    if not media_url:
        return "缺少视频/图片链接", 400
        
    print(f"收到代理下载请求: {media_url[:80]}...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://jimeng.jianying.com/',
        'Origin': 'https://jimeng.jianying.com'
    }
    
    try:
        req = urllib.request.Request(media_url, headers=headers)
        resp = urllib.request.urlopen(req, context=ctx, timeout=20)
        
        content_type = resp.headers.get('Content-Type', 'video/mp4')
        
        def generate():
            block_size = 8192
            try:
                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
                print("后端代理下载流已安全释放关闭。")
                
        filename = f"jimeng_raw_{int(time.time())}.mp4"
        headers_out = {
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': content_type
        }
        return Response(generate(), headers=headers_out)
    except Exception as e:
        return f"助手代理下载失败: {str(e)}", 500

# 6. 静态网页根路由
@app.route('/')
def index_page():
    # 兼容打包后的单文件运行路径
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    template_path = os.path.join(base_dir, "templates", "index.html")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return html_content
    except Exception as e:
        return f"<h3>前端 index.html 加载失败！</h3><p>错误原因: {str(e)}</p>"

def kill_port_process(port=5000):
    import subprocess
    try:
        cmd = f"netstat -ano | findstr :{port}"
        res = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = res.communicate()
        lines = stdout.decode('utf-8', errors='ignore').strip().split('\n')
        pids = set()
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 5 and f":{port}" in parts[1]:
                pids.add(parts[-1])
        for pid in pids:
            if pid != "0":
                print(f"[清理] 发现 5000 端口占用，PID: {pid}，正在强行清理以防冲突...")
                os.system(f"taskkill /f /pid {pid} >nul 2>&1")
    except Exception as e:
        print(f"[清理] 端口清理失败: {e}")

if __name__ == '__main__':
    local_ip = get_local_ip()
    print("\n" + "="*60)
    print("即梦AI 提示词提取与无水印下载服务端已启动！")
    print(f"电脑端访问地址: http://127.0.0.1:5000")
    print(f"局域网(手机端)访问地址: http://{local_ip}:5000")
    print("="*60 + "\n")
    kill_port_process(5000)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
