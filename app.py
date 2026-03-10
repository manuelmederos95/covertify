import os
import base64
import time
import subprocess

# Ensure Homebrew binaries (ffmpeg) are in PATH on macOS
os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')
import secrets
import imghdr
import sqlite3
import threading
import uuid
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from runwayml import RunwayML, TaskFailedError
import requests
import stripe
from PIL import Image
from flask_talisman import Talisman

app = Flask(__name__)

# Use absolute paths for Railway Volume compatibility
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')

# Check if Railway Volume is mounted, otherwise use local folder
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

# --- SQLite Setup ---
DB_PATH = os.path.join(BASE_DIR, 'covertify.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read/write
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            paid INTEGER DEFAULT 0,
            image_id TEXT,
            created_at REAL,
            used INTEGER DEFAULT 0,
            used_at REAL,
            email TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            session_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at REAL,
            updated_at REAL,
            spotify_video TEXT,
            apple_square_video TEXT,
            apple_portrait_video TEXT,
            original_video TEXT,
            video_url TEXT,
            error TEXT,
            message TEXT
        )''')
        conn.commit()

init_db()

# --- Talisman (security headers) ---
# Disable HTTPS enforcement in local dev
LOCAL_DEV = os.environ.get('LOCAL_DEV', 'false').lower() == 'true'

csp = {
    'default-src': [
        '\'self\'',
        'https://js.stripe.com',
        'https://checkout.stripe.com'
    ],
    'script-src': [
        '\'self\'',
        '\'unsafe-inline\'',
        'https://js.stripe.com'
    ],
    'style-src': [
        '\'self\'',
        '\'unsafe-inline\''
    ],
    'img-src': [
        '\'self\'',
        'data:',
        'https:'
    ],
    'frame-src': [
        'https://js.stripe.com',
        'https://hooks.stripe.com'
    ],
    'connect-src': [
        '\'self\'',
        'https://api.stripe.com'
    ]
}

Talisman(
    app,
    force_https=not LOCAL_DEV,
    strict_transport_security=not LOCAL_DEV,
    content_security_policy=csp
)

# Initialize Runway client
client = RunwayML()

# Initialize Stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID')


# --- Helpers ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def validate_image_format(filepath):
    """Validate that the uploaded file is actually a supported image format"""
    try:
        detected_format = imghdr.what(filepath)
        allowed_formats = {'png', 'jpeg', 'gif', 'webp'}

        if detected_format not in allowed_formats:
            return False, f"Unsupported image format: {detected_format or 'unknown'}. Please use PNG, JPG, or WebP."

        try:
            with Image.open(filepath) as img:
                img.verify()
            with Image.open(filepath) as img:
                width, height = img.size
                if width < 256 or height < 256:
                    return False, "Image too small. Minimum size: 256x256 pixels."
                if width > 4096 or height > 4096:
                    return False, "Image too large. Maximum size: 4096x4096 pixels."
        except Exception as e:
            return False, f"Invalid or corrupted image file: {str(e)}"

        return True, "Valid image"

    except Exception as e:
        return False, f"Error validating image: {str(e)}"

def file_to_data_uri(file_path):
    """Convert local file to data URI for Runway API"""
    with open(file_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
        ext = file_path.rsplit('.', 1)[1].lower()
        mime_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"
        return f"data:{mime_type};base64,{data}"

def generate_video(image_path, prompt, duration=5):
    """Generate video using Runway API"""
    try:
        print(f"🚀 Starting generation for: {prompt}")
        image_uri = file_to_data_uri(image_path)

        task = client.image_to_video.create(
            model='gen3a_turbo',
            prompt_image=image_uri,
            prompt_text=prompt,
            ratio="1280:768",
            duration=duration
        )

        task_id = task.id
        print(f"⏳ Task created (ID: {task_id}). Waiting for completion...")

        while True:
            task = client.tasks.retrieve(task_id)
            print(f"⏱️  Task status: {task.status}")

            if task.status == 'SUCCEEDED':
                print("✅ Generation Complete!")
                return {'success': True, 'video_url': task.output[0], 'task_id': task_id}
            elif task.status == 'FAILED':
                failure_reason = getattr(task, 'failure', getattr(task, 'failure_reason', 'Unknown failure'))
                failure_code = getattr(task, 'failure_code', 'N/A')
                print(f"❌ Task failed! Reason: {failure_reason} Code: {failure_code}")
                return {'success': False, 'error': f"{failure_code}: {failure_reason}"}

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
    print(f"📥 Downloading: {url} -> {filepath}")
    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = 0
    with open(filepath, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            total_size += len(chunk)

    print(f"✅ Download complete! Size: {total_size} bytes")
    return filepath

def process_for_platforms(input_path):
    """Process video for different platform formats"""
    base = os.path.splitext(input_path)[0]
    processed_files = {}

    print(f"🔍 Input file: {input_path} (exists: {os.path.exists(input_path)})")

    try:
        # 1. Spotify Canvas (9:16 Vertical)
        print("🎬 Formatting for Spotify Canvas...")
        spotify_file = f"{base}_spotify.mp4"
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih*(9/16):ih,scale=1080:1920',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast', '-crf', '28',
            '-threads', '2', '-bufsize', '1M',
            spotify_file
        ], capture_output=True, text=True, timeout=120)

        if os.path.exists(spotify_file) and os.path.getsize(spotify_file) > 1000:
            processed_files['spotify'] = os.path.basename(spotify_file)
            print(f"✅ Spotify Canvas complete! Size: {os.path.getsize(spotify_file)} bytes")
        else:
            raise Exception(f"Spotify Canvas encoding failed: {result.stderr[-200:]}")

        # 2. Apple Music Standard (1:1 Square - 3840x3840)
        print("🎬 Formatting for Apple Music Standard (1:1)...")
        apple_square_file = f"{base}_apple_square.mp4"
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih:ih,scale=3840:3840',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast', '-crf', '28',
            '-threads', '2', '-bufsize', '2M',
            apple_square_file
        ], capture_output=True, text=True, timeout=120)

        if os.path.exists(apple_square_file) and os.path.getsize(apple_square_file) > 1000:
            processed_files['apple_square'] = os.path.basename(apple_square_file)
            print(f"✅ Apple Music Standard complete! Size: {os.path.getsize(apple_square_file)} bytes")
        else:
            raise Exception(f"Apple Music Standard encoding failed: {result.stderr[-200:]}")

        # 3. Apple Music Listening Mode (3:4 Portrait - 2048x2732)
        print("🎬 Formatting for Apple Music Listening Mode (3:4)...")
        apple_portrait_file = f"{base}_apple_portrait.mp4"
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih*(3/4):ih,scale=2048:2732',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast', '-crf', '28',
            '-threads', '2', '-bufsize', '1.5M',
            apple_portrait_file
        ], capture_output=True, text=True, timeout=120)

        if os.path.exists(apple_portrait_file) and os.path.getsize(apple_portrait_file) > 1000:
            processed_files['apple_portrait'] = os.path.basename(apple_portrait_file)
            print(f"✅ Apple Music Listening Mode complete! Size: {os.path.getsize(apple_portrait_file)} bytes")
        else:
            raise Exception(f"Apple Music Listening Mode encoding failed: {result.stderr[-200:]}")

        return {'success': True, 'files': processed_files}

    except subprocess.TimeoutExpired as e:
        return {'success': False, 'error': f"FFmpeg timeout after {e.timeout}s"}
    except subprocess.CalledProcessError as e:
        return {'success': False, 'error': f"FFmpeg failed: {e.stderr if e.stderr else str(e)}"}
    except FileNotFoundError as e:
        return {'success': False, 'error': f"FFmpeg not found or file missing: {str(e)}"}
    except Exception as e:
        return {'success': False, 'error': f"Processing error: {str(e)}"}


def run_video_job(job_id, image_path, filename, session_id):
    """Background thread: generate video and update job status in DB"""
    def update_job(**kwargs):
        kwargs['updated_at'] = time.time()
        set_clause = ', '.join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [job_id]
        with get_db() as conn:
            conn.execute(f"UPDATE jobs SET {set_clause} WHERE job_id = ?", values)
            conn.commit()

    try:
        prompt = 'Subtle cinematic motion, slow and small zoom in, high quality, no text'
        result = generate_video(image_path, prompt, duration=5)

        if not result['success']:
            update_job(status='failed', error=result['error'])
            return

        # Download the generated video
        video_filename = f"{os.path.splitext(filename)[0]}_generated.mp4"
        video_path = download_video(result['video_url'], video_filename)

        # Process for platforms
        print("🎨 Processing video for platform formats...")
        process_result = process_for_platforms(video_path)

        if process_result['success']:
            # Mark session as used
            with get_db() as conn:
                conn.execute(
                    "UPDATE sessions SET used = 1, used_at = ? WHERE session_id = ?",
                    (time.time(), session_id)
                )
                conn.commit()

            update_job(
                status='succeeded',
                message='Videos generated successfully for all platforms!',
                video_url=result['video_url'],
                original_video=video_filename,
                spotify_video=process_result['files']['spotify'],
                apple_square_video=process_result['files']['apple_square'],
                apple_portrait_video=process_result['files']['apple_portrait'],
            )
        else:
            update_job(
                status='succeeded',
                message='Video generated but platform processing failed',
                video_url=result['video_url'],
                original_video=video_filename,
                error=process_result.get('error', 'Unknown processing error'),
            )

    except Exception as e:
        print(f"❌ Job {job_id} failed with exception: {e}")
        update_job(status='failed', error=str(e))


# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html', stripe_publishable_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/upload-image', methods=['POST'])
def upload_image():
    """Upload and store image before payment"""
    try:
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400

        filename = secure_filename(file.filename)
        unique_id = secrets.token_urlsafe(16)
        file_extension = filename.rsplit('.', 1)[1].lower()
        stored_filename = f"{unique_id}.{file_extension}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)

        file.save(filepath)
        print(f"📤 Image uploaded: {stored_filename}")

        is_valid, validation_message = validate_image_format(filepath)
        if not is_valid:
            try:
                os.remove(filepath)
            except:
                pass
            print(f"❌ Image validation failed: {validation_message}")
            return jsonify({'success': False, 'error': validation_message}), 400

        print(f"✅ Image validated: {validation_message}")
        return jsonify({'success': True, 'image_id': unique_id, 'filename': stored_filename})

    except Exception as e:
        print(f"❌ Upload error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/create-payment-intent', methods=['POST'])
def create_payment_intent():
    """Create a Stripe payment intent for video generation"""
    try:
        data = request.get_json()
        image_id = data.get('image_id')

        if not image_id:
            return jsonify({'success': False, 'error': 'Image ID required'}), 400

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            mode='payment',
            success_url=request.host_url + 'payment-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'payment-cancelled',
            metadata={'type': 'video_generation', 'image_id': image_id}
        )

        with get_db() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, paid, image_id, created_at) VALUES (?, 0, ?, ?)",
                (checkout_session.id, image_id, time.time())
            )
            conn.commit()

        return jsonify({
            'success': True,
            'checkout_url': checkout_session.url,
            'session_id': checkout_session.id
        })

    except Exception as e:
        print(f"❌ Payment error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment redirect from Stripe"""
    session_id = request.args.get('session_id')

    if session_id:
        with get_db() as conn:
            row = conn.execute(
                "SELECT paid, image_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row and row['paid']:
            return render_template('index.html',
                                   stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                                   payment_success=True,
                                   session_id=session_id,
                                   image_id=row['image_id'])

    return render_template('index.html',
                           stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                           payment_pending=True,
                           session_id=session_id)

@app.route('/payment-cancelled')
def payment_cancelled():
    return render_template('index.html', stripe_publishable_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError as e:
        print(f"❌ Invalid webhook payload: {e}")
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        print(f"❌ Invalid webhook signature: {e}")
        return jsonify({'error': 'Invalid signature'}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        session_id = session['id']
        email = session.get('customer_details', {}).get('email')
        with get_db() as conn:
            conn.execute(
                "UPDATE sessions SET paid = 1, email = ? WHERE session_id = ?",
                (email, session_id)
            )
            conn.commit()
        print(f"✅ Payment confirmed for session: {session_id}")

    return jsonify({'success': True})

@app.route('/check-payment/<session_id>')
def check_payment(session_id):
    """Check if payment has been completed"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT paid FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if row and row['paid']:
        return jsonify({'success': True, 'paid': True})
    return jsonify({'success': True, 'paid': False})

@app.route('/generate-video', methods=['POST'])
def generate_video_endpoint():
    """Start async video generation after payment — returns job_id immediately"""
    data = request.get_json()
    session_id = data.get('session_id')

    if not session_id:
        return jsonify({'success': False, 'error': 'Session ID required'}), 400

    # Verify payment directly with Stripe
    try:
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        if stripe_session.payment_status != 'paid':
            return jsonify({'success': False, 'error': 'Payment not completed'}), 402
        image_id = stripe_session.metadata.get('image_id')
    except stripe.error.StripeError as e:
        print(f"❌ Stripe error: {e}")
        return jsonify({'success': False, 'error': 'Failed to verify payment'}), 500

    # Upsert session record
    with get_db() as conn:
        existing = conn.execute(
            "SELECT used, image_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()

        if existing:
            if existing['used']:
                return jsonify({'success': False, 'error': 'Payment already used'}), 402
            if not image_id:
                image_id = existing['image_id']
            conn.execute(
                "UPDATE sessions SET paid = 1 WHERE session_id = ?", (session_id,)
            )
        else:
            if not image_id:
                return jsonify({'success': False, 'error': 'No image found for this session'}), 400
            conn.execute(
                "INSERT INTO sessions (session_id, paid, image_id, created_at) VALUES (?, 1, ?, ?)",
                (session_id, image_id, time.time())
            )
        conn.commit()

    if not image_id:
        return jsonify({'success': False, 'error': 'No image found for this session'}), 400

    # Find the uploaded image file
    import glob as glob_module
    image_files = glob_module.glob(os.path.join(app.config['UPLOAD_FOLDER'], f"{image_id}.*"))

    if not image_files:
        all_files = os.listdir(app.config['UPLOAD_FOLDER'])
        print(f"📁 All files in upload folder: {all_files}")
        return jsonify({'success': False, 'error': f'Image file not found. Image ID: {image_id}'}), 404

    filepath = image_files[0]
    filename = os.path.basename(filepath)

    # Create a job record
    job_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, session_id, status, created_at, updated_at) VALUES (?, ?, 'processing', ?, ?)",
            (job_id, session_id, time.time(), time.time())
        )
        conn.commit()

    # Start background thread — does not block this request
    thread = threading.Thread(
        target=run_video_job,
        args=(job_id, filepath, filename, session_id),
        daemon=True
    )
    thread.start()

    print(f"🚀 Job {job_id} started for session {session_id}")
    return jsonify({'success': True, 'job_id': job_id, 'status': 'processing'})

@app.route('/job-status/<job_id>')
def job_status(job_id):
    """Poll endpoint: returns current status of a video generation job"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()

    if not row:
        return jsonify({'success': False, 'error': 'Job not found'}), 404

    result = {
        'success': True,
        'job_id': job_id,
        'status': row['status'],  # processing | succeeded | failed
    }

    if row['status'] == 'succeeded':
        result['message'] = row['message']
        result['video_url'] = row['video_url']
        result['original_video'] = row['original_video']
        result['spotify_video'] = row['spotify_video']
        result['apple_square_video'] = row['apple_square_video']
        result['apple_portrait_video'] = row['apple_portrait_video']
        if row['error']:
            result['processing_error'] = row['error']
    elif row['status'] == 'failed':
        result['error'] = row['error']

    return jsonify(result)

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
    print(f"🎥 Preview request for: {filename} (exists: {os.path.exists(filepath)})")
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='video/mp4')
    return jsonify({'success': False, 'error': 'File not found'}), 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_DEBUG', 'False') == 'True'
    app.run(debug=debug, host='0.0.0.0', port=port, threaded=True)
