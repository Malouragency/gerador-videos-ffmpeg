from flask import Flask, request, send_file
import subprocess

app = Flask(__name__)

@app.route('/generate', methods=['POST'])
def generate_video():
    audio = request.files['audio']
    images = [request.files[f'image{i}'] for i in range(1, 6)]
    
    audio.save('audio.wav')
    for i, img in enumerate(images):
        img.save(f'img{i+1}.jpg')

    cmd = [
        'ffmpeg', '-i', 'audio.mp3',
        *[f'-loop 1 -i img{i+1}.jpg' for i in range(5)],
        '-filter_complex',
        ';'.join([
            f'[{i}:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,'
            f'zoompan=z="if(lte(zoom,1.0),1.5,zoom-0.003)":d=1:s=720x1280[v{i}]'
            for i in range(5)
        ]) + ';' + ''.join([f'[v{i}]' for i in range(5)]) + 'concat=n=5:v=1[v]',
        '-map', '[v]', '-map', '0:a',
        '-c:v', 'libx264', '-c:a', 'aac',
        '-shortest', 'output.mp4'
    ]
    subprocess.run(cmd, check=True)
    return send_file('output.mp4')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
