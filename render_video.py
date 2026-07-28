import os
import sys
import json
import subprocess
import time
import asyncio
import re
import aiohttp
import edge_tts

# --- CONFIGURATIONS ---
title = str(os.environ.get('TITLE', 'Engineering Video')).replace('|', '-')
description = str(os.environ.get('DESCRIPTION', 'Educational video')).replace('|', '-')
thumbnail_prompt = str(os.environ.get('THUMBNAIL_PROMPT', 'Cinematic engineering thumbnail')).replace('|', '-')

pexels_key = os.environ.get('PEXELS_API_KEY')
chat_id = os.environ.get('CHAT_ID')
telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')

# Concurrency limiter: Changed to 2 to prevent GitHub Actions CPU Overload & "No space left" error
MAX_CONCURRENT_SCENES = 2 
semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCENES)

def load_scenes_data():
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, 'r', encoding='utf-8') as f:
                event_data = json.load(f)
                raw_scenes = event_data.get('client_payload', {}).get('scenes_data')
                if raw_scenes:
                    return json.loads(raw_scenes) if isinstance(raw_scenes, str) else raw_scenes
        except Exception as e:
            print(f"DEBUG: Error reading from GITHUB_EVENT_PATH: {e}")

    try:
        return json.loads(os.environ.get('SCENES_DATA', '[]'))
    except:
        return []

def get_audio_duration(file_path):
    """Helper function to get precise audio duration to prevent FFmpeg loop hangs."""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"Error getting audio duration: {e}")
        return 5.0 # Fallback 5 seconds

async def generate_tts(text, output_path, voice="hi-IN-MadhurNeural"):
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"ERROR TTS: {e}")
        return False

async def fetch_pexels_video(session, query, output_path):
    if not pexels_key: return False
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=3&orientation=portrait"
    try:
        async with session.get(url, headers={"Authorization": pexels_key}) as resp:
            if resp.status == 200:
                data = await resp.json()
                videos = data.get('videos', [])
                if videos:
                    # Get HD link
                    files = videos[0].get('video_files', [])
                    link = next((vf['link'] for vf in files if vf.get('quality') == 'hd'), None)
                    if not link and files: link = files[0]['link']
                    
                    if link:
                        async with session.get(link) as vid_resp:
                            with open(output_path, 'wb') as f:
                                f.write(await vid_resp.read())
                        return True
    except Exception as e:
        print(f"Pexels fetch failed: {e}")
    return False

async def process_scene(index, scene, session):
    async with semaphore: # Limit parallel execution to save disk space & CPU
        scene_id = index + 1
        raw_text = str(scene.get('text', '')).strip()
        search_query = scene.get('search_query', scene.get('keyword', 'technology'))
        
        text_line = re.sub(r'[^\w\s.,?!।\-\u0900-\u097F\u200d\u200c]', '', raw_text)
        
        audio_file = f"audio_{scene_id}.mp3"
        video_file = f"video_{scene_id}.mp4"
        merged_video = f"merged_{scene_id}.mp4"
        
        print(f"\n--- Processing Scene {scene_id} ---")
        
        # 1. Generate TTS
        if not await generate_tts(text_line, audio_file): return None
            
        # 2. Fetch Video
        if not await fetch_pexels_video(session, search_query, video_file):
            subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:r=30', '-t', '10', video_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        # 3. Merge Audio and Video
        print(f"Merging Video and Audio for Scene {scene_id}...")
        
        # Calculate accurate duration to prevent FFmpeg infinite loops
        audio_duration = get_audio_duration(audio_file)
        
        cmd_merge = [
            'ffmpeg', '-y', 
            '-stream_loop', '-1', 
            '-i', video_file, 
            '-i', audio_file, 
            '-t', str(audio_duration),        # Using precise duration instead of -shortest
            '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30', # Scale fix to prevent concat issues
            '-c:v', 'libx264',                # Re-encoding to match formats
            '-preset', 'ultrafast',           # Added for speed
            '-crf', '28',                     # Added for consistent compression
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', 
            '-ar', '44100',
            '-ac', '2',
            '-map', '0:v:0', 
            '-map', '1:a:0', 
            merged_video
        ]
        subprocess.run(cmd_merge, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 4. STORAGE FIX: Delete raw files immediately after merging
        if os.path.exists(audio_file): os.remove(audio_file)
        if os.path.exists(video_file): os.remove(video_file)
            
        return { 'video': merged_video }

async def upload_to_github_release(file_path):
    gh_token = os.environ.get('GH_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY')
    if not gh_token or not repo: return None
        
    tag_name = f"vid-{int(time.time())}"
    create_url = f"https://api.github.com/repos/{repo}/releases"
    headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(create_url, headers=headers, json={"tag_name": tag_name, "name": tag_name}) as resp:
            if resp.status not in [201, 200]: return None
            release_data = await resp.json()
            upload_url = release_data.get('upload_url', '').split('{')[0] + f"?name=final_video.mp4"
            
        print("Uploading MP4 to GitHub Release...")
        headers['Content-Type'] = 'video/mp4'
        with open(file_path, 'rb') as f:
            async with session.post(upload_url, headers=headers, data=f.read()) as asset_resp:
                if asset_resp.status in [201, 200]:
                    return (await asset_resp.json()).get('browser_download_url')
    return None

async def send_to_telegram(video_url):
    if not telegram_token or not chat_id: return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    
    # Text format required by n8n Router
    message_text = f"READY_TO_UPLOAD|{video_url}|{title}|{thumbnail_prompt}|{description}"
    payload = {"chat_id": chat_id, "text": message_text}
    
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)
        print("✅ n8n webhook text trigger sent to Telegram!")

async def main():
    scenes_data = load_scenes_data()
    if not scenes_data: sys.exit(1)
        
    print(f"DEBUG: Processing {len(scenes_data)} scenes...")
    
    async with aiohttp.ClientSession() as session:
        tasks = [process_scene(i, scene, session) for i, scene in enumerate(scenes_data)]
        results = await asyncio.gather(*tasks)
        
    valid_scenes = [r for r in results if r is not None]
    
    if valid_scenes:
        print("🎬 Merging all scenes into final video...")
        concat_file = "concat_list.txt"
        final_video = "final_output.mp4"
        
        with open(concat_file, "w", encoding="utf-8") as f:
            for scene in valid_scenes:
                f.write(f"file '{scene['video']}'\n")
        
        subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_file, '-c', 'copy', final_video], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(final_video):
            # Clean up intermediate merged files to free up space
            for scene in valid_scenes:
                if os.path.exists(scene['video']): os.remove(scene['video'])
            if os.path.exists(concat_file): os.remove(concat_file)
                
            print("🚀 Uploading final video and triggering n8n...")
            video_url = await upload_to_github_release(final_video)
            if video_url: await send_to_telegram(video_url)

if __name__ == "__main__":
    asyncio.run(main())
