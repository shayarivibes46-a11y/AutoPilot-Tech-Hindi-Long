import os, sys, requests, json, subprocess, re, gc
import concurrent.futures

# --- CONFIG ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
pexels_key = os.environ.get('PEXELS_API_KEY')
bot_token = "8870266304:AAHHYfQvtQEWMIEzMfdEc7i_9hIzj7nz0Zg"
chat_id = os.environ.get('CHAT_ID')

def fetch_pexels_video(keyword):
    try:
        url = f"https://api.pexels.com/videos/search?query={keyword}&per_page=1"
        res = requests.get(url, headers={"Authorization": pexels_key}, timeout=20).json()
        if 'videos' in res and len(res['videos']) > 0:
            return res['videos'][0]['video_files'][0]['link']
    except Exception as e:
        print(f"Pexels Fetch Error: {e}")
    return None

def process_scene(i, scene):
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
    
    # 2. Fetch and Verify Video
    vid_url = fetch_pexels_video(scene.get('keyword', 'technology'))
    if vid_url:
        with open(raw_video, "wb") as f: f.write(requests.get(vid_url, timeout=30).content)
        # Verify file is not empty
        if os.path.getsize(raw_video) > 1000:
            subprocess.run(['ffmpeg', '-y', '-i', raw_video, '-t', str(dur), '-vf', 'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=25', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', scene_filename], check=True)
        else:
            raise Exception("Corrupt Video Download")
    else:
        raise Exception("Video Fetch Failed")
    
    return {"vid": scene_filename, "aud": audio_path, "index": i}

# --- EXECUTION & MERGE ---
results = []
# Using 1 worker to ensure stability in low memory environment
for i, scene in enumerate(scenes_data):
    try:
        res = process_scene(i, scene)
        results.append(res)
    except Exception as e:
        print(f"Skipping scene {i} due to error: {e}")

if not results:
    print("FATAL: No valid scenes rendered.")
    sys.exit(1)

# Generate list files
with open("list_v.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")
with open("list_a.txt", "w") as f:
    for r in results: f.write(f"file '{r['aud']}'\n")

# Merging with re-encoding
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', 'v_merged.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_a.txt', '-c:a', 'pcm_s16le', 'a_merged.wav'], check=True)

# Final Render
subprocess.run([
    'ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3',
    '-filter_complex', '[1:a]loudnorm[a_norm];[2:a]volume=0.05[a_bgm];[a_norm][a_bgm]amix=inputs=2:duration=first[aout];[0:v]drawtext=text=\'Engineering Decode\':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5[vout]',
    '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', 'final_video.mp4'
], check=True)

# Notify
try:
    res = requests.post("https://tmpfiles.org/api/v1/upload", files={'file': open('final_video.mp4', 'rb')}, timeout=600).json()
    link = res['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": f"✅ Ready! {link}"})
except: pass
