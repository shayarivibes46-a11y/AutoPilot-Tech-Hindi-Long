import os, sys, requests, json, subprocess, time, re, gc
import concurrent.futures

# --- CONFIG ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
bot_token = "8870266304:AAHHYfQvtQEWMIEzMfdEc7i_9hIzj7nz0Zg"
chat_id = os.environ.get('CHAT_ID')

def process_scene(i, scene):
    gc.collect()
    audio_path = f"audio_{i}.wav"
    norm_video = f"norm_{i}.mp4"
    
    # 1. TTS Generation
    text_clean = re.sub(r'[^\w\s.,?!-]', '', scene.get('text', '').replace('&', ' aur ')).strip()
    with open(f"temp_{i}.txt", "w", encoding="utf-8") as f: f.write(text_clean)
    subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', f"temp_{i}.txt", '--write-media', f"raw_{i}.mp3"], check=True)
    subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
    
    # 2. Fetch & Normalize Video (1280x720, 25fps)
    dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]).decode().strip())
    vid_url = "URL_FETCH_LOGIC" # Pexels fetcher
    vf = 'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=25'
    subprocess.run(['ffmpeg', '-y', '-i', vid_url, '-t', str(dur), '-vf', vf, '-c:v', 'libx264', '-preset', 'slow', '-pix_fmt', 'yuv420p', norm_video], check=True)
    
    return {"vid": norm_video, "aud": audio_path, "index": i}

# --- EXECUTION & STUDIO MERGE ---
# results gathering logic...
results.sort(key=lambda x: x['index'])

# 1. Concat Video & Audio
with open("list_v.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c', 'copy', 'v_merged.mp4'], check=True)

# 2. Studio Quality Final Merge
# loudnorm (Audio) + libx264 preset=slow (Video) + crf=18 (Quality)
subprocess.run([
    'ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3',
    '-filter_complex', 
    '[1:a]loudnorm[a_norm];[a_norm][2:a]amix=inputs=2:duration=first[aout];[0:v]drawtext=text=\'Engineering Decode\':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5[vout]',
    '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', 'final_video.mp4'
], check=True)

# 3. Notification
try:
    res = requests.post("https://tmpfiles.org/api/v1/upload", files={'file': open('final_video.mp4', 'rb')}, timeout=600).json()
    link = res['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": f"🎬 Engineering Decode: Studio Quality Video ready!\n{link}"})
except: pass
