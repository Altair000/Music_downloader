FROM python:3.11-slim

# Instalar FFmpeg y dependencias
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Establecer directorio de trabajo
WORKDIR /app

# Copiar archivos
COPY requirements.txt .
COPY bot.py .
COPY youtube_cookies.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Exponer puerto
EXPOSE 8443

# Comando para ejecutar el bot
CMD ["python", "bot.py"]
