import os
import base64
import time
import subprocess
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from runwayml import RunwayML, TaskFailedError
import requests

app = Flask(__name__)

# Use absolute paths for Railway Volume compatibility
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')

# Check if Railway Volume is mounted, otherwise use local folder
# Railway mounts volumes as absolute paths like /app/Result
RAILWAY_VOLUME_PATH = '/app/Result'
if os.path.exists(RAILWAY_VOLUME_PATH) and os.path.isdir(RAILWAY_VOLUME_PATH):
    app.config['RESULT_FOLDER'] = RAILWAY_VOLUME_PATH
    print("🚂 Using Railway Volume for storage")
else:
    app.config['RESULT_FOLDER'] = os.path.join(BASE_DIR, 'Result')
    print("💻 Using local storage")

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULT_FOLDER'], exist_ok=True)

# Debug logging
print(f"📁 BASE_DIR: {BASE_DIR}")
print(f"📁 Upload folder: {app.config['UPLOAD_FOLDER']}")
print(f"📁 Result folder: {app.config['RESULT_FOLDER']}")
print(f"📁 Result folder exists: {os.path.exists(app.config['RESULT_FOLDER'])}")
print(f"📁 Result folder writable: {os.access(app.config['RESULT_FOLDER'], os.W_OK)}")
print(f"📁 Result folder is directory: {os.path.isdir(app.config['RESULT_FOLDER'])}")

