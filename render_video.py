import os, sys, requests, json, subprocess, re, gc, time, traceback
import concurrent.futures

# --- CONFIG ---
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
pexels_key = os.environ.get('PEXELS_API_KEY')
bot_token = "8870266304:AAHHYfQvtQEWMIEzMfdEc7i_9hIzj7nz0Zg"
chat_id = os.environ.get('CHAT_ID')

# --- TOPIC & HASHTAG SETUP ---
exact_topic = os.environ.get('VIDEO_TOPIC') or os.environ.get('USER_PROMPT') or ""
if exact_topic and exact_topic.strip() != "":
    MAIN_TOPIC = exact_topic.strip().title()
else:
    MAIN_TOPIC = scenes_data[0].get('keyword', 'Engineering Concepts').title() if scenes_data else 'Engineering Concepts'

clean_words = [re.sub(r'[^A-Za-z0-9]', '', w) for w in MAIN_TOPIC.split()]
clean_words = [w for w in clean_words if w]
topic_hash = "".join(clean_words[:3]) if clean_words else "Engineering"

# --- MULTI-CLIP FETCH ENGINE ---
def fetch_multiple_pexels_videos(keyword, count=2):
    """Fetches multiple videos per scene to prevent boring loops"""
    search_terms = [keyword, topic_hash, "technology background"]
    videos_found = []
    
    for term in search_terms:
        if not term: continue
        try:
            url = f"https://api.pexels.com/videos/search?query={term}&per_page=10&orientation=landscape"
            res = requests.get(url, headers={"Authorization": pexels_key}, timeout=20).json()
            
            if 'videos' in res and len(res['videos']) > 0:
                for vid in res['videos']:
                    for file in vid['video_files']:
                        if file['quality'] == 'hd' and file['width'] >= 1280:
                            if file['link'] not in videos_found:
                                videos_found.append(file['link'])
                            break 
                    if len(videos_found) >= count:
                        return videos_found
        except Exception as e:
            print(f"Pexels Fetch Error for '{term}': {e}")
            
    return videos_found

