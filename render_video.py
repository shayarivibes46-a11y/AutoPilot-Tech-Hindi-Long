import os, sys, requests, json, subprocess, gc, time, random
import concurrent.futures
from moviepy.editor import VideoFileClip, AudioFileClip, ColorClip
import moviepy.video.fx.all as vfx

# --- VARIABLES ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
title = os.environ.get('TITLE', 'Engineering Marvel')
description = os.environ.get('DESCRIPTION', 'Amazing tech facts in Hindi.')
thumbnail_prompt = os.environ.get('THUMBNAIL_PROMPT', 'Cinematic tech thumbnail')
pexels_key = os.environ.get('PEXELS_API_KEY')
chat_id = os.environ.get('CHAT_ID')

print(f"DEBUG: Processing {len(scenes_data)} scenes - Engineering Decode Pro Build.")

# ENGINEERING FALLBACK KEYWORDS
FALLBACK_KEYWORDS = ["technology abstract", "engineering architecture", "factory robotics", "circuit board digital"]

def fetch_pexels_video(keyword):
    queries_to_try = [f"{keyword} technology"] + FALLBACK_KEYWORDS
    for query in queries_to_try:
        for attempt in range(3):
            try:
                time.sleep(random.uniform(0.5, 1.5))
                random_page = random.randint(1, 5) 
                res = requests.get(f"https://api.pexels.com/videos/search?query={query}&per_page=5&page={random_page}&orientation=landscape", headers={"Authorization": pexels_key}, timeout=10).json()
                if res.get('videos') and len(res['videos']) > 0:
                    return random.choice(res['videos'])['video_files'][0]['link']
            except:
                time.sleep(2)
                continue
    return None

# ==========================================
# PHASE 1: RENDER SCENES (FFMPEG & FAIL-SAFE)
# ==========================================
def process_scene(i, scene):
    keyword = scene.get('keyword', 'technology')
    text_line = scene.get('text', '').strip()
    if not text_line: return None

    audio_path = os.path.abspath(f"audio_{i}.wav")
    scene_filename = os.path.abspath(f"scene_{i}.mp4")
    raw_mp3 = f"raw_a_{i}.mp3"
    temp_txt = f"temp_{i}.txt"
    vid_path = f"raw_vid_{i}.mp4"
    
    try:
        # TTS Generate
        with open(temp_txt, "w", encoding="utf-8") as f: f.write(text_line)
        subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', temp_txt, '--write-media', raw_mp3], check=True)
        subprocess.run(['ffmpeg', '-y', '-i', raw_mp3, '-ss', '0.2', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        audio_clip = AudioFileClip(audio_path)
        dur = audio_clip.duration
        audio_clip.close()
        
        vid_url = fetch_pexels_video(keyword)
        if vid_url:
            with open(vid_path, "wb") as f: f.write(requests.get(vid_url, timeout=30).content)
            clip = VideoFileClip(vid_path)
            if clip.duration < dur: clip = clip.loop(duration=dur)
            else: clip = clip.subclip(0, dur)
                
            if clip.w / clip.h > 1920 / 1080: clip = clip.resize(height=1080)
            else: clip = clip.resize(width=1920)
            clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
            clip = clip.fx(vfx.fadein, 0.5).fx(vfx.fadeout, 0.5)
            clip.write_videofile(scene_filename, fps=24, codec="libx264", audio=False, ffmpeg_params=['-pix_fmt', 'yuv420p'], logger=None)
            clip.close()
        else:
            ColorClip(size=(1920, 1080), color=(5, 5, 15), duration=dur).fx(vfx.fadein, 0.5).fx(vfx.fadeout, 0.5).write_videofile(scene_filename, fps=24, codec="libx264", audio=False, ffmpeg_params=['-pix_fmt', 'yuv420p'], logger=None)
        
        for f in [temp_txt, raw_mp3, vid_path]:
            if os.path.exists(f): os.remove(f)
        return {"vid": scene_filename, "aud": audio_path, "index": i}
    except Exception as e: return None

results = []
# GitHub Action safe multithreading
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(process_scene, i, scene) for i, scene in enumerate(scenes_data)]
    for future in concurrent.futures.as_completed(futures):
        res = future.result()
        if res: results.append(res)

results = sorted(results, key=lambda x: x['index'])
with open("vid_list.txt", "w") as f:
    for r in results: f.write(f"file '{r['vid']}'\n")
with open("aud_list.txt", "w") as f:
    for r in results: f.write(f"file '{r['aud']}'\n")

# ==========================================
# PHASE 2: FINAL MERGE & BGM
# ==========================================
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'vid_list.txt', '-c', 'copy', 'raw_merged_video.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'aud_list.txt', '-c', 'pcm_s16le', 'merged_audio.wav'], check=True)

# ADD BGM, ENGINEERING WATERMARK, NORMALIZATION
cmd = ['ffmpeg', '-y', '-i', 'raw_merged_video.mp4', '-i', 'merged_audio.wav']
if os.path.exists("bgm.mp3"):
    cmd += ['-stream_loop', '-1', '-i', 'bgm.mp3', '-filter_complex', '[0:v]eq=contrast=1.1:saturation=1.25,drawtext=text=\'Engineering Decode\':fontcolor=white@0.5:fontsize=48:x=w-tw-50:y=h-th-50[vout];[1:a]loudnorm=I=-14:TP=-2:LRA=11[norm_voice];[2:a]volume=0.08[bgm];[norm_voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]', '-map', '[vout]', '-map', '[aout]']
else:
    cmd += ['-filter_complex', '[0:v]eq=contrast=1.1:saturation=1.25,drawtext=text=\'Engineering Decode\':fontcolor=white@0.5:fontsize=48:x=w-tw-50:y=h-th-50[vout];[1:a]loudnorm=I=-14:TP=-2:LRA=11[aout]', '-map', '[vout]', '-map', '[aout]']
cmd += ['-c:v', 'libx264', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', 'final_video.mp4']
subprocess.run(cmd, check=True)

# ==========================================
# PHASE 3: MULTI-SERVER UPLOAD
# ==========================================
video_link = None
for url in ["https://litterbox.catbox.moe/resources/internals/api.php", "https://tmpfiles.org/api/v1/upload"]:
    try:
        files = {'fileToUpload' if "litterbox" in url else 'file': open("final_video.mp4", 'rb')}
        data = {'reqtype': 'fileupload', 'time': '12h'} if "litterbox" in url else None
        res = requests.post(url, files=files, data=data, timeout=600)
        if "litterbox" in url and res.status_code == 200 and res.text.startswith("http"): video_link = res.text.strip()
        elif "tmpfiles" in url and res.json().get('status') == 'success': video_link = res.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
        if video_link: break
    except: continue

# ==========================================
# PHASE 4: TELEGRAM NOTIFICATION
# ==========================================
# APNA TELEGRAM BOT TOKEN YAHAN DAALEIN:
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE" 

if video_link:
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": f"READY_TO_UPLOAD|{video_link}|{title.replace('|', '')}|{thumbnail_prompt.replace('|', '')}|{description.replace('|', '')}"})
else:
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": f"⚠️ ERROR: Upload fail hua, GitHub Actions check karein."})
