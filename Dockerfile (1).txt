FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# نسخ ملفات المشروع
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت Chromium
RUN playwright install chromium

# نسخ باقي الملفات
COPY . .

# إنشاء مجلد الجلسة
RUN mkdir -p /app/session_data

CMD ["python", "-u", "bot.py"]
