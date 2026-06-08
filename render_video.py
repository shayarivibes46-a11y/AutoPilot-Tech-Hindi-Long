import os, sys, requests, json, subprocess, re, gc
import concurrent.futures

# --- CONFIG ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
bot_token = "8870266304:AAHHYfQvtQEWMIEzMfdEc7i_9hIzj7nz0Zg"
chat_id = os.environ.get('CHAT_ID')

def process_scene(i, scene):
    gc.collect()
    audio_path = f"audio_{i}.wav"
    scene_filename = f"scene_{i}.mp4"
    
    # 1. TTS Generation
    text_clean = re.sub(r'[^\w\s.,?!-]', '', scene.get('text', '').replace('&', ' aur ')).strip()
    with open(f"temp_{i}.txt", "w", encoding="utf-8") as f: f.write(text_clean)
    subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', f"temp_{i}.txt", '--write-media', f"raw_{i}.mp3"], check=True)
    subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
    
    dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]).decode().strip())
    
    # 2. Stable Render (Forced h264 for compatibility)
    subprocess.run([
        'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1280x720', 
        '-t', str(dur), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', scene_filename
    ], check=True)
    
    return {"vid": scene_filename, "aud": audio_path, "index": i}

# --- EXECUTION & MERGE ---
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(process_scene, i, scene) for i, scene in enumerate(scenes_data)]
    for f in concurrent.futures.as_completed(futures):
        if f.result(): results.append(f.result())
results.sort(key=lambda x: x['index'])

# --- STABLE MERGE ---
with open("list_v.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")
with open("list_a.txt", "w") as f:
    for r in results: f.write(f"file '{r['aud']}'\n")

# Use re-encoding (no copy) to ensure video stream is valid
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', 'v_merged.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_a.txt', '-c:a', 'pcm_s16le', 'a_merged.wav'], check=True)

# Final Merge with explicit audio sync
subprocess.run([
    'ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3',
    '-filter_complex', '[1:a]volume=1.0[a_voice];[2:a]volume=0.2[a_bgm];[a_voice][a_bgm]amix=inputs=2:duration=first[aout];[0:v]drawtext=text=\'Engineering Decode\':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5[vout]',
    '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-c:a', 'aac', 'final_video.mp4'
], check=True)
