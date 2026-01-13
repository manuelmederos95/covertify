import os
import sys
import requests
import subprocess

def download_video(url, filename):
    os.makedirs("Result", exist_ok=True)
    filepath = os.path.join("Result", filename)
    print(f"📥 Downloading: {url}")
    response = requests.get(url, stream=True)
    with open(filepath, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return filepath

def process_for_platforms(input_path):
    base = os.path.splitext(input_path)[0]
    
    # 1. Spotify Canvas (9:16 Vertical)
    print("🎬 Formatting for Spotify...")
    subprocess.run([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', 'crop=ih*(9/16):ih,scale=1080:1920',
        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', f"{base}_spotify.mp4"
    ])

    # 2. Apple Music (1:1 Square)
    print("🎬 Formatting for Apple Music (1:1)...")
    subprocess.run([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', 'crop=ih:ih,scale=3840:3840',
        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', f"{base}_apple_1x1.mp4"
    ])

    # 3. Apple Music (3:4 Vertical)
    print("🎬 Formatting for Apple Music (3:4)...")
    subprocess.run([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', 'crop=ih*(3/4):ih,scale=2048:2732',
        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', f"{base}_apple_3x4.mp4"
    ])

if __name__ == "__main__":
    # Check if a URL was actually provided in the command line
    if len(sys.argv) < 2:
        print("❌ Usage: python3 process_video.py <VIDEO_URL>")
        sys.exit(1)

    video_url = sys.argv[1]
    local_file = download_video(video_url, "input_video.mp4")
    process_for_platforms(local_file)
    print("🚀 DONE! Check the 'Result' folder.")