# Initialize Runway client
client = RunwayML()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def file_to_data_uri(file_path):
    """Convert local file to data URI for Runway API"""
    with open(file_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
        # Determine the mime type based on extension
        ext = file_path.rsplit('.', 1)[1].lower()
        mime_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"
        return f"data:{mime_type};base64,{data}"

def generate_video(image_path, prompt, duration=5):
    """Generate video using Runway API"""
    try:
        print(f"🚀 Starting generation for: {prompt}")

        # Convert image to data URI
        image_uri = file_to_data_uri(image_path)

        # Create the Image-to-Video task
        task = client.image_to_video.create(
            model='gen3a_turbo',
            prompt_image=image_uri,
            prompt_text=prompt,
            ratio="1280:768",
            duration=duration
        )

        task_id = task.id
        print(f"⏳ Task created (ID: {task_id}). Waiting for completion...")

        # Poll for the result
        while True:
            task = client.tasks.retrieve(task_id)
            if task.status == 'SUCCEEDED':
                print("✅ Generation Complete!")
                return {'success': True, 'video_url': task.output[0], 'task_id': task_id}
            elif task.status == 'FAILED':
                failure_reason = getattr(task, 'failure_reason', 'Unknown failure')
                print(f"❌ Task failed: {failure_reason}")
                return {'success': False, 'error': str(failure_reason)}

            time.sleep(5)

    except TaskFailedError as e:
        print(f"API Error: {e}")
        return {'success': False, 'error': str(e)}
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return {'success': False, 'error': str(e)}

def download_video(url, filename):
    """Download video from URL"""
    filepath = os.path.join(app.config['RESULT_FOLDER'], filename)
    print(f"📥 Downloading: {url}")
    print(f"📥 Saving to: {filepath}")
    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = 0
    with open(filepath, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            total_size += len(chunk)

    print(f"✅ Download complete! Size: {total_size} bytes")
    print(f"✅ File exists: {os.path.exists(filepath)}")
    print(f"✅ File readable: {os.access(filepath, os.R_OK)}")

    return filepath

def process_for_platforms(input_path):
    """Process video for different platform formats"""
    base = os.path.splitext(input_path)[0]
    processed_files = {}

    # Verify input file exists
    print(f"🔍 Input file: {input_path}")
    print(f"🔍 Input file exists: {os.path.exists(input_path)}")
    print(f"🔍 Input file size: {os.path.getsize(input_path) if os.path.exists(input_path) else 'N/A'} bytes")

    try:
        # 1. Spotify Canvas (9:16 Vertical)
        print("🎬 Formatting for Spotify Canvas...")
        spotify_file = f"{base}_spotify.mp4"
        print(f"🎯 Output: {spotify_file}")
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih*(9/16):ih,scale=1080:1920',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast',  # Faster encoding
            spotify_file
        ], check=True, capture_output=True, text=True, timeout=120)
        processed_files['spotify'] = os.path.basename(spotify_file)
        file_size = os.path.getsize(spotify_file) if os.path.exists(spotify_file) else 0
        print(f"✅ Spotify Canvas complete! Exists: {os.path.exists(spotify_file)}, Size: {file_size} bytes")

        # 2. Apple Music Standard (1:1 Square - 3840x3840)
        print("🎬 Formatting for Apple Music Standard (1:1)...")
        apple_square_file = f"{base}_apple_square.mp4"
        print(f"🎯 Output: {apple_square_file}")
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih:ih,scale=3840:3840',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast',
            apple_square_file
        ], check=True, capture_output=True, text=True, timeout=120)
        processed_files['apple_square'] = os.path.basename(apple_square_file)
        file_size = os.path.getsize(apple_square_file) if os.path.exists(apple_square_file) else 0
        print(f"✅ Apple Music Standard complete! Exists: {os.path.exists(apple_square_file)}, Size: {file_size} bytes")

        # 3. Apple Music Listening Mode (3:4 Portrait - 2048x2732)
        print("🎬 Formatting for Apple Music Listening Mode (3:4)...")
        apple_portrait_file = f"{base}_apple_portrait.mp4"
        print(f"🎯 Output: {apple_portrait_file}")
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih*(3/4):ih,scale=2048:2732',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast',
            apple_portrait_file
        ], check=True, capture_output=True, text=True, timeout=120)
        processed_files['apple_portrait'] = os.path.basename(apple_portrait_file)
        file_size = os.path.getsize(apple_portrait_file) if os.path.exists(apple_portrait_file) else 0
        print(f"✅ Apple Music Listening Mode complete! Exists: {os.path.exists(apple_portrait_file)}, Size: {file_size} bytes")

        return {'success': True, 'files': processed_files}

    except subprocess.TimeoutExpired as e:
        error_msg = f"FFmpeg timeout after {e.timeout}s"
        print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}
    except subprocess.CalledProcessError as e:
        error_msg = f"FFmpeg failed: {e.stderr if e.stderr else str(e)}"
        print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}
    except FileNotFoundError as e:
        error_msg = f"FFmpeg not found or file missing: {str(e)}"
        print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Processing error: {str(e)}"
        print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle image upload and video generation"""
    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['image']
    # Use default prompt for all generations
    prompt = 'Subtle cinematic motion, slow zoom in, floating dust particles, high quality'
    duration = int(request.form.get('duration', 5))

    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Generate video
        result = generate_video(filepath, prompt, duration)

        if result['success']:
            # Download the video
            video_filename = f"{os.path.splitext(filename)[0]}_generated.mp4"
            video_path = download_video(result['video_url'], video_filename)

            # Process video for different platforms
            print("🎨 Processing video for platform formats...")
            process_result = process_for_platforms(video_path)

            if process_result['success']:
                return jsonify({
                    'success': True,
                    'message': 'Videos generated successfully for all platforms!',
                    'video_url': result['video_url'],
                    'original_video': video_filename,
                    'spotify_video': process_result['files']['spotify'],
                    'apple_square_video': process_result['files']['apple_square'],
                    'apple_portrait_video': process_result['files']['apple_portrait'],
                    'task_id': result['task_id']
                })
            else:
                # Still return the original video even if processing fails
                return jsonify({
                    'success': True,
                    'message': 'Video generated but platform processing failed',
                    'video_url': result['video_url'],
                    'original_video': video_filename,
                    'processing_error': process_result.get('error', 'Unknown error'),
                    'task_id': result['task_id']
                })
        else:
            return jsonify(result), 500

    return jsonify({'success': False, 'error': 'Invalid file type'}), 400

@app.route('/download/<filename>')
def download_result(filename):
    """Download the generated video"""
    filepath = os.path.join(app.config['RESULT_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'success': False, 'error': 'File not found'}), 404

@app.route('/preview/<filename>')
def preview_video(filename):
    """Preview the generated video"""
    filepath = os.path.join(app.config['RESULT_FOLDER'], filename)
    print(f"🎥 Preview request for: {filename}")
    print(f"🎥 Looking at path: {filepath}")
    print(f"🎥 File exists: {os.path.exists(filepath)}")
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='video/mp4')
    # List all files in Result folder for debugging
    try:
        files = os.listdir(app.config['RESULT_FOLDER'])
        print(f"📂 Files in Result folder: {files}")
    except Exception as e:
        print(f"❌ Error listing files: {e}")
    return jsonify({'success': False, 'error': 'File not found'}), 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_DEBUG', 'False') == 'True'
    app.run(debug=debug, host='0.0.0.0', port=port)
