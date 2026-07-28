import os
import sys
import json
import subprocess
import time
import random
import asyncio
import re
import string
import aiohttp
import edge_tts
import shutil

# --- SAFE UTF-8 DATA LOADING LAYER (FIXED FOR TTS HINDI ENCODING) ---
def load_scenes_data():
    """
    GitHub Event JSON फ़ाइल से बिना किसी Encoding Loss / Corruption (Mojibake) के
    शुद्ध UTF-8 हिंदी/अंग्रेजी टेक्स्ट लोड करता है।
    """
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, 'r', encoding='utf-8') as f:
                event_data = json.load(f)
                payload = event_data.get('client_payload', {})
                raw_scenes = payload.get('scenes_data')
                
                if raw_scenes:
                    if isinstance(raw_scenes, str):
                        return json.loads(raw_scenes)
                    elif isinstance(raw_scenes, list):
                        return raw_scenes
        except Exception as e:
            print(f"DEBUG: GITHUB_EVENT_PATH से पढ़ने में त्रुटि: {e}")

    # Fallback: यदि सीधे SCENES_DATA env var का उपयोग किया गया हो
    raw_env = os.environ.get('SCENES_DATA', '[]')
    try:
        return json.loads(raw_env)
    except Exception as e:
        print(f"DEBUG: Env variable से पढ़ने में त्रुटि: {e}")
        return []

# --- LOAD ALL CONFIGURATIONS & DATA ---
scenes_data = load_scenes_data()

title = os.environ.get('TITLE', 'Engineering Video')
description = os.environ.get('DESCRIPTION', 'Educational video')
thumbnail_prompt = os.environ.get('THUMBNAIL_PROMPT', 'Cinematic engineering thumbnail')
pexels_key = os.environ.get('PEXELS_API_KEY')
chat_id = os.environ.get('CHAT_ID')
telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
channel_name = "Decode®" 

print(f"DEBUG: Processing {len(scenes_data)} scenes async...")

# --- TTS GENERATION FUNCTION ---
async def generate_tts(text, output_path, voice="hi-IN-MadhurNeural"):
    """
    साफ हिंदी टेक्स्ट को edge-tts के ज़रिए MP3 ऑडियो में बदलता है।
    """
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"ERROR generating TTS for '{text[:20]}...': {e}")
        return False

# --- PEXELS VIDEO DOWNLOAD FUNCTION ---
async def fetch_pexels_video(session, query, output_path):
    if not pexels_key:
        print("WARNING: PEXELS_API_KEY नहीं मिला, स्किप कर रहे हैं।")
        return False
        
    headers = {"Authorization": pexels_key}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=portrait"
    
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                videos = data.get('videos', [])
                if videos:
                    # सबसे अच्छी क्वालिट की HD वीडियो चुनना
                    video_files = videos[0].get('video_files', [])
                    selected_file = None
                    for vf in video_files:
                        if vf.get('quality') == 'hd':
                            selected_file = vf.get('link')
                            break
                    if not selected_file and video_files:
                        selected_file = video_files[0].get('link')
                    
                    if selected_file:
                        async with session.get(selected_file) as vid_resp:
                            if vid_resp.status == 200:
                                with open(output_path, 'wb') as f:
                                    f.write(await vid_resp.read())
                                return True
    except Exception as e:
        print(f"Pexels fetch failed for query '{query}': {e}")
    return False

# --- SCENE PROCESSING LAYER ---
async def process_scene(index, scene, session):
    scene_id = index + 1
    raw_text = str(scene.get('text', '')).strip()
    search_query = scene.get('search_query', 'engineering technology')
    
    # 1. Clean Text Input for TTS (हिंदी अक्षरों को बिना डैमेज किए साफ़ करना)
    text_line = raw_text.replace('&', ' और ').strip()
    # UTF-8 Hindi Characters (\u0900-\u097F) और बेसिक पंक्चुएशन को सुरक्षित रखना
    text_line = re.sub(r'[^\w\s.,?!।\-\u0900-\u097F\u200d\u200c]', '', text_line)
    
    audio_file = f"audio_{scene_id}.mp3"
    video_file = f"video_{scene_id}.mp4"
    
    print(f"\n--- Scene {scene_id} ---")
    print(f"Clean Text for TTS: {text_line}")
    print(f"Search Query: {search_query}")
    
    # 2. TTS ऑडियो जनरेट करें
    tts_success = await generate_tts(text_line, audio_file)
    if not tts_success:
        print(f"Scene {scene_id}: TTS जनरेट करने में विफलता!")
        return None
        
    # 3. Pexels से वीडियो लाएं
    v_success = await fetch_pexels_video(session, search_query, video_file)
    if not v_success:
        print(f"Scene {scene_id}: Stock video प्राप्त नहीं हुआ, डिफ़ॉल्ट/कलर बैकग्राउंड का उपयोग किया जाएगा।")
        # यदि स्टॉक वीडियो न मिले तो FFMPEG से ब्लैंक कलर वीडियो बनाना
        cmd_blank = [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:r=30',
            '-t', '5', '-pix_fmt', 'yuv420p', video_file
        ]
        subprocess.run(cmd_blank, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    return {
        'id': scene_id,
        'audio': audio_file,
        'video': video_file,
        'text': text_line
    }

# --- MAIN ASYNC EXECUTION ENGINE ---
async def main():
    if not scenes_data:
        print("ERROR: कोई Scenes Data नहीं मिला! एग्जिट कर रहे हैं।")
        sys.exit(1)
        
    async with aiohttp.ClientSession() as session:
        tasks = [process_scene(i, scene, session) for i, scene in enumerate(scenes_data)]
        results = await asyncio.gather(*tasks)
        
    valid_scenes = [r for r in results if r is not None]
    print(f"\nDEBUG: Successfully processed {len(valid_scenes)}/{len(scenes_data)} scenes.")

if __name__ == "__main__":
    asyncio.run(main())
