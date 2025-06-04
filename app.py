from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import logging
from datetime import datetime
import subprocess
import sys
import requests
from urllib.parse import urlparse
import tempfile
import shutil

# Initialize Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'mp3', 'wav'}
app.config['MAX_FILE_AGE'] = 24 * 60 * 60  # 24 hours in seconds

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('video_generator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def allowed_file(filename):
    """Check if the file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def check_ffmpeg():
    """Verify FFmpeg is installed and accessible"""
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, 
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(['ffprobe', '-version'], check=True,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"FFmpeg/FFprobe check failed: {str(e)}")
        return False

def download_remote_file(url, file_type):
    """Download remote file with improved error handling and temp file management"""
    try:
        # Validate URL
        parsed = urlparse(url)
        if not all([parsed.scheme, parsed.netloc]):
            raise ValueError("Invalid URL format")

        # Create temp file in upload folder
        temp_ext = os.path.splitext(parsed.path)[1] or f'.{file_type}'
        temp_file = tempfile.NamedTemporaryFile(
            suffix=temp_ext,
            dir=app.config['UPLOAD_FOLDER'],
            delete=False
        )
        temp_path = temp_file.name
        temp_file.close()

        # Download with timeout and streaming
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(temp_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        logger.info(f"Successfully downloaded {url} to {temp_path}")
        return temp_path

    except requests.exceptions.RequestException as e:
        logger.error(f"Download failed for {url}: {str(e)}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        return None
    except Exception as e:
        logger.error(f"Unexpected download error: {str(e)}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        return None

def validate_media_file(file_path, media_type):
    """Validate media files using ffprobe with detailed error reporting"""
    try:
        if media_type == 'image':
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,width,height,pix_fmt',
                '-of', 'json',
                file_path
            ]
        elif media_type == 'audio':
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'a:0',
                '-show_entries', 'stream=codec_name,sample_rate,channels,duration',
                '-of', 'json',
                file_path
            ]
        else:
            raise ValueError("Invalid media type")

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            logger.error(f"Validation failed for {file_path} ({media_type}): {error_msg}")
            return False, error_msg

        return True, result.stdout

    except subprocess.TimeoutExpired:
        error_msg = "Validation timed out"
        logger.error(f"Timeout validating {file_path} ({media_type})")
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        logger.error(f"Error validating {file_path} ({media_type}): {error_msg}")
        return False, error_msg

def generate_video(image_path, audio_path, output_path):
    """Generate video from image and audio with robust error handling"""
    try:
        cmd = [
            'ffmpeg',
            '-loglevel', 'error',
            '-loop', '1',
            '-framerate', '2',
            '-i', image_path,
            '-i', audio_path,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-tune', 'stillimage',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-shortest',
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
            '-y',
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            logger.error(f"FFmpeg failed: {error_msg}")
            return False, error_msg

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            error_msg = "Output file not created or empty"
            logger.error(error_msg)
            return False, error_msg

        return True, "Video generated successfully"

    except subprocess.TimeoutExpired:
        error_msg = "FFmpeg timed out"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"Video generation error: {error_msg}")
        return False, error_msg

def cleanup_old_files():
    """Clean up files older than MAX_FILE_AGE"""
    try:
        now = datetime.now().timestamp()
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file_age = now - os.path.getmtime(file_path)
            if file_age > app.config['MAX_FILE_AGE']:
                try:
                    os.unlink(file_path)
                    logger.info(f"Cleaned up old file: {filename}")
                except Exception as e:
                    logger.error(f"Error cleaning up {filename}: {str(e)}")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

@app.before_request
def log_request_info():
    """Log incoming requests"""
    logger.info(f"Request: {request.method} {request.path}")
    if request.files:
        logger.info(f"Files received: {list(request.files.keys())}")
    if request.json:
        logger.info(f"JSON data received")

@app.route('/generate', methods=['POST'])
def handle_generation():
    """Handle video generation requests"""
    cleanup_old_files()  # Clean up before processing new request

    # Check FFmpeg availability
    if not check_ffmpeg():
        return jsonify({
            "error": "Server configuration error",
            "message": "FFmpeg not available"
        }), 500

    # Initialize variables
    saved_files = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    errors = []

    try:
        # Process image (either file upload or URL)
        if 'image' in request.files:
            file = request.files['image']
            if file.filename == '':
                errors.append("Empty image filename")
            elif not allowed_file(file.filename):
                errors.append("Invalid image file type")
            else:
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"image_{timestamp}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
                file.save(filepath)
                saved_files['image'] = filepath
        elif request.json and 'image' in request.json:
            filepath = download_remote_file(request.json['image'], 'image')
            if filepath:
                saved_files['image'] = filepath
            else:
                errors.append("Failed to download image URL")
        else:
            errors.append("Missing image (file or URL)")

        # Process audio (either file upload or URL)
        if 'audio' in request.files:
            file = request.files['audio']
            if file.filename == '':
                errors.append("Empty audio filename")
            elif not allowed_file(file.filename):
                errors.append("Invalid audio file type")
            else:
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"audio_{timestamp}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
                file.save(filepath)
                saved_files['audio'] = filepath
        elif request.json and 'audio' in request.json:
            filepath = download_remote_file(request.json['audio'], 'audio')
            if filepath:
                saved_files['audio'] = filepath
            else:
                errors.append("Failed to download audio URL")
        else:
            errors.append("Missing audio (file or URL)")

        # Return errors if any
        if errors:
            return jsonify({
                "error": "Invalid request",
                "messages": errors
            }), 400

        # Validate media files
        image_valid, image_info = validate_media_file(saved_files['image'], 'image')
        audio_valid, audio_info = validate_media_file(saved_files['audio'], 'audio')

        if not image_valid or not audio_valid:
            return jsonify({
                "error": "Invalid media files",
                "image_error": None if image_valid else image_info,
                "audio_error": None if audio_valid else audio_info
            }), 400

        # Generate video
        video_filename = f"video_{timestamp}.mp4"
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)

        success, message = generate_video(saved_files['image'], saved_files['audio'], video_path)
        if not success:
            return jsonify({
                "error": "Video generation failed",
                "message": message
            }), 500

        # Return success response
        base_url = request.host_url.rstrip('/')
        return jsonify({
            "status": "success",
            "video_url": f"{base_url}/download/{video_filename}",
            "metadata": {
                "image": json.loads(image_info),
                "audio": json.loads(audio_info),
                "video_size": os.path.getsize(video_path),
                "duration": json.loads(audio_info)['streams'][0]['duration']
            }
        })

    except Exception as e:
        logger.exception("Unexpected error in video generation")
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Serve generated files"""
    try:
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            secure_filename(filename),
            as_attachment=True,
            mimetype='video/mp4' if filename.endswith('.mp4') else None
        )
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({"error": "File download failed"}), 500

@app.route('/healthcheck')
def health_check():
    """System health check endpoint"""
    status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "video-generator",
        "ffmpeg_available": check_ffmpeg(),
        "disk_space": shutil.disk_usage(app.config['UPLOAD_FOLDER'])._asdict(),
        "file_count": len(os.listdir(app.config['UPLOAD_FOLDER']))
    }
    return jsonify(status)

if __name__ == '__main__':
    # Verify system requirements
    if not os.access(app.config['UPLOAD_FOLDER'], os.W_OK):
        logger.error("Upload directory is not writable")
        sys.exit(1)
    
    if not check_ffmpeg():
        logger.error("FFmpeg/FFprobe not found. Please install first.")
        sys.exit(1)
    
    # Start the application
    app.run(host='0.0.0.0', port=10000, threaded=True)
