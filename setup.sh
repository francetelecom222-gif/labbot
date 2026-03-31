#!/bin/bash
# ══════════════════════════════════════
# تثبيت وتشغيل بوت Google Skills Lab
# ══════════════════════════════════════

echo "📦 تثبيت المكتبات..."
pip install -r requirements.txt --break-system-packages -q

echo "🌐 تثبيت متصفح Chromium..."
playwright install chromium

echo "✅ جاهز! يمكنك تشغيل البوت الآن:"
echo "python bot.py"
