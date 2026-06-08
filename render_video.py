import os, sys, requests, json, subprocess, time, random, re
import concurrent.futures
from PIL import Image

# Fix: Pillow compatibility patch
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from moviepy.editor import AudioFileClip

# --- VARIABLES ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
title = os.environ.get('TITLE', 'Engineering Marvel')
description = os.environ.get('DESCRIPTION', 'Amazing tech facts.')
pexels_key = os.environ.get('PEXELS_API_KEY')
chat_id = os.environ.get('CHAT_ID')

def clean_text_for_tts(text):
    return re.sub(r'[^\w\s.,?!-]', '', text.replace('&', ' aur ')).strip()

def process_scene(i, scene):
    text_line = clean_text_for_tts(scene.get('text', ''))
    audio_path = f"audio_{i}.wav"
    scene_filename = f"scene_{i}.mp4"
    
    try:
        # TTS generation
        temp_txt = f"temp_{i}.txt"
        with open(temp_txt, "w", encoding="utf-8") as f: f.write(text_line)
        subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', temp_txt, '--write-media', f"raw_{i}.mp3"], check=True)
        subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
        
        # Determine duration safely
        dur = AudioFileClip(audio_path).duration
        fade_out_start = max(0, dur - 0.5)
        
        # Pexels Video Fetch
        vid_path = f"raw_{i}.mp4"
        vid_url = None # (Assuming fetch logic here...)
        
        # Native FFmpeg Video Render (No MoviePy RAM load)
        if vid_url:
            with open(vid_path, "wb") as f: f.write(requests.get(vid_url, timeout=30).content)
            # PRO-TIP: Fade filter string is now formatted for FFmpeg
            vf_filter = f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fade=t=in:st=0:d=0.5,fade=t=out:st={fade_out_start}:d=0.5"
            subprocess.run(['ffmpeg', '-y', '-i', vid_path, '-t', str(dur), '-vf', vf_filter, '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', scene_filename], check=True)
        else:
            subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1280x720', '-t', str(dur), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', scene_filename], check=True)
        
        return {"vid": scene_filename, "aud": audio_path, "index": i}
    except Exception as e:
        print(f"Error scene {i}: {e}")
        return None

# --- EXECUTION ---
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(process_scene, i, scene) for i, scene in enumerate(scenes_data)]
    for f in concurrent.futures.as_completed(futures):
        if f.result(): results.append(f.result())

if not results: sys.exit(1)
results.sort(key=lambda x: x['index'])

# --- MERGE & DUCKING ---
with open("list_v.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")
with open("list_a.txt", "w") as f:
    for r in results: f.write(f"file '{r['aud']}'\n")

subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c', 'copy', 'v_merged.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_a.txt', '-c', 'pcm_s16le', 'a_merged.wav'], check=True)

# Final Merge with Ducking & Watermark
subprocess.run([
    'ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3',
    '-filter_complex', '[1:a]asplit[v_aud][sidechain];[sidechain]sidechaincompress=threshold=0.03:ratio=20[ducked];[2:a][ducked]amix=inputs=2:duration=first[aout];[0:v]drawtext=text=\'Engineering Decode\':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5[vout]',
    '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', 'final_video.mp4'
], check=True)

# --- UPLOAD & NOTIFY ---
# (Upload logic as before)
