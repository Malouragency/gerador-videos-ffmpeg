from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import logging
from datetime import datetime
import subprocess
import sys

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'mp3', 'wav'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configuração de logs
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
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def check_ffmpeg():
    """Verifica se o FFmpeg está instalado e acessível"""
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def validate_media_files(image_path, audio_path):
    """Verifica se os arquivos de mídia são válidos"""
    try:
        # Verifica imagem
        img_check = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name,width,height', '-of', 'csv=p=0', image_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        # Verifica áudio
        audio_check = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_name,sample_rate,channels', '-of', 'csv=p=0', audio_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        if img_check.returncode != 0:
            logger.error(f"Invalid image file: {img_check.stderr.decode('utf-8')}")
            return False
        
        if audio_check.returncode != 0:
            logger.error(f"Invalid audio file: {audio_check.stderr.decode('utf-8')}")
            return False
            
        return True
    except Exception as e:
        logger.error(f"Error validating media files: {str(e)}")
        return False

def generate_video(image_path, audio_path, output_path):
    """Gera vídeo a partir de imagem e áudio usando FFmpeg"""
    try:
        cmd = [
            'ffmpeg',
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
        result = subprocess.run(cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=300)
        logger.info(f"FFmpeg output: {result.stdout.decode('utf-8')}")
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8') if e.stderr else 'No error message'
        logger.error(f"FFmpeg command failed: {' '.join(cmd)}")
        logger.error(f"FFmpeg stderr: {error_msg}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timeout expired")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in generate_video: {str(e)}")
        return False

def generate_fallback_video(image_path, audio_path, output_path):
    """Método alternativo mais simples para gerar vídeo"""
    try:
        cmd = [
            'ffmpeg',
            '-loop', '1',
            '-i', image_path,
            '-i', audio_path,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-strict', 'experimental',
            '-shortest',
            '-y',
            output_path
        ]
        result = subprocess.run(cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=300)
        logger.info(f"Fallback FFmpeg output: {result.stdout.decode('utf-8')}")
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8') if e.stderr else 'No error message'
        logger.error(f"Fallback FFmpeg error: {error_msg}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("Fallback FFmpeg timeout expired")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in fallback video generation: {str(e)}")
        return False

@app.before_request
def log_request_info():
    logger.info(f"Received {request.method} request to {request.path}")
    if request.files:
        logger.info(f"Files received: {list(request.files.keys())}")

@app.route('/generate', methods=['POST'])
def handle_generation():
    if not check_ffmpeg():
        return jsonify({"error": "FFmpeg não está instalado ou não pôde ser executado"}), 500

    if not request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    try:
        saved_files = {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for field in ['image', 'audio']:
            if field not in request.files:
                return jsonify({"error": f"Arquivo {field} faltando"}), 400
            
            file = request.files[field]
            if file.filename == '':
                return jsonify({"error": f"Nome de arquivo vazio para {field}"}), 400
            
            if not allowed_file(file.filename):
                return jsonify({"error": f"Tipo de arquivo não permitido para {field}"}), 400
            
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{field}_{timestamp}.{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
            
            try:
                file.save(filepath)
                saved_files[field] = filepath
            except Exception as e:
                logger.error(f"Error saving {field} file: {str(e)}")
                return jsonify({"error": f"Falha ao salvar arquivo {field}"}), 500

        # Valida os arquivos antes de processar
        if not validate_media_files(saved_files['image'], saved_files['audio']):
            return jsonify({"error": "Arquivos de imagem ou áudio inválidos"}), 400

        # Gera vídeo
        video_filename = f"video_{timestamp}.mp4"
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        
        if not generate_video(saved_files['image'], saved_files['audio'], video_path):
            logger.info("Trying fallback FFmpeg command")
            if not generate_fallback_video(saved_files['image'], saved_files['audio'], video_path):
                return jsonify({"error": "Falha ao gerar vídeo. Verifique os logs do servidor."}), 500

        # Verifica se o vídeo foi criado
        if not os.path.exists(video_path):
            logger.error(f"Video file not created at expected path: {video_path}")
            return jsonify({"error": "Vídeo não foi gerado corretamente"}), 500

        # Retorna URLs públicas
        base_url = request.host_url.rstrip('/')
        return jsonify({
            "status": "success",
            "download_url": f"{base_url}/download/{video_filename}",
            "files": {
                "image": f"{base_url}/download/{os.pathasename(saved_files['image'])}",
                "audio": f"{base_url}/download/{os.path.basename(saved_files['audio'])}",
                "video": video_filename
            }
        })

    except Exception as e:
        logger.exception(f"Unexpected error in handle_generation: {str(e)}")
        return jsonify({"error": "Erro interno do servidor"}), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            secure_filename(filename),
            as_attachment=False
        )
    except FileNotFoundError:
        return jsonify({"error": "Arquivo não encontrado"}), 404

@app.route('/healthcheck')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "video-generator",
        "ffmpeg_available": check_ffmpeg(),
        "upload_folder_writable": os.access(app.config['UPLOAD_FOLDER'], os.W_OK)
    })

if __name__ == '__main__':
    # Verifica permissões da pasta de uploads
    if not os.access(app.config['UPLOAD_FOLDER'], os.W_OK):
        logger.error(f"Upload folder is not writable: {app.config['UPLOAD_FOLDER']}")
        sys.exit(1)
    
    # Verifica FFmpeg antes de iniciar
    if not check_ffmpeg():
        logger.error("FFmpeg is not available. Please install FFmpeg first.")
        sys.exit(1)
    
    app.run(host='0.0.0.0', port=10000, debug=True)
