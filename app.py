from flask import Flask, request, jsonify, send_from_directory, url_for
from werkzeug.utils import secure_filename
import os
import logging
from datetime import datetime
import subprocess

# Configuração básica
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'mp3', 'wav'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configuração de logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.before_request
def log_request_info():
    logger.info(f"Received {request.method} request to {request.path}")
    logger.info(f"Headers: {dict(request.headers)}")
    logger.info(f"Files: {list(request.files.keys())}")

def generate_video(image_path, audio_path, output_path):
    """Gera vídeo a partir de imagem e áudio usando FFmpeg"""
    try:
        cmd = [
            'ffmpeg',
            '-loop', '1',
            '-i', image_path,
            '-i', audio_path,
            '-c:v', 'libx264',
            '-tune', 'stillimage',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-shortest',
            '-y',  # Sobrescreve se existir
            output_path
        ]
        subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr.decode('utf-8')}")
        return False

@app.route('/generate', methods=['POST'])
def handle_generation():
    if not request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    try:
        # Salva arquivos recebidos
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
            file.save(filepath)
            saved_files[field] = filepath

        # Gera vídeo
        video_filename = f"video_{timestamp}.mp4"
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        
        if not generate_video(saved_files['image'], saved_files['audio'], video_path):
            return jsonify({"error": "Falha ao gerar vídeo"}), 500

        # Retorna URLs públicas
        base_url = request.host_url.rstrip('/')
        return jsonify({
            "status": "success",
            "download_url": f"{base_url}/download/{video_filename}",
            "files": {
                "image": f"{base_url}/download/{os.path.basename(saved_files['image'])}",
                "audio": f"{base_url}/download/{os.path.basename(saved_files['audio'])}",
                "video": video_filename
            }
        })

    except Exception as e:
        logger.exception("Erro durante processamento")
        return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=False
    )

@app.route('/healthcheck')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "video-generator"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