def process_scene(i, scene, retry=3):
    """Scene Processing with Ken Burns Zoom & Auto-Captions"""
    for attempt in range(retry):
        try:
            gc.collect()
            audio_path = f"audio_{i}.wav"
            scene_filename = f"scene_{i}.mp4"
            subtitle_file = f"sub_{i}.vtt"
            clip_list_txt = f"clips_{i}.txt"
            base_vid = f"base_{i}.mp4"
            
            # 1. TTS & Subtitle Generation
            text_clean = re.sub(r'[^\w\s.,?!-]', '', scene.get('text', '').replace('&', ' aur ')).strip()
            with open(f"temp_{i}.txt", "w", encoding="utf-8") as f: f.write(text_clean)
            
            subprocess.run([
                sys.executable, '-m', 'edge_tts', 
                '--voice', 'hi-IN-MadhurNeural', 
                '--rate=+10%', 
                '-f', f"temp_{i}.txt", 
                '--write-media', f"raw_{i}.mp3",
                '--write-subtitles', subtitle_file
            ], check=True)
            
            subprocess.run(['ffmpeg', '-y', '-i', f"raw_{i}.mp3", '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', audio_path], check=True)
            dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]).decode().strip())
            
            # 2. Fetch Multiple Videos
            urls = fetch_multiple_pexels_videos(scene.get('keyword', MAIN_TOPIC), count=2)
            if not urls:
                raise Exception("No videos found for this scene")
                
            clip_files = []
            for idx, url in enumerate(urls):
                raw_clip = f"raw_{i}_{idx}.mp4"
                norm_clip = f"norm_{i}_{idx}.mp4"
                with open(raw_clip, "wb") as f: f.write(requests.get(url, timeout=30).content)
                if os.path.getsize(raw_clip) > 1000:
                    subprocess.run(['ffmpeg', '-y', '-i', raw_clip, '-vf', 'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=25', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', norm_clip], check=True)
                    clip_files.append(norm_clip)
                    
            if not clip_files:
                raise Exception("Corrupt videos downloaded")
                
            with open(clip_list_txt, "w") as f:
                for c in clip_files: f.write(f"file '{c}'\n")
            subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', clip_list_txt, '-c', 'copy', base_vid], check=True)
            
            # 3. Apply Ken Burns Zoom & Subtitles
            # Zoompan filter slowly zooms in to 110% over time
            sub_style = "FontName=Arial,FontSize=26,PrimaryColour=&H00FFFF&,OutlineColour=&H000000&,Outline=2,Shadow=1,Bold=1,Alignment=2,MarginV=40"
            vf_string = f"zoompan=z='min(max(zoom,pzoom)+0.001,1.1)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=25,subtitles={subtitle_file}:force_style='{sub_style}'"
            
            subprocess.run(['ffmpeg', '-y', '-stream_loop', '-1', '-i', base_vid, '-t', str(dur), '-vf', vf_string, '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', scene_filename], check=True)
            
            # Return duration and keyword for Timestamp Generation
            return {"vid": scene_filename, "aud": audio_path, "index": i, "dur": dur, "keyword": scene.get('keyword', MAIN_TOPIC)}
            
        except Exception as e:
            print(f"Attempt {attempt+1} failed for scene {i}: {e}")
            time.sleep(2)
    return None

try:
    # --- EXECUTION ---
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(process_scene, i, scene) for i, scene in enumerate(scenes_data)]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: results.append(res)

    if not results:
        raise Exception("FATAL: No valid scenes rendered.")

    results.sort(key=lambda x: x['index'])

    # --- AUTO-TIMESTAMPS (YOUTUBE CHAPTERS) GENERATION ---
    chapters_str = "⏱️ **Video Chapters:**\n"
    current_time = 0.0
    for i, r in enumerate(results):
        mins = int(current_time // 60)
        secs = int(current_time % 60)
        topic_name = r['keyword'].title()
        
        if i == 0:
            chapters_str += f"00:00 - Introduction to {MAIN_TOPIC}\n"
        else:
            chapters_str += f"{mins:02d}:{secs:02d} - {topic_name}\n"
            
        current_time += r['dur']

    # Generate File Lists
    with open("list_v.txt", "w") as f:
        for r in results: f.write(f"file '{r['vid']}'\n")
    with open("list_a.txt", "w") as f:
        for r in results: f.write(f"file '{r['aud']}'\n")

    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_v.txt', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', 'v_merged.mp4'], check=True)
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'list_a.txt', '-c:a', 'pcm_s16le', 'a_merged.wav'], check=True)

    # --- STUDIO PIPELINE: AUDIO DUCKING ---
    studio_filter = (
        "[1:a]asplit=2[voice_main][voice_control];"
        "[2:a]volume=0.12[bgm_low];"
        "[3:a]volume=0.8[pop_audio];"
        "[bgm_low][voice_control]sidechaincompress=threshold=0.05:ratio=12[ducked_bgm];"
        "[voice_main][ducked_bgm][pop_audio]amix=inputs=3:duration=first[aout];"
        "[0:v]drawtext=text='Engineering Decode':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5[vout]"
    )

    subprocess.run([
        'ffmpeg', '-y', '-i', 'v_merged.mp4',
        '-vf', "drawtext=text='Engineering Decode':x=w-tw-50:y=h-th-50:fontsize=48:fontcolor=white@0.5",
        '-c:v', 'libx264', '-b:v', '2M', '-pass', '1', '-an', '-f', 'null', '/dev/null'
    ], check=True)

    subprocess.run([
        'ffmpeg', '-y', '-i', 'v_merged.mp4', '-i', 'a_merged.wav', '-stream_loop', '-1', '-i', 'bgm.mp3', '-i', 'pop.mp3',
        '-filter_complex', studio_filter,
        '-map', '[vout]', '-map', '[aout]', 
        '-c:v', 'libx264', '-pass', '2', '-b:v', '2M', '-preset', 'slow', '-c:a', 'aac', '-async', '1', '-shortest', 'final_video.mp4'
    ], check=True)

    # --- UPLOAD & NOTIFICATION ---
    print("Uploading final video to tmpfiles...")
    upload_res = requests.post("https://tmpfiles.org/api/v1/upload", files={'file': open('final_video.mp4', 'rb')}, timeout=600).json()
    video_link = upload_res['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    
    seo_title = f"{MAIN_TOPIC} Explained in Hindi"[:60].strip()
    seo_desc = f"Learn how {MAIN_TOPIC.lower()} works in this engineering breakdown. Complete mechanism explained in Hindi."[:160].strip()
    thumb_prompt = f"Cinematic wide shot of {MAIN_TOPIC}, hyper-detailed, 8k resolution, Unreal Engine 5 render, dramatic lighting, highly intricate, technological masterpiece, no text, no CGI artifacts."
    hashtags = f"#EngineeringDecode #{topic_hash} #TechHindi #EngineeringExplained"
    disclaimer = "Disclaimer: All visual elements used in this video are legally sourced and heavily edited to create original, transformative educational content under Fair Use."
    
    # Combining everything logically for YouTube formatting
    full_description = f"{seo_desc}\n\n{chapters_str}\n{hashtags}\n\n{disclaimer}"
    final_message = f"READY_TO_UPLOAD|{video_link}|{seo_title}|{thumb_prompt}|{full_description}"
    
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": final_message})

except Exception as e:
    # --- SMART FAILURE NOTIFICATION ---
    error_details = traceback.format_exc()
    error_msg = f"🚨 *PIPELINE FAILED!*\n\n*Topic:* {MAIN_TOPIC}\n*Error Message:* `{str(e)}`\n\n_Check GitHub Actions for full logs._"
    print(f"Pipeline Error: {error_details}")
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": error_msg, "parse_mode": "Markdown"})
