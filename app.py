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
                    "episodes_count": ep_cnt
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
                "usage_count": usage_count
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
        "你是一个顶级的 AI 视频生成提示词导演专家，擅长为即梦AI、Sora等模型创作 15秒电影级高品质短视频提示词。\n"
        "用户会提供一个视频的基本创意要素，并指定视频的风格、运镜、光影、细节画质以及声音配乐等专业标签。\n\n"
        "你的任务是将这些视听要素完美结合，并同时输出两个版本的 15秒视频专业提示词：【版本 A (分镜时间轴控制版)】和【版本 B (电影长句融合版)】。\n\n"
        "你必须严格按照以下格式输出，不要有任何多余的开头介绍、前言问候、分析解释或结尾寄语。输出格式为：\n\n"
        "====VERSION_A====\n"
        "### 🎬 15秒分镜时间轴版 (Version A)\n"
        "- **00:00-00:05** (画面铺垫与起势)：[结合所选风格、运镜与光影描述角色、服装、起势动作。同时标明声音/配乐切入点，如 BGM 节奏轻柔切入或特定物理环境音效出现]\n"
        "- **00:05-00:10** (动作蓄力与镜头过渡)：[结合运镜、细节与光影变化描述动作蓄力与镜头过渡。同时标明声音/配乐的起伏变化，或人声旁白/独白进入的句式]\n"
        "- **00:10-00:15** (卡点爆发与高潮收尾)：[结合细节画质描述动作卡点爆发、物理碰撞特效如水花飞溅/碎片激荡。同时必须写明在此阶段配合画面爆发爆发出的最强物理音效或BGM节拍卡点爆破，并镜头定格]\n"
        "*(推荐参数及配乐风格：[给出推荐的清晰度、运镜速度，以及最适合卡点的BGM曲风等建议])*\n\n"
        "====VERSION_B====\n"
        "### 🎥 电影级长句融合版 (Version B)\n"
        "[不要使用数字序号、Markdown列表，不要带任何分类标签前缀（如‘画面：’、‘声音：’等），将画面主体、动作、服装、材质细节、镜头运镜、光影色调与声音氛围（包括背景音乐节拍变化、人声旁白质感描述、关键画面发生时的物理撞击或破碎音效配合）完全融合在一整段连贯、画面感极强的中文叙事长句中。在此中文长句中要非常自然地夹带英文专业术语如 close-up, cinematic lighting, sub-bass pulse, glass shattering 等，直接开始描述，无额外前缀。]\n\n"
        "【硬性约束】：\n"
        "1. 版本 A 和版本 B 的总字数，必须各自独立控制在 600 字以内，精炼且富有电影视听张力。\n"
        "2. 严禁输出任何格式外的闲聊。必须以 ====VERSION_A==== 开头，以 ====VERSION_B==== 进行分隔。"
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


