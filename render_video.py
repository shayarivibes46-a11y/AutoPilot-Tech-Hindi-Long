import os, sys, requests, json, subprocess, re, gc, time, traceback
import concurrent.futures

# --- CONFIG & INPUT HANDLING ---
raw_scenes = os.environ.get('SCENES_DATA')
pexels_key = os.environ.get('PEXELS_API_KEY')
bot_token = "8952624775:AAFXQXosY1GIsVvWgeqWi4L2LE1LoQnPc3Q"
chat_id = os.environ.get('CHAT_ID')

# Naye environment variables fetch karein (GitHub Action se)
video_title = os.environ.get('TITLE', 'Engineering Video')
thumbnail_prompt = os.environ.get('THUMBNAIL_PROMPT', 'Cinematic engineering thumbnail')
video_desc = os.environ.get('DESCRIPTION', 'Educational video')

# Validate input
if not raw_scenes:
    print("FATAL: SCENES_DATA environment variable is missing.")
    sys.exit(1)

try:
    scenes_data = json.loads(raw_scenes)
except json.JSONDecodeError as e:
    print(f"FATAL: JSON Decode Error. Input: {raw_scenes}")
    raise e

# --- TOPIC & HASHTAG SETUP ---
# FIX: 'keyword' ko 'b_roll_visual' mein badla gaya
MAIN_TOPIC = os.environ.get('VIDEO_TOPIC', scenes_data[0].get('b_roll_visual', 'Engineering')).strip().title()
clean_words = [re.sub(r'[^A-Za-z0-9]', '', w) for w in MAIN_TOPIC.split()]
topic_hash = "".join([w for w in clean_words if w][:3])

# --- FETCH ENGINE ---
def fetch_multiple_pexels_videos(keyword, count=1):
    search_terms = [keyword, topic_hash, "technology background"]
    videos_found = []
    for term in search_terms:
        try:
            url = f"https://api.pexels.com/videos/search?query={term}&per_page=10&orientation=landscape"
            res = requests.get(url, headers={"Authorization": pexels_key}, timeout=20).json()
            if 'videos' in res:
                for vid in res['videos']:
                    for file in vid['video_files']:
                        if file['quality'] == 'hd' and file['width'] >= 1280:
                            if file['link'] not in videos_found: videos_found.append(file['link'])
                            break
                    if len(videos_found) >= count: return videos_found
        except Exception: continue
    return videos_found

# --- SCENE PROCESSING ---
def process_scene(i, scene):
    try:
        audio_path, scene_filename = f"audio_{i}.wav", f"scene_{i}.mp4"
        
        # TTS
        text_clean = re.sub(r'[^\w\s.,?!-]', '', scene.get('text', '').replace('&', ' aur ')).strip()
        with open(f"temp_{i}.txt", "w", encoding="utf-8") as f: f.write(text_clean)
        subprocess.run(['python', '-m', 'edge_tts', '--voice', 'hi-IN-MadhurNeural', '--rate=+10%', '-f', f"temp_{i}.txt", '--write-media', f"raw_{i}.mp3"], check=True)
        
        # FIX: Added normalize=0 to amix so TTS volume doesn't fluctuate when SFX plays
        audio_filter = "[1:a]volume=0.3[w];[2:a]volume=0.3,adelay=500|500[p];[0:a][w][p]amix=inputs=3:duration=first:normalize=0[aout];[aout]volume=1.2[final_aout]"
        subprocess.run([
            'ffmpeg', '-y', 
            '-i', f"raw_{i}.mp3", 
            '-i', 'whoosh.mp3', 
            '-i', 'pop.mp3', 
            '-filter_complex', audio_filter, 
            '-map', '[final_aout]', 
            '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path
        ], check=True)
        
        dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]).decode().strip())
        
        # Download & Zoom
        # FIX: 'keyword' ko 'b_roll_visual' mein badla gaya
        urls = fetch_multiple_pexels_videos(scene.get('b_roll_visual', MAIN_TOPIC))
        if not urls: raise Exception("No video found")
        
        raw_clip = f"raw_{i}.mp4"
        with open(raw_clip, "wb") as f: f.write(requests.get(urls[0], timeout=30).content)
        vf_string = "zoompan=z='min(max(zoom,pzoom)+0.001,1.1)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=25"
        subprocess.run(['ffmpeg', '-y', '-stream_loop', '-1', '-i', raw_clip, '-t', str(dur), '-vf', vf_string, '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', scene_filename], check=True)
        
        # FIX: 'keyword' ko 'b_roll_visual' mein badla gaya
        return {"vid": scene_filename, "aud": audio_path, "index": i, "dur": dur, "keyword": scene.get('b_roll_visual', MAIN_TOPIC)}
    except Exception as e:
        print(f"Scene {i} failed: {e}")
        return None

