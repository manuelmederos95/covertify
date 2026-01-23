import os
import base64
import time
import subprocess
import secrets
import imghdr
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from runwayml import RunwayML, TaskFailedError
import requests
import stripe
from PIL import Image

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

# Initialize Stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID')  # Price for single video generation

# In-memory payment tracking (for simple guest checkout)
# In production, use a database like PostgreSQL or Redis
paid_sessions = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def validate_image_format(filepath):
    """Validate that the uploaded file is actually a supported image format"""
    try:
        # Check actual file type using imghdr
        detected_format = imghdr.what(filepath)

        # Map imghdr formats to our allowed extensions
        allowed_formats = {'png', 'jpeg', 'gif', 'webp'}

        if detected_format not in allowed_formats:
            return False, f"Unsupported image format: {detected_format or 'unknown'}. Please use PNG, JPG, or WebP."

        # Additional validation: Try to open with PIL to ensure it's not corrupted
        try:
            with Image.open(filepath) as img:
                img.verify()  # Verify it's a valid image

            # Re-open to check dimensions (verify() closes the file)
            with Image.open(filepath) as img:
                width, height = img.size

                # Runway works best with reasonable image sizes
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
            print(f"⏱️  Task status: {task.status}")

            if task.status == 'SUCCEEDED':
                print("✅ Generation Complete!")
                return {'success': True, 'video_url': task.output[0], 'task_id': task_id}
            elif task.status == 'FAILED':
                failure_reason = getattr(task, 'failure', getattr(task, 'failure_reason', 'Unknown failure'))
                failure_code = getattr(task, 'failure_code', 'N/A')
                print(f"❌ Task failed!")
                print(f"   Reason: {failure_reason}")
                print(f"   Code: {failure_code}")
                print(f"   Full task object: {task}")
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
            '-preset', 'ultrafast',
            '-crf', '28',  # Lower quality = less CPU/memory
            '-threads', '2',  # Limit threads to reduce memory
            '-bufsize', '1M',  # Smaller buffer
            spotify_file
        ], capture_output=True, text=True, timeout=120)

        # Check if file was created successfully (should be > 1000 bytes for a 5 second video)
        if os.path.exists(spotify_file) and os.path.getsize(spotify_file) > 1000:
            processed_files['spotify'] = os.path.basename(spotify_file)
            file_size = os.path.getsize(spotify_file)
            print(f"✅ Spotify Canvas complete! Size: {file_size} bytes")
        else:
            file_size = os.path.getsize(spotify_file) if os.path.exists(spotify_file) else 0
            print(f"❌ Spotify Canvas failed - file size too small: {file_size} bytes")
            print(f"FFmpeg return code: {result.returncode}")
            print(f"FFmpeg stderr:\n{result.stderr}")
            raise Exception(f"Spotify Canvas encoding failed: {result.stderr[-200:]}")

        # 2. Apple Music Standard (1:1 Square - 3840x3840)
        print("🎬 Formatting for Apple Music Standard (1:1)...")
        apple_square_file = f"{base}_apple_square.mp4"
        print(f"🎯 Output: {apple_square_file}")
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih:ih,scale=3840:3840',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-threads', '2',
            '-bufsize', '2M',  # Slightly larger for 4K
            apple_square_file
        ], capture_output=True, text=True, timeout=120)

        if os.path.exists(apple_square_file) and os.path.getsize(apple_square_file) > 1000:
            processed_files['apple_square'] = os.path.basename(apple_square_file)
            file_size = os.path.getsize(apple_square_file)
            print(f"✅ Apple Music Standard complete! Size: {file_size} bytes")
        else:
            file_size = os.path.getsize(apple_square_file) if os.path.exists(apple_square_file) else 0
            print(f"❌ Apple Music Standard failed - file size too small: {file_size} bytes")
            print(f"FFmpeg return code: {result.returncode}")
            print(f"FFmpeg stderr:\n{result.stderr}")
            raise Exception(f"Apple Music Standard encoding failed: {result.stderr[-200:]}")

        # 3. Apple Music Listening Mode (3:4 Portrait - 2048x2732)
        print("🎬 Formatting for Apple Music Listening Mode (3:4)...")
        apple_portrait_file = f"{base}_apple_portrait.mp4"
        print(f"🎯 Output: {apple_portrait_file}")
        result = subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'crop=ih*(3/4):ih,scale=2048:2732',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-threads', '2',
            '-bufsize', '1.5M',
            apple_portrait_file
        ], capture_output=True, text=True, timeout=120)

        if os.path.exists(apple_portrait_file) and os.path.getsize(apple_portrait_file) > 1000:
            processed_files['apple_portrait'] = os.path.basename(apple_portrait_file)
            file_size = os.path.getsize(apple_portrait_file)
            print(f"✅ Apple Music Listening Mode complete! Size: {file_size} bytes")
        else:
            file_size = os.path.getsize(apple_portrait_file) if os.path.exists(apple_portrait_file) else 0
            print(f"❌ Apple Music Listening Mode failed - file size too small: {file_size} bytes")
            print(f"FFmpeg return code: {result.returncode}")
            print(f"FFmpeg stderr:\n{result.stderr}")
            raise Exception(f"Apple Music Listening Mode encoding failed: {result.stderr[-200:]}")

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

        # Generate unique filename
        filename = secure_filename(file.filename)
        unique_id = secrets.token_urlsafe(16)
        file_extension = filename.rsplit('.', 1)[1].lower()
        stored_filename = f"{unique_id}.{file_extension}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)

        # Save file temporarily
        file.save(filepath)
        print(f"📤 Image uploaded: {stored_filename}")

        # Validate the actual image format
        is_valid, validation_message = validate_image_format(filepath)

        if not is_valid:
            # Remove invalid file
            try:
                os.remove(filepath)
            except:
                pass
            print(f"❌ Image validation failed: {validation_message}")
            return jsonify({'success': False, 'error': validation_message}), 400

        print(f"✅ Image validated: {validation_message}")

        return jsonify({
            'success': True,
            'image_id': unique_id,
            'filename': stored_filename
        })

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

        # Create a Stripe Checkout Session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': STRIPE_PRICE_ID,
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.host_url + 'payment-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'payment-cancelled',
            metadata={
                'type': 'video_generation',
                'image_id': image_id
            }
        )

        # Store Stripe session with image_id for later verification
        paid_sessions[checkout_session.id] = {
            'paid': False,
            'image_id': image_id,
            'created_at': time.time()
        }

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

    # Check if payment is confirmed and get image_id
    if session_id and session_id in paid_sessions:
        session_data = paid_sessions[session_id]
        if session_data.get('paid'):
            image_id = session_data.get('image_id')
            return render_template('index.html',
                                stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                                payment_success=True,
                                session_id=session_id,
                                image_id=image_id)

    return render_template('index.html',
                         stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                         payment_pending=True,
                         session_id=session_id)