# 4. 核心接口：通义千问大模型智能反推提示词
@app.route('/api/reverse', methods=['POST'])
def reverse_prompt():
    import base64
    
    data = request.json or {}
    image_url = data.get("image_url", "").strip()
    api_key = data.get("api_key", "").strip()
    mode = data.get("mode", "2").strip()
    
    if not image_url:
        return jsonify({"code": -1, "msg": "缺少图片链接"}), 400
    if not api_key:
        return jsonify({"code": -1, "msg": "请先配置大模型 API Key（可在设置中填写）"}), 400
        
    print(f"收到 AI 视频反推请求，方案模式: {mode}，图片地址: {image_url[:80]}...")
    
    # 后端下载图片并转成 Base64，100% 避免大模型端拉取字节 CDN 403 限流
    image_input = image_url
    try:
        img_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://jimeng.jianying.com/'
        }
        print("后端正在代理下载图片并转换为 Base64 数据流...")
        img_req = urllib.request.Request(image_url, headers=img_headers)
        with urllib.request.urlopen(img_req, context=ctx, timeout=15) as img_resp:
            img_data = img_resp.read()
            content_type = img_resp.headers.get('Content-Type', 'image/jpeg')
        base64_data = base64.b64encode(img_data).decode('utf-8')
        image_input = f"data:{content_type};base64,{base64_data}"
        print("图片 Base64 转换成功！")
    except Exception as e:
        print(f"警告: 后端图片转 Base64 失败，回退到使用原 URL 请求大模型: {e}")
        image_input = image_url
        
    # 调用阿里通义千问多模态模型 (Qwen-VL-Max) 进行反推
    qwen_api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    
    if mode == "1":
        prompt_text = (
            "你看到的这张图片是一段由 AI 生成的动态视频（Video）的核心封面、起始帧或关键画面。\n"
            "请作为一名顶级的 AI 视频生成（Text-to-Video / Image-to-Video）提示词专家，为我深度反推并重构用于生成该动态视频的专业级提示词方案。\n\n"
            "你需要严格按照以下十个方面，对画面进行深度拆解与重构，并使用极简的 Markdown 列表格式输出：\n\n"
            "### 🎬 **专业级 AI 视频反推生成方案**\n\n"
            "- **【画面】**：(极简描述画面的主体人物/物体、动作演变、衣服款式、材质、纹理、物理动态脑补)\n"
            "- **【台词】**：(旁白、角色台词或意境独白，若无写无台词)\n"
            "- **【运镜】**：(相机的运动轨迹与速度)\n"
            "- **【景别】**：(镜头的框架范围，如特写/全景)\n"
            "- **【光影】**：(光线的方向与质感)\n"
            "- **【色调】**：(色彩倾向和风格)\n"
            "- **【音效】**：(最贴合的物理环境音或音乐提示)\n"
            "- **【情绪】**：(角色或场景传递的情感)\n"
            "- **【镜头构图】**：(画面的视觉几何美学)\n"
            "- **【氛围感】**：(用一句话概括整体的意境)\n\n"
            "### 🇬🇧 **一键复制英文提示词 (English Prompt)**\n"
            "（请将上述关键特征和运镜，融合并精简为一段连贯、高质量的英文视频生成提示词，用于直接生成视频。例如：`Close-up, slow zoom in, a man in a business suit, blinking, warm tone...`）\n\n"
            "### 💡 **AI 参数建议**\n"
            "（用一句话给出生视频的推荐参数，如运镜速度、清晰度等。）\n\n"
            "⚠️【硬性约束】：为满足即梦平台的字数限制，上述所有部分的总输出字数必须严格控制在 600 字以内（包含标点符号、中文、英文和 Markdown 符号）。请字字珠玑，去掉所有多余的寒暄与废话，直接输出内容。"
        )
    else:
        prompt_text = (
            "你看到的这张图片是一段由 AI 生成的动态视频（Video）的核心封面、起始帧或关键画面。\n"
            "请作为一名顶级的 AI 视频生成（Text-to-Video / Image-to-Video）提示词专家，为我深度反推并重构用于生成该动态视频的专业级提示词。\n\n"
            "【输出格式与硬性约束】：\n"
            "1. 必须将“画面、台词、运镜、景别、光影、色调、音效、情绪、镜头构图、氛围感”这十个要素以及参数生成建议，完全融合成**一整段连贯、画面感极强的中文叙述文字**（不能使用数字序号、不能带有‘画面：’、‘运镜：’等任何分类标签前缀，不能使用 Markdown 列表或任何分段，必须是仅有一段的纯文本叙事）。\n"
            "2. 不提供整段的英文翻译提示词，但必须在中文长句里非常自然地夹带必要的相关英文专业术语或指令（如 `close-up`, `slow panning`, `volumetric light`, `cinematic lighting` 等）。\n"
            "3. 整体总字数必须严格控制在 600 字以内（含标点符号和英文术语），文字需要展现出电影美感与高度视觉张力，短小精悍。\n"
            "4. 严禁提供任何额外的建议、开头介绍、分析解释或结尾问候，直接输出这一整段提示词内容。"
        )
    
    payload = {
        "model": "qwen-vl-max",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": image_input},
                        {"text": prompt_text}
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
    
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(qwen_api_url, headers=headers, data=data_bytes, method="POST")
        with urllib.request.urlopen(req, context=ctx, timeout=35) as resp:
            res_data = resp.read().decode('utf-8')
            res_json = json.loads(res_data)
            
        choices = res_json.get("output", {}).get("choices", [])
        if not choices:
            err_msg = res_json.get("message", "接口未返回有效文本，请检查 API Key 权限或余额")
            return jsonify({"code": -1, "msg": f"AI 反推失败: {err_msg}"}), 500
            
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
        return jsonify({"code": -1, "msg": f"请求阿里大模型失败: {str(e)}，请确认您的 API Key 填写正确且接口可用"}), 500

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