# --- MAIN EXECUTION ---
try:
    results = [res for i, scene in enumerate(scenes_data) if (res := process_scene(i, scene))]
    results.sort(key=lambda x: x['index'])

    # Merge
    with open("list_v.txt", "w") as f: [f.write(f"file '{r['vid']}'\n") for r in results]
    with open("list_a.txt", "w") as f: [f.write(f"file '{r['aud']}'\n") for r in results]
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', 'v_merged.mp4'], check=True)
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_a.txt', '-c:a', 'pcm_s16le', 'a_merged.wav'], check=True)

    # Studio Rendering - Added normalize=0 to amix to fix volume jumping
    studio_filter = "[1:a]asplit=2[voice_main][voice_control];[2:a]volume=0.45[bgm_low];[bgm_low][voice_control]sidechaincompress=threshold=0.05:ratio=12[ducked_bgm];[voice_main][ducked_bgm]amix=inputs=2:duration=first:normalize=0[aout];[0:v]drawtext=text='Decode':x=w-tw-50:y=h-th-50:fontsize=32:fontcolor=white@0.5[vout]"
    
    # Decreased -b:v to 1.2M to solve Payload Too Large error
    subprocess.run(['ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3', '-filter_complex', studio_filter, '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-b:v', '1.2M', '-preset', 'medium', '-c:a', 'aac', '-shortest', 'final_video.mp4'], check=True)

    # ==========================================
    # GITHUB RELEASES UPLOAD (NEW METHOD)
    # ==========================================
    print("\n🚀 Uploading Video directly to GitHub Releases...")
    
    run_id = os.environ.get('GITHUB_RUN_ID', str(int(time.time())))
    tag_name = f"vid-{run_id}"
    
    # Yahan "amu8085-lab/my-project1" ki jagah apne repo ka asali naam dal dena ya GitHub se environment variable ke through automatically fetch karne dena.
    repo_name = os.environ.get('GITHUB_REPOSITORY', "amu8085-lab/my-project1") 
    
    cmd = ['gh', 'release', 'create', tag_name, 'final_video.mp4', '--repo', repo_name, '--notes', 'Automated Video Render']
    
    # Synchronous subprocess run taaki baaki script ki flow bani rahe
    proc = subprocess.run(cmd, capture_output=True, text=True)
    
    if proc.returncode == 0:
        video_link = f"https://github.com/{repo_name}/releases/download/{tag_name}/final_video.mp4"
        print(f"✅ Success! Video uploaded to GitHub: {video_link}")
        
        # Safe character replacement just like the original async file
        final_msg = f"READY_TO_UPLOAD|{video_link}|{video_title.replace('|', '')}|{thumbnail_prompt.replace('|', '')}|{video_desc.replace('|', '')}"
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": final_msg})
    else:
        err_msg = proc.stderr.strip()
        print(f"❌ GitHub Release failed. Error: {err_msg}")
        raise Exception(f"Upload API Error: {err_msg}")

except Exception as e:
    error_msg = f"🚨 *PIPELINE FAILED!*\n*Error:* `{str(e)[:100]}`"
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": error_msg, "parse_mode": "Markdown"})
