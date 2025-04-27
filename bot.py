import logging
import os
import time
import uuid
import re
import yt_dlp
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from threading import Thread
import shutil
from flask import Flask, request, Response

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '7985588609:AAFCJckm9Qg2TGqVCVs9d36ZwvX9ue6ySw4')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Configurar ffmpeg_location dinámicamente
if os.name == 'nt':  # Windows
    ffmpeg_location = shutil.which('ffmpeg') or 'ffmpeg'
else:
    ffmpeg_location = '/usr/bin/ffmpeg'

# Diccionarios para rastrear descargas
active_downloads = {}
completed_downloads = {}
download_errors = {}

# Sanitizar nombres de archivo
def sanitize_filename(filename):
    filename = re.sub(r'[^\w\s\-]', '', filename)
    filename = filename.replace(' ', '_').strip()
    return filename[:100] + '.mp3'

# Limpieza automática de archivos
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

# Comando /start
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "¡Hola! Soy un bot para descargar música. Envía el nombre de una canción para buscarla.")

# Manejar mensajes de texto (búsqueda)
@bot.message_handler(content_types=['text'])
def search_song(message):
    query = message.text
    logger.info(f"Búsqueda recibida: {query}")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': 'youtube_cookies.txt',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch10:{query}", download=False)['entries']
            if not results:
                bot.reply_to(message, "No se encontraron resultados para tu búsqueda.")
                return
            
            # Crear botones inline (5 en la primera fila, 5 en la segunda)
            keyboard = []
            for i in range(0, len(results), 5):
                row = [
                    InlineKeyboardButton(
                        text=result['title'][:40] + ('...' if len(result['title']) > 40 else ''),
                        callback_data=f"download:{result['id']}"
                    ) for result in results[i:i+5]
                ]
                keyboard.append(row)
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            bot.reply_to(message, f"Resultados para '{query}':", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error en búsqueda: {str(e)}")
        bot.reply_to(message, f"Error en la búsqueda: {str(e)}")

# Manejar selección de botón inline
@bot.callback_query_handler(func=lambda call: True)
def handle_button(call):
    callback_data = call.data
    if callback_data.startswith("download:"):
        video_id = callback_data.split(":", 1)[1]
        download_id = str(uuid.uuid4())
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        logger.info(f"Iniciando descarga para {download_id}: {url}")
        bot.reply_to(call.message, "Descargando canción... Por favor, espera.")
        
        # Iniciar descarga en un hilo separado
        Thread(target=download_song, args=(download_id, url, call.message.chat.id)).start()
        active_downloads[download_id] = {'video_id': video_id, 'chat_id': call.message.chat.id}

# Función para descargar la canción
def download_song(download_id, url, chat_id):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }, {
            'key': 'FFmpegMetadata',
        }, {
            'key': 'EmbedThumbnail',
            'already_have_thumbnail': False,
        }],
        'write_thumbnail': True,
        'ffmpeg_location': ffmpeg_location,
        'cookiefile': 'youtube_cookies.txt',
        'noplaylist': True,
        'retries': 5,
        'verbose': True,
        'format_sort': ['has_audio', 'ext:m4a,mp3'],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Descargando {url} para {download_id}")
            info = ydl.extract_info(url, download=True)
            raw_filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            logger.info(f"Archivo MP3 generado: {raw_filename}")
            
            if not os.path.exists(raw_filename):
                raise FileNotFoundError(f"Archivo MP3 no encontrado: {raw_filename}")
            
            safe_filename = sanitize_filename(info['title'])
            target_path = os.path.join(DOWNLOAD_FOLDER, safe_filename)
            logger.info(f"Renombrando {raw_filename} a {target_path}")
            if os.path.exists(target_path):
                os.remove(target_path)
            os.rename(raw_filename, target_path)
            
            if not os.path.exists(target_path):
                raise FileNotFoundError(f"Archivo no encontrado tras renombrar: {target_path}")
            
            # Enviar archivo MP3 como documento
            with open(target_path, 'rb') as mp3_file:
                bot.send_document(
                    chat_id=chat_id,
                    document=mp3_file,
                    caption="¡Aquí tienes tu canción en MP3 con la portada incrustada!",
                    file_name=safe_filename
                )
            
            completed_downloads[download_id] = {
                'filename': safe_filename,
                'chat_id': chat_id
            }
            logger.info(f"Descarga completada: {download_id}, archivo: {safe_filename}")
            active_downloads.pop(download_id, None)
            
    except Exception as e:
        logger.error(f"Error en descarga {download_id}: {str(e)}")
        download_errors[download_id] = str(e)
        bot.send_message(
            chat_id=chat_id,
            text=f"Error al descargar la canción: {str(e)}. Intenta con otro resultado o actualiza las cookies de YouTube."
        )
        active_downloads.pop(download_id, None)

# Ruta para el webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return Response(status=200)
    return Response(status=403)

# Configurar el bot con webhook
def main():
    webhook_url = os.environ.get('WEBHOOK_URL', 'bloody-salaidh-devsolutions-02d7b0ea.koyeb.app/webhook')
    port = int(os.environ.get('PORT', 8443))
    
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
