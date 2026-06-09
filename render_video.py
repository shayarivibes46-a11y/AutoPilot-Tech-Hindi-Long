import os, sys, requests, json, subprocess, re, gc, time
import concurrent.futures

# --- CONFIG ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
pexels_key = os.environ.get('PEXELS_API_KEY')
bot_token = "8870266304:AAHHYfQvtQEWMIEzMfdEc7i_9hIzj7nz0Zg"
chat_id = os.environ.get('CHAT_ID')

# --- TOPIC & HASHTAG FIX ---
# Check if n8n/Make is sending the exact user prompt
exact_topic = os.environ.get('VIDEO_TOPIC') or os.environ.get('USER_PROMPT') or ""

if exact_topic and exact_topic.strip() != "":
    MAIN_TOPIC = exact_topic.strip().title()
else:
    # Fallback to AI JSON if env variable is missing
    MAIN_TOPIC = scenes_data[0].get('keyword', 'Engineering Concepts').title() if scenes_data else 'Engineering Concepts'

# Clean up hashtags to ensure no commas or special characters are included
clean_words = [re.sub(r'[^A-Za-z0-9]', '', w) for w in MAIN_TOPIC.split()]
clean_words = [w for w in clean_words if w]
topic_hash = "".join(clean_words[:3]) if clean_words else "Engineering" # Take first 3 words for hashtag

def fetch_pexels_video(keyword):
    """Smart Pexels Fetcher: Enforces HD Landscape"""
    search_terms = [keyword, topic_hash, "technology background"]
    
    for term in search_terms:
        if not term: continue
        try:
            url = f"https://api.pexels.com/videos/search?query={term}&per_page=5&orientation=landscape"
            res = requests.get(url, headers={"Authorization": pexels_key}, timeout=20).json()
            
            if 'videos' in res and len(res['videos']) > 0:
                for vid in res['videos']:
                    for file in vid['video_files']:
                        if file['quality'] == 'hd' and file['width'] >= 1280:
                            return file['link']
                return res['videos'][0]['video_files'][0]['link']
        except Exception as e:
            print(f"Pexels Fetch Error for '{term}': {e}")
    return None

def process_scene(i, scene, retry=3):
    """Scene Processing with Auto-Retry Logic"""
    for attempt in range(retry):
        try:
            gc.collect()
            audio_path = f"audio_{i}.wav"
            scene_filename = f"scene_{i}.mp4"
            raw_video = f"raw_{i}.mp4"
            
            # 1. TTS Generation
            text_clean = re.sub(r'[^\w\s.,?!-]', '', scene.get('text', '').replace('&', ' aur ')).strip()
            with open(f"temp_{i}.txt", "w", encoding="utf-8") as f: f.write(text_clean)
            subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', f"temp_{i}.txt", '--write-media', f"raw_{i}.mp3"], check=True)
            subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
            
            dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]).decode().strip())
            
            # 2. Fetch & Normalize Video
            vid_url = fetch_pexels_video(scene.get('keyword', MAIN_TOPIC))
            if vid_url:
                with open(raw_video, "wb") as f: f.write(requests.get(vid_url, timeout=30).content)
                if os.path.getsize(raw_video) > 1000:
                    subprocess.run(['ffmpeg', '-y', '-stream_loop', '-1', '-i', raw_video, '-t', str(dur), '-vf', 'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=25', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', scene_filename], check=True)
                    return {"vid": scene_filename, "aud": audio_path, "index": i}
            raise Exception("Video download failed or file corrupt")
        except Exception as e:
            print(f"Attempt {attempt+1} failed for scene {i}: {e}")
            time.sleep(2)
    return None

# --- EXECUTION ---
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(process_scene, i, scene) for i, scene in enumerate(scenes_data)]
    for f in concurrent.futures.as_completed(futures):
        res = f.result()
        if res: results.append(res)

if not results:
    print("FATAL: No valid scenes rendered.")
    sys.exit(1)

results.sort(key=lambda x: x['index'])

with open("list_v.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")
with open("list_a.txt", "w") as f:
    for r in results: f.write(f"file '{r['aud']}'\n")

# Initial Concat
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', 'v_merged.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_a.txt', '-c:a', 'pcm_s16le', 'a_merged.wav'], check=True)

# --- STUDIO PIPELINE: BGM(0.12) + POP.MP3 + AUDIO DUCKING ---
# 1. Voice split
# 2. BGM volume set to 0.12
# 3. Pop audio volume set
# 4. Ducking applied to BGM
# 5. Mix all 3 together (Voice + Ducked BGM + Pop Sound)
studio_filter = (
    "[1:a]asplit=2[voice_main][voice_control];"
    "[2:a]volume=0.12[bgm_low];"
    "[3:a]volume=0.8[pop_audio];"
    "[bgm_low][voice_control]sidechaincompress=threshold=0.05:ratio=12[ducked_bgm];"
    "[voice_main][ducked_bgm][pop_audio]amix=inputs=3:duration=first[aout];"
    "[0:v]drawtext=text='Engineering Decode':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5[vout]"
)

# Pass 1 (Video Only)
subprocess.run([
    'ffmpeg', '-y', '-i', 'v_merged.mp4',
    '-vf', "drawtext=text='Engineering Decode':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5",
    '-c:v', 'libx264', '-b:v', '2M', '-pass', '1', '-an', '-f', 'null', '/dev/null'
], check=True)

# Pass 2 (Video + Voice + BGM + Pop)
# Added '-i pop.mp3' as the 4th input [3:a]
subprocess.run([
    'ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3', '-i', 'pop.mp3',
    '-filter_complex', studio_filter,
    '-map', '[vout]', '-map', '[aout]', 
    '-c:v', 'libx264', '-pass', '2', '-b:v', '2M', '-preset', 'slow', '-c:a', 'aac', '-async', '1', '-shortest', 'final_video.mp4'
], check=True)

# --- UPLOAD & EXACT TOPIC NOTIFICATION ---
try:
    print("Uploading final video to tmpfiles...")
    upload_res = requests.post("https://tmpfiles.org/api/v1/upload", files={'file': open('final_video.mp4', 'rb')}, timeout=600).json()
    video_link = upload_res['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    
    # Restrict lengths to avoid SEO issues (RankMath: 60 for Title, 160 for Desc)
    seo_title = f"{MAIN_TOPIC} Explained in Hindi"[:60].strip()
    seo_desc = f"Learn how {MAIN_TOPIC.lower()} works in this engineering breakdown. Complete mechanism explained in Hindi."[:160].strip()
    thumb_prompt = f"Cinematic wide shot of {MAIN_TOPIC}, hyper-detailed, 8k resolution, Unreal Engine 5 render, dramatic lighting, highly intricate, technological masterpiece, no text, no CGI artifacts."
    
    # Safe hashtags without commas
    hashtags = f"#EngineeringDecode #{topic_hash} #TechHindi #EngineeringExplained"
    
    final_message = f"READY_TO_UPLOAD|{video_link}|{seo_title}|{thumb_prompt}|{seo_desc} {hashtags}"
    
    print("Sending formatted message to Telegram...")
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": final_message})

except Exception as e:
    print(f"Notification Error: {e}")
