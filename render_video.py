import os, sys, requests, json, subprocess, time, random, re
import concurrent.futures
from PIL import Image
if not hasattr(Image, 'ANTIALIAS'): Image.ANTIALIAS = Image.Resampling.LANCZOS

# --- VARIABLES ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
title = os.environ.get('TITLE', 'Engineering Marvel')
description = os.environ.get('DESCRIPTION', 'Amazing tech facts.')
pexels_key = os.environ.get('PEXELS_API_KEY')
chat_id = os.environ.get('CHAT_ID')

def clean_text_for_tts(text):
    # Sirf alphanumeric, space, dot, comma, exclamation aur dash allow karein
    return re.sub(r'[^\w\s.,?!-]', '', text.replace('&', ' aur ')).strip()

def process_scene(i, scene):
    text_line = clean_text_for_tts(scene.get('text', ''))
    audio_path = f"audio_{i}.wav"
    scene_filename = f"scene_{i}.mp4"
    
    try:
        # TTS generation with strict cleanup
        with open(f"temp_{i}.txt", "w", encoding="utf-8") as f: f.write(text_line)
        subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', f"temp_{i}.txt", '--write-media', f"raw_{i}.mp3"], check=True)
        subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
        
        # Audio duration check
        dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]).decode().strip())
        fade_out_start = max(0, dur - 0.5)
        
        # Native FFmpeg Video Render
        # Pexels logic...
        subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1280x720', '-t', str(dur), '-vf', f'fade=t=in:st=0:d=0.5,fade=t=out:st={fade_out_start}:d=0.5', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', scene_filename], check=True)
        
        return {"vid": scene_filename, "aud": audio_path, "index": i}
    except Exception as e:
        print(f"Error scene {i}: {e}")
        return None

# --- RUN EXECUTION ---
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(process_scene, i, scene) for i, scene in enumerate(scenes_data)]
    for f in concurrent.futures.as_completed(futures):
        if f.result(): results.append(f.result())

if not results: sys.exit(1)
results.sort(key=lambda x: x['index'])

# --- MERGE & DUCKING (FFMPEG PRO-VERSION) ---
with open("list_v.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")
with open("list_a.txt", "w") as f:
    for r in results: f.write(f"file '{r['aud']}'\n")

subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c', 'copy', 'v_merged.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_a.txt', '-c', 'pcm_s16le', 'a_merged.wav'], check=True)

# Final Merge with explicit asplit=2 fix
subprocess.run([
    'ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3',
    '-filter_complex', '[1:a]asplit=2[v_aud][sidechain];[sidechain]sidechaincompress=threshold=0.03:ratio=20[ducked];[2:a][ducked]amix=inputs=2:duration=first[aout];[0:v]drawtext=text=\'Engineering Decode\':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5[vout]',
    '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', 'final_video.mp4'
], check=True)
