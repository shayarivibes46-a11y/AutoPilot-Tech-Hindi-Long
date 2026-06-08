import os, sys, requests, json, subprocess, time, random, re
import concurrent.futures
from PIL import Image
# Compatibility patch for Pillow/MoviePy
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from moviepy.editor import VideoFileClip, AudioFileClip, ColorClip
import moviepy.video.fx.all as vfx

# --- VARIABLES ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
title = os.environ.get('TITLE', 'Engineering Marvel')
description = os.environ.get('DESCRIPTION', 'Amazing tech facts.')
thumbnail_prompt = os.environ.get('THUMBNAIL_PROMPT', 'Cinematic tech thumbnail')
pexels_key = os.environ.get('PEXELS_API_KEY')
chat_id = os.environ.get('CHAT_ID')

def clean_text_for_tts(text):
    # Emojis aur weird chars hatao jo Edge-TTS crash karte hain
    safe_text = re.sub(r'[^\w\s.,?!-]', '', text.replace('&', ' aur '))
    return safe_text.strip()

def fetch_pexels_video(keyword):
    try:
        res = requests.get(f"https://api.pexels.com/videos/search?query={keyword} technology&per_page=3&orientation=landscape", headers={"Authorization": pexels_key}, timeout=10).json()
        if res.get('videos'): return random.choice(res['videos'])['video_files'][0]['link']
    except: return None
    return None

# ==========================================
# PHASE 1: RENDER SCENES
# ==========================================
def process_scene(i, scene):
    text_line = clean_text_for_tts(scene.get('text', ''))
    audio_path = f"audio_{i}.wav"
    scene_filename = f"scene_{i}.mp4"
    
    try:
        # TTS generation with retry
        with open(f"temp_{i}.txt", "w", encoding="utf-8") as f: f.write(text_line)
        for attempt in range(3):
            try:
                subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', f"temp_{i}.txt", '--write-media', f"raw_{i}.mp3"], check=True)
                subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
                if os.path.exists(audio_path): break
            except: time.sleep(2)
        
        dur = AudioFileClip(audio_path).duration
        vid_url = fetch_pexels_video(scene.get('keyword', 'technology'))
        
        if vid_url:
            with open(f"raw_{i}.mp4", "wb") as f: f.write(requests.get(vid_url, timeout=30).content)
            clip = VideoFileClip(f"raw_{i}.mp4").loop(duration=dur).resize(height=720).crop(x_center=640, y_center=360, width=1280, height=720)
            clip.write_videofile(scene_filename, fps=24, codec="libx264", audio=False, ffmpeg_params=['-pix_fmt', 'yuv420p'], logger=None)
            clip.close()
        else:
            ColorClip(size=(1280, 720), color=(0, 0, 0), duration=dur).write_videofile(scene_filename, fps=24, codec="libx264", audio=False, ffmpeg_params=['-pix_fmt', 'yuv420p'], logger=None)
        
        return {"vid": scene_filename, "aud": audio_path, "index": i}
    except Exception as e:
        print(f"Error scene {i}: {e}")
        return None

results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(process_scene, i, scene) for i, scene in enumerate(scenes_data)]
    for f in concurrent.futures.as_completed(futures):
        if f.result(): results.append(f.result())

if not results: sys.exit(1)
results.sort(key=lambda x: x['index'])

# ==========================================
# PHASE 2: MERGE & BGM
# ==========================================
with open("list.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")

# Concatenate videos
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list.txt', '-c', 'copy', 'merged.mp4'], check=True)
# Add BGM and Watermark
subprocess.run(['ffmpeg', '-y', '-i', 'merged.mp4', '-i', results[0]['aud'], '-filter_complex', '[0:v]eq=contrast=1.1:saturation=1.25,drawtext=text=\'Engineering Decode\':fontcolor=white@0.5:fontsize=48:x=w-tw-50:y=h-th-50[vout];[1:a]loudnorm[a]', '-map', '[vout]', '-map', '[a]', '-c:v', 'libx264', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', 'final_video.mp4'], check=True)

# ==========================================
# PHASE 3: UPLOAD & TELEGRAM
# ==========================================
video_link = None
try:
    res = requests.post("https://tmpfiles.org/api/v1/upload", files={'file': open('final_video.mp4', 'rb')}, timeout=600).json()
    if res.get('status') == 'success': video_link = res['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
except: pass

token = "8870266304:AAHHYfQvtQEWMIEzMfdEc7i_9hIzj7nz0Zg"
msg = f"READY_TO_UPLOAD|{video_link}|{title[:60]}|{thumbnail_prompt[:500]}|{description[:157]}" if video_link else "⚠️ Upload Failed."
requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": msg})
