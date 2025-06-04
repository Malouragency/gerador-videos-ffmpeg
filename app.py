from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import os
import logging
from datetime import datetime

# Configuração básica
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configuração de logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.before_request
def log_request_info():
    """Log detalhado de todas as requisições"""
    logger.info(f"Headers: {dict(request.headers)}")
    logger.info(f"Method: {request.method}")
    logger.info(f"Form Data: {request.form}")
    logger.info(f"Files: {list(request.files.keys())}")

def allowed_file(filename):
    """Verifica extensões permitidas"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'jpg', 'jpeg', 'png', 'mp3', 'wav'}

@app.route('/generate', methods=['POST'])
def handle_generation():
    """Endpoint principal para processar arquivos"""
    try:
        # Verifica se arquivos foram enviados
        if not request.files:
            logger.error("Nenhum arquivo recebido")
            return jsonify({"error": "Envie arquivos no formato multipart"}), 400

        saved_files = {}
        
        # Processa cada arquivo
        for field_name, file in request.files.items():
            if file.filename == '':
                continue
                
            if not allowed_file(file.filename):
                logger.warning(f"Arquivo não permitido: {file.filename}")
                continue

            # Gera nome seguro com timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{field_name}_{timestamp}.{ext}"
            secure_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
            
            file.save(secure_path)
            saved_files[field_name] = filename
            logger.info(f"Arquivo salvo: {secure_path}")

        if not saved_files:
            logger.error("Nenhum arquivo válido recebido")
            return jsonify({"error": "Nenhum arquivo válido foi enviado"}), 400

        return jsonify({
            "status": "success",
            "message": "Arquivos processados com sucesso",
            "files": saved_files
        })

    except Exception as e:
        logger.exception("Erro durante o processamento")
        return jsonify({"error": str(e)}), 500

@app.route('/healthcheck', methods=['GET'])
def health_check():
    """Endpoint para verificação de saúde"""
    return jsonify({"status": "healthy", "version": "1.0.0"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