@app.route('/payment-cancelled')
def payment_cancelled():
    """Handle cancelled payment redirect from Stripe"""
    return render_template('index.html', stripe_publishable_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        print(f"❌ Invalid webhook payload: {e}")
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        print(f"❌ Invalid webhook signature: {e}")
        return jsonify({'error': 'Invalid signature'}), 400

    # Handle successful payment
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        session_id = session['id']

        if session_id in paid_sessions:
            paid_sessions[session_id]['paid'] = True
            paid_sessions[session_id]['email'] = session.get('customer_details', {}).get('email')
            print(f"✅ Payment confirmed for session: {session_id}")

    return jsonify({'success': True})

@app.route('/check-payment/<session_id>')
def check_payment(session_id):
    """Check if payment has been completed"""
    if session_id in paid_sessions and paid_sessions[session_id]['paid']:
        return jsonify({'success': True, 'paid': True})
    return jsonify({'success': True, 'paid': False})

@app.route('/generate-video', methods=['POST'])
def generate_video_endpoint():
    """Generate video from stored image after payment"""
    data = request.get_json()
    session_id = data.get('session_id')

    if not session_id:
        return jsonify({'success': False, 'error': 'Session ID required'}), 400

    # Verify payment status directly with Stripe (don't rely on webhook)
    try:
        stripe_session = stripe.checkout.Session.retrieve(session_id)

        # Check if payment was successful
        if stripe_session.payment_status != 'paid':
            return jsonify({'success': False, 'error': 'Payment not completed'}), 402

        # Get image_id from metadata or our session storage
        image_id = stripe_session.metadata.get('image_id')

        # If session exists in our storage, update it
        if session_id in paid_sessions:
            paid_sessions[session_id]['paid'] = True
            if not image_id:
                image_id = paid_sessions[session_id].get('image_id')
        else:
            # Create session record if webhook hasn't fired yet
            if not image_id:
                return jsonify({'success': False, 'error': 'No image found for this session'}), 400
            paid_sessions[session_id] = {
                'paid': True,
                'image_id': image_id,
                'created_at': time.time()
            }

    except stripe.error.StripeError as e:
        print(f"❌ Stripe error: {e}")
        return jsonify({'success': False, 'error': 'Failed to verify payment'}), 500

    # Check if session was already used (prevent reuse)
    if paid_sessions[session_id].get('used', False):
        return jsonify({'success': False, 'error': 'Payment already used'}), 402

    # Check if session was already used (prevent reuse)
    if paid_sessions[session_id].get('used', False):
        return jsonify({'success': False, 'error': 'Payment already used'}), 402

    # Get the stored image
    if not image_id:
        return jsonify({'success': False, 'error': 'No image found for this session'}), 400

    # Find the image file
    import glob
    image_files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], f"{image_id}.*"))

    print(f"🔍 Looking for image with ID: {image_id}")
    print(f"🔍 Upload folder: {app.config['UPLOAD_FOLDER']}")
    print(f"🔍 Pattern: {image_id}.*")
    print(f"🔍 Files found: {image_files}")

    if not image_files:
        # List all files in upload folder for debugging
        all_files = os.listdir(app.config['UPLOAD_FOLDER'])
        print(f"📁 All files in upload folder: {all_files}")
        return jsonify({'success': False, 'error': f'Image file not found. Image ID: {image_id}'}), 404

    filepath = image_files[0]
    filename = os.path.basename(filepath)

    # Use default prompt for all generations
    prompt = 'Subtle cinematic motion, slow zoom in, floating dust particles, high quality'
    duration = 5

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
            # Mark session as used (prevent reuse)
            paid_sessions[session_id]['used'] = True
            paid_sessions[session_id]['used_at'] = time.time()

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
