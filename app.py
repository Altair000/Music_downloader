from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import sqlite3
import os
import time
import uuid
import re
import logging
from threading import Thread

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
DOWNLOAD_FOLDER = "downloads"
app.config['UPLOAD_FOLDER'] = DOWNLOAD_FOLDER

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Diccionarios para rastrear descargas, errores y archivos completados
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
            active_downloads[download_id]['progress'] = percent
            logger.info(f"Progreso descarga {download_id}: {percent:.2f}%")
        elif d['status'] == 'finished':
            active_downloads[download_id]['progress'] = 100
            logger.info(f"Descarga {download_id} finalizada en progress_hook")

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
            'noplaylist': True,
            'retries': 5,
            'verbose': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Iniciando descarga para {download_id}: {url}")
                info = ydl.extract_info(url, download=True)
                # El postprocesador crea el archivo .mp3
                raw_filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
                logger.info(f"Archivo MP3 generado: {raw_filename}")
                # Verificar que el archivo exista
                if not os.path.exists(raw_filename):
                    raise FileNotFoundError(f"Archivo MP3 no encontrado: {raw_filename}")
                # Renombrar al nombre sanitizado
                safe_filename = sanitize_filename(info['title'])
                target_path = os.path.join(DOWNLOAD_FOLDER, safe_filename)
                logger.info(f"Renombrando {raw_filename} a {target_path}")
                if os.path.exists(target_path):
                    os.remove(target_path)  # Evitar conflictos
                os.rename(raw_filename, target_path)
                logger.info(f"Archivo renombrado: {target_path}")
                # Verificar archivo final
                if not os.path.exists(target_path):
                    raise FileNotFoundError(f"Archivo no encontrado tras renombrar: {target_path}")
            
            # Guardar en base de datos
            logger.info(f"Guardando en base de datos para {download_id}")
            conn = sqlite3.connect("database.db")
            c = conn.cursor()
            c.execute("INSERT INTO downloads (title, quality, timestamp) VALUES (?, ?, datetime('now'))", 
                      (info['title'], quality))
            conn.commit()
            conn.close()

            # Almacenar el archivo completado
            completed_downloads[download_id] = {'filename': safe_filename}
            logger.info(f"Descarga completada: {download_id}, archivo: {safe_filename}, almacenado en completed_downloads")
            active_downloads.pop(download_id, None)
        except Exception as e:
            logger.error(f"Error en descarga {download_id}: {str(e)}")
            download_errors[download_id] = str(e)
            active_downloads.pop(download_id, None)

    active_downloads[download_id] = {'video_id': video_id, 'quality': quality, 'progress': 0}
    logger.info(f"Iniciando hilo de descarga para {download_id}")
    Thread(target=download_song, args=(download_id, url, quality)).start()

    return render_template('download.html', title="Descargando...", download_id=download_id)

@app.route('/download_status/<download_id>', methods=['GET'])
def download_status(download_id):
    logger.info(f"Consulta de estado para {download_id}")
    if download_id in download_errors:
        error = download_errors[download_id]
        logger.info(f"Estado error para {download_id}: {error}")
        return jsonify({'status': 'error', 'message': error})
    elif download_id in completed_downloads:
        filename = completed_downloads[download_id]['filename']
        logger.info(f"Estado completo para {download_id}: {filename}")
        completed_downloads.pop(download_id, None)  # Limpiar
        return jsonify({'status': 'complete', 'filename': filename})
    elif download_id in active_downloads:
        progress = active_downloads[download_id]['progress']
        logger.info(f"Estado descargando para {download_id}: {progress}%")
        return jsonify({'status': 'downloading', 'progress': progress})
    else:
        logger.warning(f"Descarga no encontrada: {download_id}")
        return jsonify({'status': 'error', 'message': 'Descarga no encontrada'}), 404

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
        logger.info(f"Enviando archivo: {filename}")
        return send_file(file_path, as_attachment=True)
    logger.warning(f"Archivo no encontrado: {filename}")
    return jsonify({'error': 'Archivo no encontrado'}), 404

if __name__ == '__main__':
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
