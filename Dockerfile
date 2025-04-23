FROM python:3.11-slim

# Instalar FFmpeg y dependencias
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# Configurar directorio de trabajo
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Crear carpeta de descargas
RUN mkdir -p /app/downloads

# Configurar variables de entorno
ENV FLASK_APP=app.py
ENV PORT=8000

# Exponer puerto
EXPOSE 8000

# Comando para producción
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:$PORT", "app:app"]