#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║   Google Skills Lab Bot  -  النسخة النهائية v3      ║
║   تسجيل دخول عبر Google دائماً + حفظ جلسة          ║
╚══════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import random
import re
import sys
import traceback
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from playwright.async_api import async_playwright, Page, BrowserContext

# ╔══════════════════════════════════════════╗
# ║              ⚙️ الإعدادات               ║
# ╚══════════════════════════════════════════╝
TELEGRAM_TOKEN  = "ضع_توكن_البوت_هنا"
CHAT_ID         = "ضع_chat_id_هنا"
GOOGLE_EMAIL    = "francetelecom222@gmail.com"
GOOGLE_PASSWORD = "ضع_كلمة_السر_هنا"
LAB_URL         = "https://www.skills.google/focuses/19146?parent=catalog"
SESSION_DIR     = Path("./session_data")
SESSION_FILE    = SESSION_DIR / "google_session.json"
# ════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

page_global:       Optional[Page] = None
waiting_captcha:   bool           = False
selected_cells:    set            = set()
step_log:          list           = []
bot_running:       bool           = False
_tg_bot:           Optional[Bot]  = None
use_saved_session: bool           = True


# ══════════════════════════════════════════════════════════
#  مساعدات عامة
# ══════════════════════════════════════════════════════════

def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log_step(emoji: str, msg: str) -> str:
    line = f"{emoji} [{now_str()}] {msg}"
    step_log.append(line)
    log.info(msg)
    return line

async def rand_sleep(lo: float = 0.5, hi: float = 2.0):
    await asyncio.sleep(random.uniform(lo, hi))

async def human_move(page: Page):
    for _ in range(random.randint(3, 6)):
        await page.mouse.move(
            random.randint(80, 1280),
            random.randint(80, 720),
            steps=random.randint(10, 30),
        )
        await rand_sleep(0.05, 0.25)
    if random.random() < 0.4:
        await page.mouse.wheel(0, random.randint(-150, 150))
        await rand_sleep(0.1, 0.3)

async def human_type(page: Page, selector: str, text: str):
    await page.click(selector)
    await rand_sleep(0.4, 0.9)
    await page.keyboard.press("Control+a")
    await asyncio.sleep(0.15)
    await page.keyboard.press("Delete")
    await rand_sleep(0.2, 0.5)
    for ch in text:
        if random.random() < 0.04:
            fat = random.choice("qwertyuiopasdfghjklzxcvbnm")
            await page.keyboard.type(fat)
            await rand_sleep(0.08, 0.18)
            await page.keyboard.press("Backspace")
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.06, 0.22))
        if random.random() < 0.03:
            await rand_sleep(0.3, 0.8)
    await rand_sleep(0.3, 0.7)

async def safe_screenshot(page: Page) -> Optional[bytes]:
    try:
        return await page.screenshot(full_page=False, type="png")
    except Exception as e:
        log.warning(f"screenshot fail: {e}")
        return None


# ══════════════════════════════════════════════════════════
#  Telegram
# ══════════════════════════════════════════════════════════

def _bot() -> Bot:
    global _tg_bot
    if _tg_bot is None:
        _tg_bot = Bot(token=TELEGRAM_TOKEN)
    return _tg_bot

def _trim(text: str, limit: int = 4000) -> str:
    return text[:limit] + "…" if len(text) > limit else text

async def tg_msg(text: str, keyboard=None):
    try:
        await _bot().send_message(
            chat_id=CHAT_ID, text=_trim(text),
            reply_markup=keyboard, parse_mode="HTML",
        )
    except Exception as e:
        log.error(f"tg_msg: {e}")

async def tg_photo(img: bytes, caption: str, keyboard=None):
    try:
        await _bot().send_photo(
            chat_id=CHAT_ID, photo=img,
            caption=_trim(caption, 950),
            reply_markup=keyboard, parse_mode="HTML",
        )
    except Exception as e:
        log.error(f"tg_photo: {e}")

