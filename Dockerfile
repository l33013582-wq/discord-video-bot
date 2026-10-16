FROM python:3.11-slim

# Mencegah Python mem-buffer output log ke console
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies terlebih dahulu agar memanfaatkan Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode bot
COPY . .

# Jalankan bot
CMD ["python", "bot.py"]
