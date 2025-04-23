from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import yt_dlp
import sqlite3
import os
import time
import uuid
import re
import logging
from threading import Thread

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'i802r4rl')
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*", manage_session=True)
DOWNLOAD_FOLDER = "downloads"
app.config['UPLOAD_FOLDER'] = DOWNLOAD_FOLDER

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Diccionarios para rastrear descargas, errores y descargas completadas
active_downloads = {}
download_errors = {}
completed_downloads = {}

# Crear base de datos
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS downloads 
                 (id INTEGER PRIMARY KEY, title TEXT, quality TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Limpieza automática
def clean_old_files():
    while True:
        now = time.time()
        for filename in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, filename)
            if os.path.isfile(file_path):
                if now - os.path.getmtime(file_path) > 3600:  # 1 hora
                    os.remove(file_path)
        time.sleep(3600)

Thread(target=clean_old_files, daemon=True).start()

# Sanitizar nombres de archivo
def sanitize_filename(filename):
    filename = re.sub(r'[^\w\s\-]', '', filename)
    filename = filename.replace(' ', '_').strip()
    return filename[:100] + '.mp3'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': 'youtube_cookies.txt',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch5:{query}", download=False)['entries']
            songs = [{'title': r['title'], 'id': r['id'], 'url': r['url']} for r in results]
        return render_template('results.html', songs=songs, query=query)
    except Exception as e:
        logger.error(f"Error en búsqueda: {str(e)}")
        return jsonify({'error': 'Error en la búsqueda: ' + str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    video_id = request.form['video_id']
    quality = request.form['quality']
    download_id = str(uuid.uuid4())
    url = f"https://www.youtube.com/watch?v={video_id}"

    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
            emit('progress', {'percent': percent, 'download_id': download_id}, namespace='/download')
        elif d['status'] == 'finished':
            emit('progress', {'percent': 100, 'download_id': download_id}, namespace='/download')

    def download_song(download_id, url, quality):
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': quality,
            }],
            'progress_hooks': [progress_hook],
            'ffmpeg_location': '/usr/bin/ffmpeg',
            'cookiefile': 'youtube_cookies.txt',
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                raw_filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
                safe_filename = sanitize_filename(info['title'])
                os.rename(raw_filename, os.path.join(DOWNLOAD_FOLDER, safe_filename))
            
            conn = sqlite3.connect("database.db")
            c = conn.cursor()
            c.execute("INSERT INTO downloads (title, quality, timestamp) VALUES (?, ?, datetime('now'))", 
                      (info['title'], quality))
            conn.commit()
            conn.close()

            # Almacenar la descarga completada en lugar de emitir directamente
            completed_downloads[download_id] = {'filename': safe_filename}
            active_downloads.pop(download_id, None)
        except Exception as e:
            logger.error(f"Error en descarga {download_id}: {str(e)}")
            download_errors[download_id] = str(e)
            active_downloads.pop(download_id, None)

    active_downloads[download_id] = {'video_id': video_id, 'quality': quality}
    Thread(target=download_song, args=(download_id, url, quality)).start()

    # Manejar errores y descargas completadas desde el cliente
    @socketio.on('check_error', namespace='/download')
    def check_error(data):
        if data['download_id'] in download_errors:
            emit('error', {'message': download_errors[data['download_id']], 'download_id': data['download_id']}, namespace='/download')
            download_errors.pop(data['download_id'], None)

    @socketio.on('check_complete', namespace='/download')
    def check_complete(data):
        if data['download_id'] in completed_downloads:
            emit('download_complete', {
                'filename': completed_downloads[data['download_id']]['filename'],
                'download_id': data['download_id']
            }, namespace='/download')
            completed_downloads.pop(data['download_id'], None)

    return render_template('download.html', title="Descargando...", download_id=download_id)

@app.route('/history')
def history():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT title, quality, timestamp FROM downloads ORDER BY timestamp DESC")
    history = c.fetchall()
    conn.close()
    return jsonify(history)

@app.route('/get_file/<filename>')
def get_file(filename):
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return jsonify({'error': 'Archivo no encontrado'}), 404

if __name__ == '__main__':
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