async def tg_step(page: Page, emoji: str, msg: str):
    line = log_step(emoji, msg)
    img  = await safe_screenshot(page)
    if img:
        await tg_photo(img, f"<b>{line}</b>")
    else:
        await tg_msg(f"<b>{line}</b>")

async def tg_error(page: Optional[Page], error: Exception, context: str = ""):
    tb    = traceback.format_exc()
    short = str(error)[:400]
    await tg_msg(
        f"❌ <b>خطأ في: {context}</b>\n"
        f"<code>{short}</code>\n\n"
        f"📋 <b>Traceback:</b>\n<code>{tb[:600]}</code>"
    )
    if page:
        img = await safe_screenshot(page)
        if img:
            await tg_photo(img, f"📸 صورة عند خطأ: {context}")


# ══════════════════════════════════════════════════════════
#  الجلسة
# ══════════════════════════════════════════════════════════

def session_exists() -> bool:
    return SESSION_FILE.exists() and SESSION_FILE.stat().st_size > 100

async def save_session(ctx: BrowserContext):
    try:
        SESSION_DIR.mkdir(exist_ok=True)
        storage = await ctx.storage_state()
        SESSION_FILE.write_text(json.dumps(storage, ensure_ascii=False, indent=2))
        log_step("💾", "تم حفظ الجلسة")
        await tg_msg("💾 <b>تم حفظ الجلسة!</b> لن تحتاج كلمة السر مرة أخرى.")
    except Exception as e:
        log_step("⚠️", f"فشل حفظ الجلسة: {e}")

