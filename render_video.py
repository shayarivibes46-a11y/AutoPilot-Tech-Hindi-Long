import os, sys, requests, json, subprocess, gc, time, random, re
import concurrent.futures
from moviepy.editor import VideoFileClip, AudioFileClip, ColorClip
import moviepy.video.fx.all as vfx

# --- VARIABLES ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
title = os.environ.get('TITLE', 'Engineering Marvel')
description = os.environ.get('DESCRIPTION', 'Amazing tech facts.')
thumbnail_prompt = os.environ.get('THUMBNAIL_PROMPT', 'Cinematic tech thumbnail')
pexels_key = os.environ.get('PEXELS_API_KEY')
chat_id = os.environ.get('CHAT_ID')

print(f"DEBUG: Processing {len(scenes_data)} scenes.")

FALLBACK_KEYWORDS = ["technology abstract", "engineering architecture", "factory robotics", "circuit board digital"]

def fetch_pexels_video(keyword):
    queries_to_try = [f"{keyword} technology"] + FALLBACK_KEYWORDS
    for query in queries_to_try:
        try:
            res = requests.get(f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=landscape", headers={"Authorization": pexels_key}, timeout=10).json()
            if res.get('videos'): return random.choice(res['videos'])['video_files'][0]['link']
        except: continue
    return None

def clean_text(text):
    return re.sub(r'[^\w\s.,?!-]', '', text.replace('&', ' aur ').strip())

# ==========================================
# PHASE 1: RENDER SCENES
# ==========================================
def process_scene(i, scene):
    text_line = clean_text(scene.get('text', ''))
    audio_path = os.path.realpath(f"audio_{i}.wav")
    scene_filename = os.path.realpath(f"scene_{i}.mp4")
    
    try:
        # TTS
        temp_txt = f"temp_{i}.txt"
        with open(temp_txt, "w", encoding="utf-8") as f: f.write(text_line)
        subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', temp_txt, '--write-media', f"raw_{i}.mp3"], check=True)
        subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ss', '0.2', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
        
        dur = AudioFileClip(audio_path).duration
        vid_url = fetch_pexels_video(scene.get('keyword', 'technology'))
        
        if vid_url:
            vid_path = f"raw_{i}.mp4"
            with open(vid_path, "wb") as f: f.write(requests.get(vid_url, timeout=30).content)
            clip = VideoFileClip(vid_path).loop(duration=dur).resize(height=720).crop(x_center=640, y_center=360, width=1280, height=720).fx(vfx.fadein, 0.5).fx(vfx.fadeout, 0.5)
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
# PHASE 2: MERGE (SAFE CONCAT)
# ==========================================
with open("list.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")

# Use FFmpeg to concat without Python-MoviePy overhead
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list.txt', '-c', 'copy', 'merged.mp4'], check=True)

# Add BGM & Normalization
subprocess.run(['ffmpeg', '-y', '-i', 'merged.mp4', '-i', 'audio_0.wav', '-filter_complex', '[1:a]loudnorm[a]', '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', 'final_video.mp4'], check=True)

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