async def inject_stealth(ctx: BrowserContext):
    await ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        try { delete navigator.__proto__.webdriver; } catch(e) {}
        window.chrome = {
            runtime: { onConnect:{addListener:()=>{}}, onMessage:{addListener:()=>{}},
                       connect:()=>{}, sendMessage:()=>{} },
            loadTimes:()=>{}, csi:()=>{}, app:{isInstalled:false},
        };
        Object.defineProperty(navigator,'languages',{get:()=>['en-US','en','fr']});
        const _q = window.navigator.permissions.query.bind(navigator.permissions);
        window.navigator.permissions.query = p =>
            p.name==='notifications' ? Promise.resolve({state:Notification.permission}) : _q(p);
        Object.defineProperty(screen,'width', {get:()=>1366});
        Object.defineProperty(screen,'height',{get:()=>768});
        const gp = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {
            if(p===37445) return 'Intel Inc.';
            if(p===37446) return 'Intel Iris OpenGL Engine';
            return gp.call(this,p);
        };
    """)


# ══════════════════════════════════════════════════════════
#  مساعدات الأتمتة
# ══════════════════════════════════════════════════════════

async def _element_exists(page: Page, selector: str, timeout=5000) -> bool:
    try:
        await page.wait_for_selector(selector, timeout=timeout, state="visible")
        return True
    except:
        return False

async def _safe_click(page: Page, selectors: list, label: str, timeout=8000) -> bool:
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=timeout, state="visible")
            await human_move(page)
            await rand_sleep(0.4, 1.0)
            await page.click(sel)
            log_step("✅", f"ضُغط: {label}")
            await tg_msg(f"✅ <b>ضُغط:</b> {label}")
            await rand_sleep(0.5, 1.5)
            return True
        except:
            continue
    log_step("⚠️", f"لم يُجد: {label}")
    await tg_msg(f"⚠️ <b>لم أجد:</b> {label}")
    return False


# ══════════════════════════════════════════════════════════
#  تسجيل الدخول عبر Google
# ══════════════════════════════════════════════════════════

async def do_google_signin(page: Page, ctx: BrowserContext):
    """
    يضغط Sign in with Google دائماً
    ثم يختار francetelecom222@gmail.com من القائمة
    """
    await tg_msg("🔐 <b>يضغط Sign in with Google...</b>")

    clicked = await _safe_click(page, [
        'text=Sign in with Google',
        'a:has-text("Sign in with Google")',
        'button:has-text("Sign in with Google")',
        '[data-provider="google"]',
    ], "Sign in with Google", timeout=10000)

    if not clicked:
        await tg_step(page, "⚠️", "لم أجد Sign in with Google!")
        return

    await rand_sleep(2, 4)
    await tg_step(page, "🔐", "فُتحت صفحة Google")

    # ── اختيار الحساب ───────────────────────────────
    account_found = False

    # محاولة 1: div[data-identifier]
    try:
        await page.wait_for_selector('div[data-identifier]', timeout=8000)
        locator = page.locator(f'div[data-identifier="{GOOGLE_EMAIL}"]')
        if await locator.count() > 0:
            await human_move(page)
            await rand_sleep(0.8, 1.8)
            await locator.click()
            await tg_msg(f"👤 <b>اختار:</b> {GOOGLE_EMAIL}")
            account_found = True
        else:
            # ابحث بالنص
            all_accs = await page.locator('div[data-identifier]').all()
            for acc in all_accs:
                txt = await acc.inner_text()
                if "francetelecom" in txt.lower() or GOOGLE_EMAIL in txt:
                    await human_move(page)
                    await acc.click()
                    await tg_msg(f"👤 <b>اختار الحساب:</b> {txt[:60]}")
                    account_found = True
                    break
    except:
        pass

    # محاولة 2: li:has-text
    if not account_found:
        try:
            await page.wait_for_selector(f'li:has-text("{GOOGLE_EMAIL}")', timeout=5000)
            await page.click(f'li:has-text("{GOOGLE_EMAIL}")')
            await tg_msg("👤 <b>اختار الحساب من القائمة</b>")
            account_found = True
        except:
            pass

    # محاولة 3: أي عنصر يحوي الإيميل
    if not account_found:
        try:
            locator = page.locator(f':has-text("{GOOGLE_EMAIL}")').first
            if await locator.count() > 0:
                await locator.click()
                await tg_msg("👤 <b>اختار الحساب (بديل)</b>")
                account_found = True
        except:
            pass

    await rand_sleep(2, 4)

    # ── إذا لم يجد → Use another account ───────────
    if not account_found:
        await tg_step(page, "📧", "لم أجد الحساب - سأستخدم Use another account")
        if await _element_exists(page, 'text=Use another account', timeout=4000):
            await page.click('text=Use another account')
            await rand_sleep(1, 2)
        try:
            await page.wait_for_selector('input[type="email"]', timeout=8000)
            await tg_step(page, "📧", "يُدخل الإيميل...")
            await human_type(page, 'input[type="email"]', GOOGLE_EMAIL)
            await _safe_click(page, ['#identifierNext','button:has-text("Next")','text=Next'], "Next")
            await rand_sleep(2, 4)
        except Exception as e:
            await tg_error(page, e, "إدخال الإيميل")

    # ── كلمة السر إذا طُلبت ─────────────────────────
    try:
        if await _element_exists(page, 'input[type="password"]', timeout=8000):
            await tg_step(page, "🔑", "يُدخل كلمة السر...")
            await human_type(page, 'input[type="password"]', GOOGLE_PASSWORD)
            await _safe_click(page, ['#passwordNext','button:has-text("Next")','text=Next'], "Next")
            await rand_sleep(3, 6)
            await tg_step(page, "✅", "تم تسجيل الدخول!")
        else:
            await tg_step(page, "✅", "تم الدخول بدون كلمة سر (جلسة محفوظة)!")
        await save_session(ctx)
    except Exception as e:
        await tg_error(page, e, "كلمة السر")


# ══════════════════════════════════════════════════════════
#  reCAPTCHA
# ══════════════════════════════════════════════════════════

async def handle_recaptcha(page: Page):
    global waiting_captcha, selected_cells

    await tg_msg("🔍 <b>يبحث عن reCAPTCHA...</b>")

    if not await _element_exists(page, 'iframe[title*="reCAPTCHA"]', timeout=8000):
        await tg_msg("✅ <b>لا توجد reCAPTCHA!</b>")
        return

    await tg_msg("☑️ <b>وجدت reCAPTCHA - يضغط I'm not a robot...</b>")
    await rand_sleep(1, 2)
    await human_move(page)

    try:
        fr = page.frame_locator('iframe[title*="reCAPTCHA"]')
        cb = fr.locator('#recaptcha-anchor')
        await cb.wait_for(timeout=8000)
        await rand_sleep(0.8, 2.0)
        await cb.click()
        await tg_msg("☑️ <b>ضُغط I'm not a robot!</b>")
        await rand_sleep(2, 4)
    except Exception as e:
        await tg_error(page, e, "CAPTCHA checkbox")
        return

    if not await _element_exists(page, 'iframe[title*="recaptcha challenge"]', timeout=6000):
        await tg_step(page, "✅", "CAPTCHA اجتيزت تلقائياً! 🎉")
        return

    await tg_msg("🖼️ <b>ظهرت صور CAPTCHA - أرسلها!</b>")
    await _send_captcha_to_user(page)

    await tg_msg("⏳ <b>انتظر إجابتك (3 دقائق)</b>")
    for _ in range(180):
        if not waiting_captcha:
            break
        await asyncio.sleep(1)

    if waiting_captcha:
        await tg_msg("⏰ <b>انتهت مهلة CAPTCHA</b>")
        waiting_captcha = False


async def _send_captcha_to_user(page: Page):
    global waiting_captcha, selected_cells
    waiting_captcha = True
    selected_cells  = set()

    img = await safe_screenshot(page)
    try:
        cf  = page.frame_locator('iframe[title*="recaptcha challenge"]')
        box = await cf.locator('.rc-imageselect').bounding_box()
        if box and box["width"] > 10:
            img = await page.screenshot(clip={
                "x": max(0, box["x"]-5), "y": max(0, box["y"]-5),
                "width": box["width"]+10, "height": box["height"]+10,
            }, type="png")
    except:
        pass

    question = "اختر الصور المطلوبة"
    for sel in ['.rc-imageselect-desc-no-canonical', '.rc-imageselect-desc']:
        try:
            cf = page.frame_locator('iframe[title*="recaptcha challenge"]')
            q  = await cf.locator(sel).inner_text(timeout=3000)
            if q.strip():
                question = q.strip()
                break
        except:
            continue

    caption = (
        f"🖼️ <b>CAPTCHA - حلّها!</b>\n📌 <i>{question}</i>\n\n"
        f"<code>1️⃣ 2️⃣ 3️⃣\n4️⃣ 5️⃣ 6️⃣\n7️⃣ 8️⃣ 9️⃣</code>\n\n"
        f"اضغط الأرقام الصحيحة ثم ✅ تأكيد"
    )
    if img:
        await tg_photo(img, caption, keyboard=_captcha_kb())
    else:
        await tg_msg(caption, keyboard=_captcha_kb())


def _captcha_kb() -> InlineKeyboardMarkup:
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            n   = r*3+c+1
            lbl = f"✅{n}" if n in selected_cells else str(n)
            row.append(InlineKeyboardButton(lbl, callback_data=f"cap_{n}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✅ تأكيد",  callback_data="cap_confirm"),
        InlineKeyboardButton("🔄 تحديث", callback_data="cap_refresh"),
        InlineKeyboardButton("⏭️ تخطي",  callback_data="cap_skip"),
    ])
    return InlineKeyboardMarkup(rows)


async def apply_captcha_selection(page: Page):
    global waiting_captcha, selected_cells
    try:
        cf    = page.frame_locator('iframe[title*="recaptcha challenge"]')
        tiles = await cf.locator('td.rc-imageselect-tile').all()
        await tg_msg(f"🖱️ <b>خلايا: {len(tiles)} | مختار: {sorted(selected_cells)}</b>")
        for n in sorted(selected_cells):
            if 1 <= n <= len(tiles):
                await tiles[n-1].click()
                await tg_msg(f"🖱️ خلية {n}")
                await rand_sleep(0.5, 1.2)
        await rand_sleep(0.8, 1.5)
        vb = cf.locator('#recaptcha-verify-button')
        await vb.wait_for(timeout=5000)
        await vb.click()
        await tg_msg("✅ <b>ضُغط Verify!</b>")
        await rand_sleep(2, 4)
        img = await safe_screenshot(page)
        if img:
            await tg_photo(img, "📸 بعد CAPTCHA")
    except Exception as e:
        await tg_error(page, e, "تطبيق CAPTCHA")
    finally:
        waiting_captcha = False


async def _wait_for_lab_link(page: Page, timeout: int = 90) -> Optional[str]:
    patterns = [
        r'https://console\.cloud\.google\.com/[^\s"\'<>\)]+',
        r'https://[a-z0-9\-]+\.cloudshell\.dev[^\s"\'<>\)]*',
        r'https://ide\.cloud\.google\.com[^\s"\'<>\)]*',
        r'https://[a-z0-9\-]+\.qwiklabs\.com[^\s"\'<>\)]*',
    ]
    for i in range(timeout):
        try:
            html = await page.content()
            for pat in patterns:
                m = re.search(pat, html)
                if m:
                    return m.group(0).rstrip('.,;')
        except:
            pass
        if i % 15 == 0 and i > 0:
            await tg_msg(f"⏳ <b>ينتظر رابط Lab... {i}/{timeout}s</b>")
        await asyncio.sleep(1)
    return None


# ══════════════════════════════════════════════════════════
#  الدالة الرئيسية
# ══════════════════════════════════════════════════════════

async def start_lab_automation():
    global page_global, bot_running, step_log

    bot_running = True
    step_log    = []

    await tg_msg(
        "🤖 <b>البوت انطلق! v3</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔐 يضغط Sign in with Google\n"
        "👤 يختار حسابك تلقائياً\n"
        "📸 صورة عند كل خطوة\n"
        "🔔 تقرير فوري لكل حدث\n"
        "❌ أي خطأ يُرسل مع صورة\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars", "--window-size=1366,768",
                "--lang=en-US", "--disable-web-security",
            ],
        )

        ctx_args = dict(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
        )

        # تحميل الجلسة
        if use_saved_session and session_exists():
            try:
                storage = json.loads(SESSION_FILE.read_text())
                ctx = await browser.new_context(**ctx_args, storage_state=storage)
                await tg_msg("📂 <b>تم تحميل الجلسة المحفوظة!</b>")
            except:
                ctx = await browser.new_context(**ctx_args)
                await tg_msg("⚠️ <b>فشل تحميل الجلسة - جلسة جديدة</b>")
        else:
            ctx = await browser.new_context(**ctx_args)
            await tg_msg("🆕 <b>جلسة جديدة</b>")

        await inject_stealth(ctx)
        page        = await ctx.new_page()
        page_global = page
        await page.goto("about:blank")
        await human_move(page)

        try:
            # 1️⃣ فتح Lab
            await tg_msg(f"🌐 <b>يفتح Lab...</b>")
            await page.goto(LAB_URL, wait_until="domcontentloaded", timeout=45000)
            await rand_sleep(2, 4)
            await human_move(page)
            await tg_step(page, "🌐", "فُتحت صفحة Lab")

            # 2️⃣ Sign in
            if await _element_exists(page, 'text=Sign in', timeout=6000):
                await tg_step(page, "🔐", "يضغط Sign in...")
                await _safe_click(page, [
                    'text=Sign in', 'a[href*="sign_in"]',
                    'button:has-text("Sign in")',
                ], "Sign in")
                await rand_sleep(2, 4)
                # 3️⃣ Sign in with Google
                await do_google_signin(page, ctx)
            else:
                await tg_msg("ℹ️ <b>مسجل بالفعل!</b>")

            # 4️⃣ إغلاق Credits popup
            await rand_sleep(2, 3)
            if await _element_exists(page, 'text=Dismiss', timeout=5000):
                await _safe_click(page, ['text=Dismiss','button:has-text("Dismiss")'], "Dismiss")
                await tg_step(page, "💰", "أُغلقت نافذة Credits")
            else:
                await tg_msg("ℹ️ <b>لا توجد نافذة Credits</b>")

            # 5️⃣ Start Lab
            await tg_step(page, "🧪", "يبحث عن Start Lab...")
            for attempt in range(20):
                try:
                    disabled = await page.evaluate(
                        "() => { const b = document.querySelector('button'); "
                        "return b ? b.disabled : true; }"
                    )
                    if not disabled:
                        break
                except:
                    break
                if attempt % 5 == 0:
                    await tg_msg(f"⏳ <b>ينتظر Start Lab... {attempt}s</b>")
                await asyncio.sleep(1)

            clicked = await _safe_click(page, [
                'button:has-text("Start Lab"):not([disabled])',
                'button:has-text("Start Lab")',
                'text=Start Lab',
            ], "Start Lab", timeout=15000)

            if not clicked:
                await tg_step(page, "❌", "لم أجد Start Lab!")
                return

            await rand_sleep(2, 4)
            await tg_step(page, "🧪", "ضُغط Start Lab! ✅")

            # 6️⃣ reCAPTCHA
            await handle_recaptcha(page)

            # 7️⃣ Launch with Credits
            await tg_msg("💳 <b>يبحث عن Launch with Credits...</b>")
            launched = await _safe_click(page, [
                'text=Launch with 5 Credits',
                'button:has-text("Launch with")',
                'button:has-text("Launch")',
            ], "Launch Credits", timeout=20000)

            if launched:
                await tg_step(page, "💳", "ضُغط Launch! ✅")
            else:
                await tg_step(page, "⚠️", "لم أجد Launch - صورة أرسلت")

            # 8️⃣ رابط Lab
            await tg_msg("⏳ <b>ينتظر رابط Lab (90s)...</b>")
            link = await _wait_for_lab_link(page, timeout=90)

            if link:
                await tg_msg(
                    f"🎉 <b>تم بنجاح!</b>\n\n"
                    f"🔗 <b>رابط Lab:</b>\n<code>{link}</code>\n\n"
                    f"اضغط للدخول 👆"
                )
                await tg_step(page, "🏁", "اكتمل! 🎉")
            else:
                await tg_step(page, "🔎", "لم أجد رابطاً - ابحث في الصورة")

        except Exception as exc:
            await tg_error(page, exc, "التشغيل الرئيسي")

        finally:
            summary = "📋 <b>ملخص:</b>\n<code>" + "\n".join(step_log) + "</code>"
            await tg_msg(summary)
            await browser.close()
            bot_running  = False
            page_global  = None


# ══════════════════════════════════════════════════════════
#  معالجات Telegram
# ══════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s  = "✅ جلسة محفوظة" if session_exists() else "⚠️ لا توجد جلسة"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ابدأ (جلسة محفوظة)", callback_data="do_start_saved")],
        [InlineKeyboardButton("🆕 ابدأ (تسجيل جديد)",  callback_data="do_start_fresh")],
        [InlineKeyboardButton("📸 صورة لحظية",          callback_data="do_shot")],
        [InlineKeyboardButton("📋 سجل الخطوات",         callback_data="do_log")],
        [InlineKeyboardButton("🗑️ حذف الجلسة",         callback_data="do_clear")],
        [InlineKeyboardButton("⛔ إيقاف",                callback_data="do_stop")],
    ])
    await update.message.reply_text(
        f"👋 <b>بوت Google Skills Lab v3</b>\n\n"
        f"💾 <b>الجلسة:</b> {s}\n\n"
        "🔐 يضغط Sign in with Google دائماً\n"
        "👤 يختار حسابك تلقائياً\n"
        "📸 صورة عند كل خطوة\n"
        "❌ أي خطأ يُرسل مع صورة وتفاصيل\n\n"
        "اختر 👇",
        reply_markup=kb, parse_mode="HTML",
    )

async def cmd_screenshot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if page_global:
        img = await safe_screenshot(page_global)
        if img:
            await update.message.reply_photo(img, caption=f"📸 [{now_str()}]")
        else:
            await update.message.reply_text("⚠️ فشل التقاط الصورة")
    else:
        await update.message.reply_text("⚠️ المتصفح غير مشغّل")

async def cmd_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = "\n".join(step_log[-30:]) if step_log else "لا يوجد سجل"
    await update.message.reply_text(
        f"📋 <b>آخر الخطوات:</b>\n<code>{txt}</code>", parse_mode="HTML"
    )

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global waiting_captcha, selected_cells, bot_running, use_saved_session

    q = update.callback_query
    await q.answer()
    d = q.data

    if d in ("do_start_saved", "do_start_fresh"):
        if bot_running:
            await tg_msg("⚠️ البوت يعمل بالفعل!")
            return
        use_saved_session = (d == "do_start_saved")
        await q.edit_message_text("⏳ جاري التشغيل...")
        asyncio.get_event_loop().create_task(start_lab_automation())

    elif d == "do_shot":
        if page_global:
            img = await safe_screenshot(page_global)
            if img:
                await tg_photo(img, f"📸 [{now_str()}]")
            else:
                await tg_msg("⚠️ فشل")
        else:
            await tg_msg("⚠️ المتصفح غير مشغّل")

    elif d == "do_log":
        txt = "\n".join(step_log[-30:]) if step_log else "لا يوجد سجل"
        await tg_msg(f"📋 <b>الخطوات:</b>\n<code>{txt}</code>")

    elif d == "do_stop":
        bot_running = waiting_captcha = False
        await q.edit_message_text("⛔ تم الإيقاف")

    elif d == "do_clear":
        try:
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
                await tg_msg("🗑️ <b>تم حذف الجلسة</b>")
            else:
                await tg_msg("ℹ️ لا توجد جلسة")
        except Exception as e:
            await tg_msg(f"❌ خطأ: {e}")

    elif d.startswith("cap_"):
        act = d[4:]
        if act == "confirm":
            if not selected_cells:
                await tg_msg("⚠️ لم تختر شيئاً!")
                return
            await q.edit_message_caption(
                f"✅ {sorted(selected_cells)} - جاري...", parse_mode="HTML"
            )
            if page_global:
                asyncio.get_event_loop().create_task(apply_captcha_selection(page_global))
            else:
                await tg_msg("❌ المتصفح انتهى")

        elif act == "refresh":
            if page_global:
                try:
                    cf = page_global.frame_locator('iframe[title*="recaptcha challenge"]')
                    await cf.locator('.rc-imageselect-refresh, #recaptcha-reload-button').click()
                    await asyncio.sleep(2)
                    selected_cells.clear()
                    await _send_captcha_to_user(page_global)
                except Exception as e:
                    await tg_msg(f"❌ {e}")

        elif act == "skip":
            waiting_captcha = False
            await q.edit_message_caption("⏭️ تم التخطي")

        else:
            try:
                n = int(act)
                if n in selected_cells:
                    selected_cells.discard(n)
                else:
                    selected_cells.add(n)
                await q.edit_message_reply_markup(reply_markup=_captcha_kb())
            except ValueError:
                pass


# ══════════════════════════════════════════════════════════
#  نقطة الانطلاق
# ══════════════════════════════════════════════════════════

def main():
    SESSION_DIR.mkdir(exist_ok=True)
    log.info("🤖 بوت v3 يعمل...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("log",        cmd_log))
    app.add_handler(CallbackQueryHandler(handle_callback))
    log.info("✅ جاهز - أرسل /start")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
