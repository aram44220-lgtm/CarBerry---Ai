import asyncio
import logging
import os
import re
import sys
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from html import escape as html_escape

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
import uvicorn

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from openai import AsyncOpenAI

# ─── Website Engine ────────────────────────────────────────────────────────────
try:
    from site_engine.generator import build_html, extract_json, get_system_prompt
    from site_engine.schema import validate_plan
    _SITE_ENGINE_OK = True
except Exception as _se_import_err:
    _SITE_ENGINE_OK = False
    logger_pre = logging.getLogger(__name__)
    logger_pre.warning("site_engine import failed: %s", _se_import_err)
# ───────────────────────────────────────────────────────────────────────────────

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _clean_env(value: str | None, strip_trailing_punct: bool = True) -> str:
    if not value:
        return ""
    v = value.strip()
    # Убираем оборачивающие кавычки: "..." или '...'
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        v = v[1:-1].strip()
    if strip_trailing_punct:
        while v and v[-1] in ",; ":
            v = v[:-1]
    return v.strip()


def required_env(name: str) -> str:
    value = _clean_env(os.getenv(name))
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения {name}. Заполни файл .env.")
    return value


# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = required_env("BOT_TOKEN")
GROQ_API_KEY = required_env("GROQ_API_KEY")
# WEBAPP_URL: публичный домен для Mini App кнопок (Railway, VPS, ngrok и т.д.)
_raw_webapp_url = _clean_env(os.getenv("WEBAPP_URL", "https://carberry-ai-production.up.railway.app"))
WEBAPP_URL = _raw_webapp_url.rstrip("/")  # гарантируем без trailing slash
AI_MODEL = _clean_env(os.getenv("AI_MODEL")) or "llama-3.1-8b-instant"
_RAW_PORT = _clean_env(os.getenv("PORT"))
try:
    PORT = int(_RAW_PORT) if _RAW_PORT else 8000
except ValueError:
    PORT = 8000

MAX_CACHE_SIZE = 500
CACHE_TTL_SECONDS = 7200
RATE_LIMIT_SECONDS = 10
MAX_RATE_USERS = 2000
POLLING_RESTART_DELAY_SECONDS = 5

FALLBACK_MODELS: tuple[str, ...] = (
    AI_MODEL,
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-4-scout-instruct",
    "llama-4-maverick-17b-128e-instruct",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "groq/compound",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "minimaxai/minimax-m2.7",
    "moonshotai/kimi-k2-instruct",
    "groq/compound-mini",
    "moonshotai/kimi-k2-instruct-0905",
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)


def _dedupe_models(models: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in models:
        m_stripped = (m or "").strip()
        if not m_stripped:
            continue
        key = m_stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(m_stripped)
    return out


async def _check_bot_token_once() -> bool:
    try:
        me = await bot.get_me()
        logger.info("Токен бота ОК — подключен как @%s (%s)", me.username, me.first_name)
        try:
            from aiogram.types import BotCommand
            commands = [
                BotCommand(command="start", description="👋 Приветствие и как пользоваться"),
                BotCommand(command="templates", description="🎨 Готовые шаблоны сайтов"),
                BotCommand(command="stats", description="📊 Твоя статистика"),
                BotCommand(command="help", description="❓ Справка и часто задаваемые вопросы"),
            ]
            await bot.set_my_commands(commands)
            logger.info("Команды меню Telegram обновлены (/start /templates /stats /help)")
        except Exception as _ce:
            logger.debug("Не удалось обновить команды меню: %s", _ce)
        return True
    except Exception as e:
        logger.error(
            "Токен бота не работает или нет интернета: %s. "
            "Исправь BOT_TOKEN в .env и перезапусти бота.",
            e,
        )
        return False


async def _polling_loop_forever(stop_event: asyncio.Event):
    retry_delay = POLLING_RESTART_DELAY_SECONDS
    while not stop_event.is_set():
        try:
            logger.info("Запускаю polling Telegram...")
            await dp.start_polling(bot, handle_signals=False)
            retry_delay = POLLING_RESTART_DELAY_SECONDS  # сброс после успешной сессии
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            logger.info("Polling остановлен по запросу shutdown.")
            break
        except Exception as e:
            err_name = type(e).__name__
            err_text = str(e).lower()
            _is_network = any(k in err_text for k in (
                "server disconnected", "serverdisconnected", "network",
                "timeout", "connection", "conflict", "terminated by other",
                "getupdate", "aiohttp", "clienterror",
            )) or "TelegramNetworkError" in err_name or "ServerDisconnected" in err_name
            if _is_network:
                logger.warning(
                    "Сетевая ошибка polling (%s): %s — переподключение через %ss...",
                    err_name, str(e)[:100], retry_delay,
                )
            else:
                logger.exception("Polling упал с неожиданной ошибкой: %s", e)
        if stop_event.is_set():
            break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
        except asyncio.TimeoutError:
            pass


class TTLCache:
    def __init__(self, max_size: int, ttl: int):
        self._data: "OrderedDict[str, tuple[str, float]]" = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def _cleanup(self):
        now = time.time()
        expired = [k for k, (_, ts) in self._data.items() if now - ts > self._ttl]
        for k in expired:
            del self._data[k]
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def get(self, key: str):
        self._cleanup()
        item = self._data.get(key)
        if item is None:
            return None
        value, ts = item
        if time.time() - ts > self._ttl:
            del self._data[key]
            return None
        return value

    def put(self, key: str, value: str):
        self._cleanup()
        self._data[key] = (value, time.time())

    def __len__(self):
        self._cleanup()
        return len(self._data)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def keys_snapshot(self) -> list[str]:
        """Возвращает актуальные (не истёкшие) ключи."""
        self._cleanup()
        return list(self._data.keys())


GENERATED_APPS = TTLCache(max_size=MAX_CACHE_SIZE, ttl=CACHE_TTL_SECONDS)
PERMANENT_READY_APPS: "dict[str, str]" = {}
USER_LAST_REQUEST: dict[int, float] = {}
# Stores the site plan (dict) per app_id so the user can request edits
SITE_PLANS: dict[str, dict] = {}
# Tracks last generated site app_id per user_id
USER_LAST_SITE: dict[int, str] = {}
# PUBLIC_URL задаётся сразу из env — ngrok больше не нужен
PUBLIC_URL = WEBAPP_URL


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%d.%m.%Y %H:%M")


USER_STATS: dict[int, dict] = {}


def _ensure_user_stats(user_id: int, username: str | None = None, first_name: str | None = None) -> dict:
    s = USER_STATS.get(user_id)
    if s is None:
        s = {
            "username": username or "",
            "first_name": first_name or "",
            "first_seen": _now_iso(),
            "last_seen": _now_iso(),
            "total_requests": 0,
            "successful_apps": 0,
            "failed_requests": 0,
            "used_models": {},
        }
        USER_STATS[user_id] = s
    else:
        if username:
            s["username"] = username
        if first_name:
            s["first_name"] = first_name
        s["last_seen"] = _now_iso()
    return s


def _stat_inc_request(user_id: int, username: str | None, first_name: str | None):
    s = _ensure_user_stats(user_id, username, first_name)
    s["total_requests"] += 1


def _stat_inc_success(user_id: int, model: str | None = None):
    s = _ensure_user_stats(user_id)
    s["successful_apps"] += 1
    if model:
        key = model.strip() or "unknown"
        s["used_models"][key] = s["used_models"].get(key, 0) + 1


def _stat_inc_fail(user_id: int):
    s = _ensure_user_stats(user_id)
    s["failed_requests"] += 1


def _stat_rate(s: dict) -> str:
    total = s["successful_apps"] + s["failed_requests"]
    if total == 0:
        return "0%"
    return f"{round(100 * s['successful_apps'] / total)}%"


# ================= FASTAPI (ВЕБ-СЕРВЕР) =================


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    logger.info("🌍 Публичный URL (Mini App): %s", PUBLIC_URL)

    await _check_bot_token_once()

    polling_task = asyncio.create_task(_polling_loop_forever(stop_event))

    async def _bg_diag():
        try:
            await _diagnose_all_models_on_startup()
        except Exception as _diag_e:
            print("⚠️  Предстартовая диагностика упала с ошибкой (не смертельно):", _diag_e)

    _bg_diag_task = asyncio.create_task(_bg_diag())

    async def _bg_cache_cleanup():
        """Фоновая задача: каждые 30 минут принудительно чистит истёкшие записи из GENERATED_APPS."""
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1800)  # 30 минут
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break
            try:
                before = len(GENERATED_APPS._data)
                GENERATED_APPS._cleanup()
                after = len(GENERATED_APPS._data)
                removed = before - after
                if removed > 0:
                    logger.info("[Cache GC] Удалено %d истёкших записей из GENERATED_APPS (осталось %d)", removed, after)
            except Exception as _gc_e:
                logger.debug("[Cache GC] Ошибка при очистке кэша: %s", _gc_e)

    _bg_cleanup_task = asyncio.create_task(_bg_cache_cleanup())

    try:
        yield
    finally:
        stop_event.set()
        _bg_diag_task.cancel()
        _bg_cleanup_task.cancel()
        polling_task.cancel()
        try:
            await _bg_diag_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await _bg_cleanup_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await polling_task
        except (asyncio.CancelledError, Exception):
            logger.debug("Polling loop завершён")
        # ngrok не используется — ничего не убиваем
        try:
            await bot.session.close()
        except Exception:
            pass


_READY_TEMPLATES_IDS = None


def _get_ready_ids() -> set[str]:
    global _READY_TEMPLATES_IDS
    if _READY_TEMPLATES_IDS is None:
        _READY_TEMPLATES_IDS = set(READY_APP_TEMPLATES.keys())
    return _READY_TEMPLATES_IDS


def _resolve_ready_template_id(raw_app_id: str) -> str | None:
    if not raw_app_id:
        return None
    a = raw_app_id.strip().lower()
    if not a:
        return None
    ids = _get_ready_ids()
    if a in ids:
        return a
    for prefix in ("ready__", "ready_", "app_", "tpl_", "template_", "go_"):
        if a.startswith(prefix):
            tail = a[len(prefix):]
            if tail in ids:
                return tail
            m = tail
            for sep in ("_", "-", "__"):
                if sep in m:
                    first = m.split(sep)[0]
                    if first in ids:
                        return first
            if tail:
                for known in ids:
                    if tail.startswith(known):
                        return known
    for known in ids:
        if a == known or known in a or a in known:
            return known
    return None


def _resolve_app_html(app_id: str) -> tuple[str | None, str | None]:
    if not app_id:
        return None, None
    tpl = _resolve_ready_template_id(app_id)
    if tpl:
        html_code = PERMANENT_READY_APPS.get(tpl)
        if not html_code:
            t = READY_APP_TEMPLATES.get(tpl)
            if t:
                _, html_code = t
                PERMANENT_READY_APPS[tpl] = html_code
                try:
                    GENERATED_APPS.put(f"ready__{tpl}", html_code)
                    GENERATED_APPS.put(f"ready_{tpl}", html_code)
                    GENERATED_APPS.put(tpl, html_code)
                except Exception:
                    pass
        if html_code:
            return tpl, html_code
    if app_id in GENERATED_APPS:
        return None, GENERATED_APPS.get(app_id)
    if len(app_id) >= 6:
        return None, None
    return None, None


def _build_not_found_page(app_id: str, suggestion: str | None = None) -> str:
    quick_links_html = ""
    done = 0
    for tid, (title, _html) in READY_APP_TEMPLATES.items():
        if done >= 6:
            break
        quick_links_html += f'<a href="/app/{tid}?ngrok-skip-browser-warning=1" class="py-3 rounded-xl bg-slate-100 dark:bg-slate-700 text-sm font-bold hover:bg-indigo-500 hover:text-white transition shadow-sm">{title.split()[0]} {title.split()[1] if len(title.split())>1 else ""}</a>'
        done += 1
    if suggestion:
        sug_html = f'<div class="mb-6 p-4 rounded-2xl bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-200 dark:border-indigo-700/50"><div class="text-indigo-900 dark:text-indigo-100 text-sm mb-2">💡 Возможно, ты имел в виду:</div><a href="/app/{suggestion}?ngrok-skip-browser-warning=1" class="inline-block px-4 py-2 rounded-xl bg-indigo-600 text-white font-black">/app/{suggestion}</a></div>'
    else:
        sug_html = ""
    raw_id = _safe_html(app_id) if app_id else ""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no" />
<meta name="theme-color" content="#dc2626">
<title>404 · Страница не найдена</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>try{{if(window.Telegram&&Telegram.WebApp){{const t=Telegram.WebApp;t.ready();t.expand();try{{t.setHeaderColor('#dc2626')}}catch(e){{}};if(t.BackButton)t.BackButton.hide();try{{t.MainButton.hide()}}catch(e){{}};}}}}catch(e){{}}</script>
</head>
<body class="min-h-screen bg-gradient-to-br from-rose-50 via-white to-orange-50 dark:from-slate-950 dark:via-slate-900 dark:to-rose-950 flex items-center justify-center p-6">
  <div class="max-w-lg w-full bg-white dark:bg-slate-800 rounded-3xl shadow-2xl p-8 text-center border border-slate-200 dark:border-slate-700">
    <div class="text-7xl mb-4 animate-bounce">😕</div>
    <h1 class="text-3xl font-black text-slate-900 dark:text-white mb-2">Страница не найдена</h1>
    <p class="text-slate-500 dark:text-slate-400 mb-6">URL <code class="px-2 py-1 rounded-lg bg-slate-100 dark:bg-slate-700 text-sm font-mono break-all">{raw_id}</code> не существует, либо кэш приложения истёк (он живёт 2 часа).</p>
    {sug_html}
    <div class="text-xs uppercase font-black tracking-widest text-slate-400 mb-3">Выбери готовое приложение:</div>
    <div class="grid grid-cols-2 gap-2">
      {quick_links_html}
    </div>
    <div class="mt-8 text-sm text-slate-400">
      <i class="fa-brands fa-telegram text-sky-500"></i> Вернись в бот → <b>/start</b> → выбери шаблон
    </div>
  </div>
</body>
</html>"""


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,        # Disable /docs in production
    redoc_url=None,       # Disable /redoc in production
    openapi_url=None,     # Disable /openapi.json in production
)


@app.middleware("http")
async def global_headers_and_request_logging(request: Request, call_next):
    try:
        if request.method == "GET":
            path = request.url.path
            fixed = path.replace("//", "/")
            if fixed != path and fixed:
                qs = request.url.query
                return RedirectResponse(url=fixed + ("?" + qs if qs else ""), status_code=307)
            if len(path) > 1 and path.endswith("/"):
                qs = request.url.query
                return RedirectResponse(url=path[:-1] + ("?" + qs if qs else ""), status_code=307)
        t0 = time.time()
        response = await call_next(request)
    except Exception as _err:
        response = Response(content=_build_not_found_page(""), media_type="text/html; charset=utf-8", status_code=500)
    response.headers["ngrok-skip-browser-warning"] = "69420"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if "ngrok-skip-browser-warning" in request.query_params and "ngrok-skip-browser-warning" not in request.cookies:
        try:
            from fastapi import Response as _R
            response.set_cookie("ngrok-skip-browser-warning", "69420", max_age=31536000, httponly=False, samesite="lax")
        except Exception:
            pass
    return response


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    raw = request.url.path
    suggestion = None
    for chunk in raw.split("/"):
        c = chunk.strip()
        if c:
            r = _resolve_ready_template_id(c)
            if r:
                suggestion = r
                break
    if not suggestion and len(raw.split("/")) >= 2:
        last = raw.strip("/").split("/")[-1]
        r = _resolve_ready_template_id(last)
        if r:
            suggestion = r
    content = _build_not_found_page(raw or "/", suggestion)
    headers = {"Content-Type": "text/html; charset=utf-8", "ngrok-skip-browser-warning": "69420"}
    return Response(content=content, status_code=404, headers=headers)


@app.exception_handler(405)
@app.exception_handler(500)
async def other_http_handler(request: Request, exc):
    code = getattr(exc, "status_code", 500)
    content = _build_not_found_page(request.url.path or "/")
    return Response(content=content, status_code=code, headers={"Content-Type": "text/html; charset=utf-8", "ngrok-skip-browser-warning": "69420"})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc):
    content = _build_not_found_page(request.url.path or "/")
    return Response(content=content, status_code=404, headers={"Content-Type": "text/html; charset=utf-8", "ngrok-skip-browser-warning": "69420"})


@app.get("/robots.txt", response_class=Response)
async def robots_txt():
    return Response(content="User-agent: *\nDisallow: /\n", media_type="text/plain")


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request) -> HTMLResponse:
    tpl_rows = ""
    for tpl_id, (title, _html) in READY_APP_TEMPLATES.items():
        preview_url = f"/app/{tpl_id}?ngrok-skip-browser-warning=1"
        emoji = title.split()[0] if title and title.split() else "📱"
        name_rest = " ".join(title.split()[1:]) if len(title.split()) > 1 else ""
        tpl_rows += f"""
            <a href="{preview_url}" class="group block p-5 rounded-3xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-indigo-400 hover:shadow-2xl transition-all">
              <div class="flex items-center gap-4">
                <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 text-white text-2xl flex items-center justify-center shadow-lg group-hover:scale-110 transition">
                  {emoji}
                </div>
                <div class="flex-1 min-w-0">
                  <div class="font-black text-lg text-slate-900 dark:text-white truncate">{emoji} {name_rest}</div>
                  <div class="text-sm text-slate-500 dark:text-slate-400 truncate">/app/{tpl_id}</div>
                </div>
                <div class="text-slate-400 group-hover:text-indigo-500 group-hover:translate-x-1 transition">
                  <i class="fa-solid fa-chevron-right"></i>
                </div>
              </div>
            </a>
        """
    pub_url = PUBLIC_URL or ""
    body = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no" />
<meta name="theme-color" content="#6366f1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>CarBerry — Mini App Gateway</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>tailwind.config = {{ darkMode: 'class' }};</script>
<script>try{{if(window.Telegram&&Telegram.WebApp){{const t=Telegram.WebApp;t.ready();t.expand();try{{t.setHeaderColor('#6366f1');t.setBackgroundColor('#0f172a');}}catch(e){{}};if(t.BackButton)t.BackButton.hide();try{{t.MainButton.hide()}}catch(e){{}};}}}}catch(e){{}}</script>
</head>
<body class="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-purple-50 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950 text-slate-800 dark:text-white">
<div class="max-w-3xl mx-auto px-5 py-10">
  <div class="flex items-center justify-between mb-8">
    <div>
      <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-sm font-black mb-3 border border-emerald-500/20">
        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
        CarBerry Gateway — ONLINE
      </div>
      <h1 class="text-4xl sm:text-5xl font-black leading-tight">
        <span class="bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 bg-clip-text text-transparent">Mini Apps</span>
        <br/>готовы к запуску 🚀
      </h1>
      <p class="text-slate-500 dark:text-slate-400 mt-3 text-lg">Telegram WebView · HTTPS Tunnnel · Кэш 2 часа + вечные готовые шаблоны</p>
    </div>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">
    <div class="p-5 rounded-3xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
      <div class="text-xs font-black uppercase tracking-widest text-slate-400">Кэш приложений</div>
      <div class="mt-2 text-4xl font-black bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">{len(GENERATED_APPS)}</div>
      <div class="mt-1 text-sm text-slate-500 dark:text-slate-400">загружено сейчас</div>
    </div>
    <div class="p-5 rounded-3xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
      <div class="text-xs font-black uppercase tracking-widest text-slate-400">Готовые шаблоны</div>
      <div class="mt-2 text-4xl font-black bg-gradient-to-r from-fuchsia-600 to-pink-600 bg-clip-text text-transparent">{len(READY_APP_TEMPLATES)}</div>
      <div class="mt-1 text-sm text-slate-500 dark:text-slate-400">мгновенный запуск</div>
    </div>
    <div class="p-5 rounded-3xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
      <div class="text-xs font-black uppercase tracking-widest text-slate-400">Порт / Прокси</div>
      <div class="mt-2 text-4xl font-black bg-gradient-to-r from-emerald-600 to-teal-600 bg-clip-text text-transparent">{PORT}</div>
      <div class="mt-1 text-sm text-slate-500 dark:text-slate-400 truncate">{"не запущен" if not pub_url else "HTTPS ✓"}</div>
    </div>
  </div>

  <h2 class="text-2xl font-black mb-5 text-slate-900 dark:text-white flex items-center gap-3">
    <i class="fa-solid fa-bolt text-yellow-500"></i> Открыть готовое приложение
  </h2>
  <div class="space-y-3">
    {tpl_rows}
  </div>

  <div class="mt-12 p-6 rounded-3xl border-2 border-dashed border-slate-300 dark:border-slate-700 text-center">
    <div class="text-5xl mb-3">🤖</div>
    <div class="text-xl font-black text-slate-900 dark:text-white">Хочешь своё приложение?</div>
    <div class="text-slate-500 dark:text-slate-400 mt-1">Напиши любую идею боту в Telegram — он сгенерирует готовый сайт за ~20 сек.</div>
  </div>
</div>
</body>
</html>"""
    return HTMLResponse(body)


@app.get("/health")
async def health_endpoint(request: Request) -> dict:
    # Minimal response — no internal info exposed
    return {"ok": True}


def _deliver_html_response(request: Request, html_code: str, status_code: int = 200, immutable: bool = False) -> Response:
    cc = "public, max-age=31536000, stale-while-revalidate=31536000, immutable" if immutable else "public, max-age=3600, stale-while-revalidate=7200"
    accept = request.headers.get("accept", "")
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": cc,
        "Content-Security-Policy": (
            "default-src 'self' https: 'unsafe-inline' 'unsafe-eval' data: blob:; "
            "img-src * data: blob:; "
            "connect-src *; "
            "style-src 'self' https: 'unsafe-inline'; "
            "script-src 'self' https: 'unsafe-inline' 'unsafe-eval' https://telegram.org https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
            "frame-ancestors 'self' https://t.me https://web.telegram.org https://*.t.me; "
            "base-uri 'none'; "
            "form-action 'self';"
        ),
        "X-Frame-Options": "ALLOWALL",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "Cross-Origin-Embedder-Policy": "unsafe-none",
        "ngrok-skip-browser-warning": "69420",
        "Permissions-Policy": "geolocation=*, microphone=(), camera=(), fullscreen=*",
    }
    try:
        from fastapi import Response as _Rtmp
    except Exception:
        pass
    return Response(content=html_code, status_code=status_code, headers=headers)


@app.get("/app/{tpl_id}")
async def simple_app_endpoint(request: Request, tpl_id: str) -> Response:
    tpl_resolved, html_code = _resolve_app_html(tpl_id)
    if not html_code:
        sug = _resolve_ready_template_id(tpl_id)
        return Response(content=_build_not_found_page(tpl_id, sug), status_code=404, headers={"Content-Type": "text/html; charset=utf-8", "ngrok-skip-browser-warning": "69420"})
    # /app is for built-in templates — these are truly immutable
    return _deliver_html_response(request, html_code, immutable=True)


@app.get("/app/{tpl_id}/{tail:path}")
async def simple_app_endpoint_with_tail(request: Request, tpl_id: str, tail: str = "") -> Response:
    return RedirectResponse(url=f"/app/{tpl_id}" + ("?" + request.url.query if request.url.query else ""), status_code=307)


@app.get("/preview/{app_id}")
async def get_preview(request: Request, app_id: str) -> Response:
    _SKIP_HDR = {
        "Content-Type": "text/html; charset=utf-8",
        "ngrok-skip-browser-warning": "69420",
        "Cache-Control": "no-store",
    }
    try:
        tpl_resolved, html_code = _resolve_app_html(app_id)
    except Exception:
        html_code = None
        tpl_resolved = None
    if not html_code:
        sug = _resolve_ready_template_id(app_id)
        if sug:
            qs = request.url.query
            url = f"/app/{sug}" + ("?" + qs if qs else "")
            return RedirectResponse(url=url, status_code=307)
        # Красивая страница «ссылка истекла» вместо 500/пустого экрана
        expired_page = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f59e0b">
<title>Ссылка истекла</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<script>try{if(window.Telegram&&Telegram.WebApp){const t=Telegram.WebApp;t.ready();t.expand();try{t.setHeaderColor('#f59e0b');}catch(e){}}}catch(e){}</script>
</head>
<body class="min-h-screen bg-gradient-to-br from-amber-50 via-white to-orange-50 flex items-center justify-center p-6">
  <div class="max-w-md w-full bg-white rounded-3xl shadow-2xl p-8 text-center border border-amber-100">
    <div class="text-7xl mb-5">⏳</div>
    <h1 class="text-2xl font-black text-slate-900 mb-3">Ссылка истекла</h1>
    <p class="text-slate-500 mb-6">Это приложение было автоматически удалено через <b class="text-amber-600">2 часа</b> после создания.<br><br>Сгенерируй его снова — напиши боту тот же запрос.</p>
    <div class="text-xs text-slate-400 mt-4">ID: <code class="bg-slate-100 px-2 py-1 rounded">{app_id}</code></div>
  </div>
</body>
</html>""".format(app_id=app_id[:16])
        return Response(content=expired_page, status_code=404, headers=_SKIP_HDR)
    immutable = bool(tpl_resolved)
    try:
        return _deliver_html_response(request, html_code, immutable=immutable)
    except Exception as _preview_err:
        logger.exception("Ошибка при отдаче preview %s: %s", app_id, _preview_err)
        return Response(
            content="<h1>Ошибка сервера</h1><p>Попробуй снова.</p>",
            status_code=500,
            headers=_SKIP_HDR,
        )


# ================= TELEGRAM BOT =================
# ================= КОМАНДЫ БОТА =================
TEMPLATE_CATEGORIES: "OrderedDict[str, list[tuple[str, str]]]" = OrderedDict([
    (
        "🌐 Лендинги и сайты",
        [
            ("Сайт-лендинг для стартапа", "Создай современный лендинг для SaaS стартапа AI-инструмента с hero-секцией, фичами, тарифами и CTA-кнопками. Тёмная тема, плавные анимации."),
            ("Портфолио дизайнера", "Одностраничный сайт-портфолио для креативного дизайнера: работы, о себе, навыки, контакты. Стильный минимализм."),
            ("Сайт ресторана/кафе", "Сайт для современного ресторана: меню, о нас, галерея блюд, бронь столика, контакты. Тёплые цвета."),
            ("Интернет-магазин", "Главная страница интернет-магазина одежды: категории, товары с ценниками, акции, корзина. Светлая тема."),
            ("Новостной блог", "Главная страница новостного блога: посты, категории, теги, популярное, подписка на рассылку."),
            ("Сайт фитнес-зала", "Лендинг фитнес клуба: абонементы, тренеры, расписание, фото зала, CTA записаться."),
        ],
    ),
    (
        "🛠️ Веб-приложения и утилиты",
        [
            ("Список задач (Todo App)", "Полнофункциональный Todo List: добавление, удаление, отметка выполненных, фильтры, темы. Modern UI."),
            ("Калькулятор ИМТ", "Калькулятор индекса массы тела с вводом роста/веса, красивой визуализацией результата и советами."),
            ("Трекер привычек", "Трекер ежедневных привычек: добавить привычку, отметить день, статистика выполнения за месяц."),
            ("Конвертер валют", "Конвертер валют в реальном времени с красивым UI, выбор валют, история конвертаций."),
            ("Генератор паролей", "Генератор безопасных паролей: настройка длины, символов, цифр, копирование в буфер."),
            ("Таймер Помодоро", "Таймер Помодоро 25/5 минут: задачи, звуковой сигнал, статистика фокусировки."),
        ],
    ),
    (
        "🎮 Игры и развлечения",
        [
            ("Крестики-нолики", "Игра крестики-нолики с красивым дизайном, анимациями и счётом побед."),
            ("Змейка", "Классическая игра змейка на Canvas: управление стрелками, очки, рекорд, уровни сложности."),
            ("Memory карточки", "Игра Memory: переворачивай карточки и найди пары. Счёт, таймер, разные темы."),
            ("Викторина", "Викторина с вопросами на разные темы, счёт, прогресс-бар, красивые анимации."),
            ("Камень-ножницы-бумага", "Игра камень-ножницы-бумага против компьютера: анимации, счёт, статистика."),
        ],
    ),
    (
        "🤖 ИИ и автоматизация",
        [
            ("AI Chat интерфейс", "Интерфейс чата с ИИ-ассистентом: сообщения, отправка, индикатор печати, тёмная тема."),
            ("Генератор идей стартапов", "Генератор идей стартапов: ввод индустрии, случайная идея, список шагов реализации."),
            ("Анализатор текста", "Инструмент анализа текста: подсчёт символов/слов, частотность слов, тональность."),
            ("Генератор цитат", "Генератор мотивационных цитат: красивая карточка, кнопка сохранить/скопировать."),
        ],
    ),
    (
        "💼 Бизнес и документы",
        [
            ("Интерфейс CRM", "Дашборд CRM: лиды, сделки, статистика по месяцам, диаграммы, таблица клиентов."),
            ("Счёт на оплату (Invoice)", "Шаблон красивого счёта на оплату: услуги, суммы, логотип, кнопка оплатить."),
            ("Календарь встреч", "Календарь планирования встреч: добавить событие, напоминание, список дел на день."),
            ("Дашборд аналитики", "Аналитический дашборд: графики доходов, KPI-показатели, топ клиенты, таблицы."),
        ],
    ),
])

READY_APP_TEMPLATES: "OrderedDict[str, tuple[str, str]]" = OrderedDict([
    ("todo", ("📝 To-Do лист", """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#6366f1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>To-Do List</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>
try {
  if (window.Telegram && Telegram.WebApp) {
    const tg = Telegram.WebApp;
    tg.ready(); tg.expand();
    try { tg.setHeaderColor('#6366f1'); tg.setBackgroundColor('#0f172a'); } catch(e){}
    if (tg.HapticFeedback) { window.__tgHaptic = tg.HapticFeedback; }
    if (tg.BackButton) { tg.BackButton.hide(); }
    try { tg.MainButton.hide(); } catch(e){}
    window.__tg = tg;
    document.documentElement.style.setProperty('--tg-safe-top', (tg.safeAreaInsetTop||0)+'px');
    document.documentElement.style.setProperty('--tg-safe-bot', (tg.safeAreaInsetBottom||0)+'px');
  }
} catch(e){}
function haptic(kind='light'){ try { const h = window.__tgHaptic || (window.__tg && __tg.HapticFeedback); if(!h) return; if(kind==='success') h.notificationOccurred('success'); else if(kind==='error') h.notificationOccurred('error'); else if(kind==='warn') h.notificationOccurred('warning'); else if(kind==='select') h.selectionChanged(); else h.impactOccurred(kind); } catch(e){} }
</script>
<script>
tailwind.config = { darkMode: 'class', theme: { extend: {
  colors: { brand: '#6366f1', brandDark: '#4f46e5' },
  animation: { 'fade-in': 'fadeIn .3s ease', 'slide-in': 'slideIn .3s ease' }
}} } };
</script>
<style>
@keyframes fadeIn { from {opacity:0} to {opacity:1} }
@keyframes slideIn { from {opacity:0; transform: translateY(8px)} to {opacity:1; transform:translateY(0)} }
body { -webkit-tap-highlight-color: transparent; }
.checkbox-custom:checked + label .check { background: linear-gradient(135deg, #6366f1, #8b5cf6); }
</style>
</head>
<body class="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-purple-50 dark:from-slate-900 dark:via-slate-800 dark:to-indigo-950 text-slate-800 dark:text-slate-100 transition-colors duration-300">
<div class="max-w-xl mx-auto px-4 py-6 pb-24">
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-3xl font-black bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">Мои задачи</h1>
      <p class="text-sm text-slate-500 dark:text-slate-400 mt-1" id="todayDate"></p>
    </div>
    <button onclick="toggleTheme()" class="w-11 h-11 rounded-2xl bg-white dark:bg-slate-800 shadow-lg border border-slate-200 dark:border-slate-700 flex items-center justify-center active:scale-95 transition"><i id="themeIcon" class="fa-solid fa-moon text-indigo-500"></i></button>
  </div>

  <div class="bg-white dark:bg-slate-800 rounded-3xl p-4 shadow-xl border border-slate-100 dark:border-slate-700 mb-6">
    <div class="flex gap-2">
      <input id="newTask" type="text" placeholder="Добавь задачу..." class="flex-1 px-4 py-3 rounded-2xl bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 dark:focus:ring-indigo-900 transition" onkeypress="if(event.key==='Enter')addTask()">
      <button onclick="addTask()" class="px-5 py-3 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white font-bold shadow-lg shadow-indigo-500/30 active:scale-95 transition"><i class="fa-solid fa-plus"></i></button>
    </div>
    <div class="flex gap-2 mt-3 flex-wrap">
      <button onclick="setFilter('all')" data-filter="all" class="filter-btn px-4 py-1.5 rounded-xl text-sm font-semibold transition">Все</button>
      <button onclick="setFilter('active')" data-filter="active" class="filter-btn px-4 py-1.5 rounded-xl text-sm font-semibold transition">Активные</button>
      <button onclick="setFilter('done')" data-filter="done" class="filter-btn px-4 py-1.5 rounded-xl text-sm font-semibold transition">Выполнено</button>
    </div>
  </div>

  <div class="grid grid-cols-3 gap-3 mb-6">
    <div class="bg-white dark:bg-slate-800 p-4 rounded-2xl shadow-md border border-slate-100 dark:border-slate-700 text-center"><div class="text-2xl font-black text-indigo-600 dark:text-indigo-400" id="statTotal">0</div><div class="text-xs text-slate-500 dark:text-slate-400 mt-1">Всего</div></div>
    <div class="bg-white dark:bg-slate-800 p-4 rounded-2xl shadow-md border border-slate-100 dark:border-slate-700 text-center"><div class="text-2xl font-black text-amber-500" id="statActive">0</div><div class="text-xs text-slate-500 dark:text-slate-400 mt-1">Осталось</div></div>
    <div class="bg-white dark:bg-slate-800 p-4 rounded-2xl shadow-md border border-slate-100 dark:border-slate-700 text-center"><div class="text-2xl font-black text-emerald-500" id="statDone">0</div><div class="text-xs text-slate-500 dark:text-slate-400 mt-1">Готово</div></div>
  </div>

  <div id="taskList" class="space-y-2"></div>
  <div id="emptyState" class="hidden text-center py-16">
    <div class="text-6xl mb-4 opacity-30">📝</div>
    <p class="text-slate-500 dark:text-slate-400 text-lg font-semibold">Пока нет задач</p>
    <p class="text-sm text-slate-400 dark:text-slate-500 mt-1">Добавь первую задачу выше ✨</p>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let tasks = JSON.parse(localStorage.getItem('todo_tasks') || '[]');
let filter = 'all';
const months = ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
const d = new Date();
$('#todayDate').textContent = `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;

function save(){ localStorage.setItem('todo_tasks', JSON.stringify(tasks)); }
function toggleTheme(){
  document.documentElement.classList.toggle('dark');
  localStorage.setItem('todo_theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  $('#themeIcon').className = document.documentElement.classList.contains('dark') ? 'fa-solid fa-sun text-amber-400' : 'fa-solid fa-moon text-indigo-500';
}
if(localStorage.getItem('todo_theme') === 'dark') { document.documentElement.classList.add('dark'); $('#themeIcon').className='fa-solid fa-sun text-amber-400'; }

function addTask(){
  const v = $('#newTask').value.trim();
  if(!v) return;
  tasks.unshift({id:Date.now(), text:v, done:false, createdAt:Date.now()});
  $('#newTask').value='';
  save(); render();
}
function toggleTask(id){ tasks = tasks.map(t => t.id===id ? {...t, done:!t.done} : t); save(); render(); }
function delTask(id){ tasks = tasks.filter(t => t.id!==id); save(); render(); }
function clearDone(){ tasks = tasks.filter(t => !t.done); save(); render(); }
function setFilter(f){ filter=f; document.querySelectorAll('.filter-btn').forEach(b=>{
  const active = b.dataset.filter === f;
  b.className = 'filter-btn px-4 py-1.5 rounded-xl text-sm font-semibold transition ' + (active ? 'bg-indigo-500 text-white shadow-md' : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300');
}); render(); }
setFilter('all');

function render(){
  const list = $('#taskList');
  const filtered = tasks.filter(t => filter==='all' ? true : filter==='done' ? t.done : !t.done);
  $('#statTotal').textContent = tasks.length;
  $('#statActive').textContent = tasks.filter(t=>!t.done).length;
  $('#statDone').textContent = tasks.filter(t=>t.done).length;
  $('#emptyState').classList.toggle('hidden', filtered.length>0);
  list.innerHTML = filtered.map(t => `
    <div class="group animate-slide-in bg-white dark:bg-slate-800 rounded-2xl p-4 shadow-md border border-slate-100 dark:border-slate-700 flex items-center gap-3 hover:shadow-lg transition">
      <div class="relative w-7 h-7 flex-shrink-0">
        <input id="cb${t.id}" type="checkbox" class="checkbox-custom sr-only" ${t.done?'checked':''} onchange="toggleTask(${t.id})">
        <label for="cb${t.id}" class="block w-7 h-7 rounded-xl border-2 ${t.done?'border-transparent':'border-slate-300 dark:border-slate-600 bg-transparent'} flex items-center justify-center cursor-pointer transition check ${t.done?'bg-gradient-to-br from-indigo-500 to-purple-600':''}">
          ${t.done?'<i class="fa-solid fa-check text-white text-xs"></i>':''}
        </label>
      </div>
      <div class="flex-1 min-w-0">
        <div class="font-semibold ${t.done?'line-through text-slate-400 dark:text-slate-500':'text-slate-800 dark:text-slate-200'} break-words">${escapeHtml(t.text)}</div>
      </div>
      <button onclick="delTask(${t.id})" class="w-9 h-9 rounded-xl text-slate-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-500 flex items-center justify-center active:scale-90 transition"><i class="fa-solid fa-trash text-sm"></i></button>
    </div>`).join('');
  if(tasks.some(t=>t.done)){
    list.innerHTML += `<button onclick="clearDone()" class="w-full mt-4 py-3 rounded-2xl text-sm font-semibold text-red-500 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 active:scale-99 transition">🗑 Очистить выполненные</button>`;
  }
}
function escapeHtml(s){ return s.replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
render();
</script>
</body>
</html>""")),

    ("calc", ("🧮 Калькулятор", """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#0b1120">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Калькулятор</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>
try { if (window.Telegram && Telegram.WebApp) { const tg = Telegram.WebApp; tg.ready(); tg.expand(); try{ tg.setHeaderColor('#0b1120'); tg.setBackgroundColor('#020617');}catch(e){} if(tg.HapticFeedback) window.__tgHaptic=tg.HapticFeedback; if(tg.BackButton) tg.BackButton.hide(); try{tg.MainButton.hide();}catch(e){} window.__tg=tg; } } catch(e){}
function haptic(kind='light'){ try{ const h=window.__tgHaptic||(window.__tg&&__tg.HapticFeedback); if(!h) return; if(kind==='success')h.notificationOccurred('success'); else if(kind==='select')h.selectionChanged(); else h.impactOccurred(kind); }catch(e){} }
</script>
<script>
tailwind.config = { darkMode: 'class', theme: { extend: { animation: { 'pop': 'pop .15s ease' } } } };
</script>
<style>
@keyframes pop { 0%{transform:scale(1)} 50%{transform:scale(.94)} 100%{transform:scale(1)} }
.btn-press:active { animation: pop .15s ease; }
body { -webkit-tap-highlight-color: transparent; user-select:none; }
</style>
</head>
<body class="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
<div class="max-w-md mx-auto px-4 py-6 min-h-screen flex flex-col">
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-black"><i class="fa-solid fa-calculator mr-2 text-cyan-400"></i>Калькулятор</h1>
    <button onclick="toggleTheme()" id="themeBtn" class="w-10 h-10 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center"><i class="fa-solid fa-sun text-amber-400"></i></button>
  </div>

  <div class="bg-slate-800/60 backdrop-blur rounded-3xl p-6 mb-5 border border-slate-700 shadow-2xl">
    <div id="history" class="text-right text-slate-400 text-lg min-h-[28px] font-mono break-all"></div>
    <div id="display" class="text-right text-5xl font-black mt-2 break-all font-mono">0</div>
  </div>

  <div class="grid grid-cols-4 gap-3 flex-1">
    <button onclick="pushBtn('clear')" class="btn-press h-16 rounded-2xl bg-rose-500/20 text-rose-400 text-xl font-bold border border-rose-500/30 hover:bg-rose-500/30">AC</button>
    <button onclick="pushBtn('back')" class="btn-press h-16 rounded-2xl bg-slate-700/60 text-slate-300 text-xl font-bold hover:bg-slate-700"><i class="fa-solid fa-delete-left"></i></button>
    <button onclick="pushBtn('%')" class="btn-press h-16 rounded-2xl bg-slate-700/60 text-cyan-400 text-xl font-bold hover:bg-slate-700">%</button>
    <button onclick="pushBtn('/')" class="btn-press h-16 rounded-2xl bg-cyan-500/20 text-cyan-400 text-2xl font-bold border border-cyan-500/30 hover:bg-cyan-500/30">÷</button>

    <button onclick="pushBtn('7')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">7</button>
    <button onclick="pushBtn('8')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">8</button>
    <button onclick="pushBtn('9')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">9</button>
    <button onclick="pushBtn('*')" class="btn-press h-16 rounded-2xl bg-cyan-500/20 text-cyan-400 text-2xl font-bold border border-cyan-500/30 hover:bg-cyan-500/30">×</button>

    <button onclick="pushBtn('4')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">4</button>
    <button onclick="pushBtn('5')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">5</button>
    <button onclick="pushBtn('6')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">6</button>
    <button onclick="pushBtn('-')" class="btn-press h-16 rounded-2xl bg-cyan-500/20 text-cyan-400 text-2xl font-bold border border-cyan-500/30 hover:bg-cyan-500/30">−</button>

    <button onclick="pushBtn('1')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">1</button>
    <button onclick="pushBtn('2')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">2</button>
    <button onclick="pushBtn('3')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">3</button>
    <button onclick="pushBtn('+')" class="btn-press h-16 rounded-2xl bg-cyan-500/20 text-cyan-400 text-2xl font-bold border border-cyan-500/30 hover:bg-cyan-500/30">+</button>

    <button onclick="pushBtn('sci')" class="btn-press h-16 rounded-2xl bg-slate-700/60 text-amber-400 text-sm font-bold hover:bg-slate-700" id="sciBtn"><i class="fa-solid fa-flask"></i></button>
    <button onclick="pushBtn('0')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">0</button>
    <button onclick="pushBtn('.')" class="btn-press h-16 rounded-2xl bg-slate-800/80 text-white text-2xl font-bold border border-slate-700 hover:bg-slate-700">.</button>
    <button onclick="pushBtn('=')" class="btn-press h-16 rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 text-white text-2xl font-black shadow-lg shadow-cyan-500/40">=</button>
  </div>

  <div id="sciPanel" class="hidden mt-4 grid grid-cols-5 gap-2 pb-4">
    <button onclick="pushSci('sin')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">sin</button>
    <button onclick="pushSci('cos')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">cos</button>
    <button onclick="pushSci('tan')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">tan</button>
    <button onclick="pushSci('log')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">log</button>
    <button onclick="pushSci('ln')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">ln</button>
    <button onclick="pushSci('sqrt')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">√</button>
    <button onclick="pushSci('pow2')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">x²</button>
    <button onclick="pushSci('pow3')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">x³</button>
    <button onclick="pushSci('pi')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">π</button>
    <button onclick="pushSci('fact')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">x!</button>
    <button onclick="pushSci('1/x')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">1/x</button>
    <button onclick="pushSci('abs')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">|x|</button>
    <button onclick="pushSci('neg')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">±</button>
    <button onclick="pushSci('e')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">e</button>
    <button onclick="pushSci('mod')" class="btn-press h-12 rounded-xl bg-slate-700/60 text-amber-300 text-sm font-bold">mod</button>
  </div>
</div>

<script>
let expr = '', lastWasEq = false, dark = true;
const $ = s => document.querySelector(s);
function upd(){
  $('#display').textContent = expr ? formatNum(evalDisplay()) : '0';
  $('#history').textContent = expr.replace(/[*]/g,'\u00d7').replace(/[/]/g,'\u00f7').replace(/-/g,'\u2212');
}
function formatNum(n){
  if(n===Infinity||isNaN(n)) return 'Error';
  const s = String(Number(n.toPrecision(12)));
  return s.length>14 ? Number(n).toExponential(8) : s;
}
function evalDisplay(){ try { if(!expr) return 0; const e = expr.replace(/×/g,'*').replace(/÷/g,'/').replace(/−/g,'-'); return Function('"use strict";return ('+e+')')(); } catch { return 'Error'; } }
function fact(n){ n=parseInt(n); if(isNaN(n)||n<0) return NaN; if(n>170) return Infinity; let r=1; for(let i=2;i<=n;i++)r*=i; return r; }

function pushBtn(b){
  if(b==='clear'){ expr=''; lastWasEq=false; }
  else if(b==='back'){ expr=expr.slice(0,-1); }
  else if(b==='='){ try{ const r=evalDisplay(); if(r==='Error'){expr='Error'}else{expr=String(r); lastWasEq=true;} }catch{ expr='Error'; } }
  else if(b==='sci'){ $('#sciPanel').classList.toggle('hidden'); }
  else if(b==='%'){ if(expr){ try{ expr=String(parseFloat(evalDisplay())/100); }catch{} } }
  else { if(lastWasEq&&/[0-9.]/.test(b)&&expr!=='Error'){ expr=''; } lastWasEq=false; if(expr==='Error') expr=''; expr+=b; }
  upd();
}
function pushSci(op){
  let v = evalDisplay();
  if(v==='Error') return;
  const deg = x => x*Math.PI/180;
  let r = v;
  switch(op){
    case 'sin': r=Math.sin(deg(v)); break;
    case 'cos': r=Math.cos(deg(v)); break;
    case 'tan': r=Math.tan(deg(v)); break;
    case 'log': r=Math.log10(v); break;
    case 'ln': r=Math.log(v); break;
    case 'sqrt': r=Math.sqrt(v); break;
    case 'pow2': r=Math.pow(v,2); break;
    case 'pow3': r=Math.pow(v,3); break;
    case 'pi': expr=String(Math.PI); upd(); return;
    case 'fact': r=fact(v); break;
    case '1/x': r=1/v; break;
    case 'abs': r=Math.abs(v); break;
    case 'neg': r=-v; break;
    case 'e': expr=String(Math.E); upd(); return;
    case 'mod': expr+='%'; upd(); return;
  }
  expr = isNaN(r)?'Error':String(r); lastWasEq=true; upd();
}
function toggleTheme(){
  dark=!dark;
  document.body.className = dark
    ? 'min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white'
    : 'min-h-screen bg-gradient-to-br from-slate-100 via-white to-slate-200 text-slate-800';
}
upd();
</script>
</body>
</html>""")),

    ("timer", ("⏱️ Таймер", """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#f43f5e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Таймер</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>
try { if (window.Telegram && Telegram.WebApp) { const tg = Telegram.WebApp; tg.ready(); tg.expand(); try{ tg.setHeaderColor('#f43f5e'); tg.setBackgroundColor('#fff7ed');}catch(e){} if(tg.HapticFeedback) window.__tgHaptic=tg.HapticFeedback; if(tg.BackButton) tg.BackButton.hide(); try{tg.MainButton.hide();}catch(e){} window.__tg=tg; } } catch(e){}
function haptic(kind='light'){ try{ const h=window.__tgHaptic||(window.__tg&&__tg.HapticFeedback); if(!h) return; if(kind==='success')h.notificationOccurred('success'); else if(kind==='warn')h.notificationOccurred('warning'); else if(kind==='select')h.selectionChanged(); else h.impactOccurred(kind); }catch(e){} }
</script>
<style>
body { -webkit-tap-highlight-color: transparent; }
.progress-ring-circle { transition: stroke-dashoffset .5s ease; transform: rotate(-90deg); transform-origin: 50% 50%; }
@keyframes pulse-ring { 0%{box-shadow:0 0 0 0 rgba(239,68,68,.5)} 70%{box-shadow:0 0 0 20px rgba(239,68,68,0)} 100%{box-shadow:0 0 0 0 rgba(239,68,68,0)} }
.pulse { animation: pulse-ring 1.5s infinite; }
</style>
</head>
<body class="min-h-screen bg-gradient-to-br from-rose-50 via-white to-orange-50 dark:from-slate-900 dark:via-slate-800 dark:to-rose-950 text-slate-800 dark:text-white transition-colors duration-300">
<div class="max-w-xl mx-auto px-4 py-8">
  <div class="text-center mb-8">
    <h1 class="text-3xl font-black bg-gradient-to-r from-rose-500 to-orange-500 bg-clip-text text-transparent">Таймер</h1>
    <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">Установи время и нажми старт</p>
  </div>

  <div class="relative flex items-center justify-center mb-10">
    <svg class="w-72 h-72" viewBox="0 0 200 200">
      <circle cx="100" cy="100" r="90" fill="none" stroke="currentColor" class="text-slate-200 dark:text-slate-700" stroke-width="10"/>
      <circle id="ring" cx="100" cy="100" r="90" fill="none" stroke="url(#grad)" stroke-width="10" stroke-linecap="round" stroke-dasharray="565.48" stroke-dashoffset="0" class="progress-ring-circle"/>
      <defs><linearGradient id="grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#f43f5e"/><stop offset="100%" stop-color="#f97316"/></linearGradient></defs>
    </svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center">
      <div id="timeDisplay" class="text-6xl font-black font-mono tracking-tight tabular-nums">00:00</div>
      <div id="statusText" class="text-sm text-slate-500 dark:text-slate-400 mt-2 font-semibold">Готов к старту</div>
    </div>
  </div>

  <div id="setupPanel" class="bg-white dark:bg-slate-800 rounded-3xl p-5 shadow-xl border border-slate-100 dark:border-slate-700 mb-6">
    <div class="grid grid-cols-3 gap-3 mb-5">
      <div class="text-center">
        <div class="text-xs text-slate-500 dark:text-slate-400 mb-2 font-bold">Часы</div>
        <div class="flex flex-col gap-1 items-center">
          <button onclick="adj('h',1)" class="w-10 h-8 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 active:scale-90 transition"><i class="fa-solid fa-chevron-up text-xs"></i></button>
          <input id="h" type="number" min="0" max="23" value="0" class="w-16 h-12 text-center text-2xl font-black rounded-xl bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 outline-none">
          <button onclick="adj('h',-1)" class="w-10 h-8 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 active:scale-90 transition"><i class="fa-solid fa-chevron-down text-xs"></i></button>
        </div>
      </div>
      <div class="text-center">
        <div class="text-xs text-slate-500 dark:text-slate-400 mb-2 font-bold">Минуты</div>
        <div class="flex flex-col gap-1 items-center">
          <button onclick="adj('m',1)" class="w-10 h-8 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 active:scale-90 transition"><i class="fa-solid fa-chevron-up text-xs"></i></button>
          <input id="m" type="number" min="0" max="59" value="5" class="w-16 h-12 text-center text-2xl font-black rounded-xl bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 outline-none">
          <button onclick="adj('m',-1)" class="w-10 h-8 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 active:scale-90 transition"><i class="fa-solid fa-chevron-down text-xs"></i></button>
        </div>
      </div>
      <div class="text-center">
        <div class="text-xs text-slate-500 dark:text-slate-400 mb-2 font-bold">Секунды</div>
        <div class="flex flex-col gap-1 items-center">
          <button onclick="adj('s',1)" class="w-10 h-8 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 active:scale-90 transition"><i class="fa-solid fa-chevron-up text-xs"></i></button>
          <input id="s" type="number" min="0" max="59" value="0" class="w-16 h-12 text-center text-2xl font-black rounded-xl bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 outline-none">
          <button onclick="adj('s',-1)" class="w-10 h-8 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 active:scale-90 transition"><i class="fa-solid fa-chevron-down text-xs"></i></button>
        </div>
      </div>
    </div>
    <div class="grid grid-cols-4 gap-2">
      <button onclick="preset(60)" class="py-2.5 rounded-xl bg-slate-100 dark:bg-slate-700 text-sm font-bold hover:bg-slate-200 dark:hover:bg-slate-600 active:scale-95 transition">1 мин</button>
      <button onclick="preset(300)" class="py-2.5 rounded-xl bg-slate-100 dark:bg-slate-700 text-sm font-bold hover:bg-slate-200 dark:hover:bg-slate-600 active:scale-95 transition">5 мин</button>
      <button onclick="preset(600)" class="py-2.5 rounded-xl bg-slate-100 dark:bg-slate-700 text-sm font-bold hover:bg-slate-200 dark:hover:bg-slate-600 active:scale-95 transition">10 мин</button>
      <button onclick="preset(1500)" class="py-2.5 rounded-xl bg-slate-100 dark:bg-slate-700 text-sm font-bold hover:bg-slate-200 dark:hover:bg-slate-600 active:scale-95 transition">25 мин</button>
    </div>
  </div>

  <div class="flex gap-3 justify-center">
    <button id="startBtn" onclick="startTimer()" class="px-8 py-4 rounded-2xl bg-gradient-to-br from-rose-500 to-orange-500 text-white text-lg font-black shadow-xl shadow-rose-500/30 active:scale-95 transition flex items-center gap-2"><i class="fa-solid fa-play"></i> Старт</button>
    <button onclick="resetTimer()" class="px-6 py-4 rounded-2xl bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200 text-lg font-bold active:scale-95 transition"><i class="fa-solid fa-rotate-left"></i></button>
  </div>
</div>

<script>
let totalSec = 0, remainSec = 0, interval = null, running = false;
const $ = s => document.querySelector(s);
const CIRC = 2 * Math.PI * 90;
function fmt(sec){
  sec = Math.max(0, sec);
  const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = sec%60;
  return h>0 ? `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}
function updateDisplay(){
  $('#timeDisplay').textContent = fmt(remainSec);
  document.title = running ? `⏱ ${fmt(remainSec)}` : 'Таймер';
  const pct = totalSec>0 ? remainSec/totalSec : 1;
  $('#ring').style.strokeDashoffset = CIRC*(1-pct);
}
function readInputs(){
  return Math.min(23*3600+59*60+59, Math.max(0, (parseInt($('#h').value)||0)*3600 + (parseInt($('#m').value)||0)*60 + (parseInt($('#s').value)||0)));
}
function adj(t,d){
  const el = $('#'+t); const v = parseInt(el.value)||0; const mxs = {h:23,m:59,s:59};
  el.value = Math.max(0, Math.min(mxs[t], v+d)); updateFromInputs();
}
function preset(sec){ $('#h').value=Math.floor(sec/3600); $('#m').value=Math.floor((sec%3600)/60); $('#s').value=sec%60; updateFromInputs(); }
function updateFromInputs(){ totalSec = readInputs(); remainSec = totalSec; running = false; $('#statusText').textContent='Готов к старту'; updateDisplay(); }
function startTimer(){
  if(running){ clearInterval(interval); running=false; $('#startBtn').innerHTML='<i class="fa-solid fa-play"></i> Продолжить'; $('#statusText').textContent='Пауза'; document.body.classList.remove('pulse'); return; }
  if(remainSec<=0){ totalSec = readInputs(); remainSec = totalSec; }
  if(remainSec<=0) return;
  running = true; $('#setupPanel').style.opacity='0.5'; $('#setupPanel').style.pointerEvents='none';
  $('#startBtn').innerHTML='<i class="fa-solid fa-pause"></i> Пауза'; $('#statusText').textContent='Время идёт...';
  interval = setInterval(()=>{
    remainSec--; updateDisplay();
    if(remainSec<=0){
      clearInterval(interval); running=false; finish();
    }
  },1000);
}
function resetTimer(){ clearInterval(interval); running=false; $('#startBtn').innerHTML='<i class="fa-solid fa-play"></i> Старт'; $('#setupPanel').style.opacity='1'; $('#setupPanel').style.pointerEvents=''; document.body.classList.remove('pulse'); updateFromInputs(); }
function beep(){
  try { const ctx = new (window.AudioContext||window.webkitAudioContext)();
    for(let i=0;i<3;i++){ const o=ctx.createOscillator(), g=ctx.createGain(); o.frequency.value=800; o.type='sine'; g.gain.setValueAtTime(0.0001,ctx.currentTime+i*0.4); g.gain.exponentialRampToValueAtTime(0.3,ctx.currentTime+0.01+i*0.4); g.gain.exponentialRampToValueAtTime(0.0001,ctx.currentTime+0.25+i*0.4); o.connect(g); g.connect(ctx.destination); o.start(ctx.currentTime+i*0.4); o.stop(ctx.currentTime+0.3+i*0.4); }
  } catch(e) {}
}
function finish(){
  $('#statusText').textContent='⏰ Время вышло!';
  $('#startBtn').innerHTML='<i class="fa-solid fa-play"></i> Старт';
  $('#setupPanel').style.opacity='1'; $('#setupPanel').style.pointerEvents='';
  for(let i=0;i<5;i++) setTimeout(()=>{ beep(); }, i*400);
  if(navigator.vibrate) navigator.vibrate([300,150,300,150,300]);
  document.body.classList.add('pulse');
}
$('#h').addEventListener('input', updateFromInputs); $('#m').addEventListener('input', updateFromInputs); $('#s').addEventListener('input', updateFromInputs);
updateFromInputs();
</script>
</body>
</html>""")),

    ("weather", ("🌤️ Погода", """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#f97316">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Погода</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>
try { if (window.Telegram && Telegram.WebApp) { const tg = Telegram.WebApp; tg.ready(); tg.expand(); try{ tg.setHeaderColor('#f97316');}catch(e){} if(tg.HapticFeedback) window.__tgHaptic=tg.HapticFeedback; if(tg.BackButton) tg.BackButton.hide(); try{tg.MainButton.hide();}catch(e){} window.__tg=tg; } } catch(e){}
function haptic(kind='light'){ try{ const h=window.__tgHaptic||(window.__tg&&__tg.HapticFeedback); if(!h) return; if(kind==='success')h.notificationOccurred('success'); else if(kind==='error')h.notificationOccurred('error'); else if(kind==='select')h.selectionChanged(); else h.impactOccurred(kind); }catch(e){} }
</script>
<script>
tailwind.config = { theme: { extend: { animation: { 'fade-in': 'fadeIn .5s ease', 'float': 'float 6s ease-in-out infinite' } } } };
</script>
<style>
@keyframes fadeIn { from {opacity:0;transform:translateY(10px)} to {opacity:1;transform:translateY(0)} }
@keyframes float { 0%,100% {transform:translateY(0)} 50% {transform:translateY(-12px)} }
.weather-bg-sunny { background: linear-gradient(135deg,#fcd34d 0%,#fb923c 50%,#f97316 100%); }
.weather-bg-cloudy { background: linear-gradient(135deg,#94a3b8 0%,#64748b 50%,#475569 100%); }
.weather-bg-rainy { background: linear-gradient(135deg,#64748b 0%,#334155 50%,#1e293b 100%); }
.weather-bg-night { background: linear-gradient(135deg,#1e1b4b 0%,#312e81 50%,#4c1d95 100%); }
body { -webkit-tap-highlight-color: transparent; }
</style>
</head>
<body id="weatherBody" class="min-h-screen weather-bg-sunny text-white transition-all duration-700">
<div class="max-w-xl mx-auto px-4 py-6 pb-24">
  <div class="mb-6">
    <h1 class="text-2xl font-black mb-4"><i class="fa-solid fa-cloud-sun mr-2"></i>Погода</h1>
    <div class="relative">
      <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-white/60"></i>
      <input id="cityInput" type="text" placeholder="Введи город..." value="Москва" class="w-full pl-11 pr-11 py-3.5 rounded-2xl bg-white/20 backdrop-blur-md border border-white/30 text-white placeholder-white/60 outline-none focus:ring-2 focus:ring-white/50 font-medium">
      <button onclick="loadWeather()" class="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-xl bg-white/25 hover:bg-white/35 flex items-center justify-center active:scale-90 transition"><i class="fa-solid fa-arrow-right"></i></button>
    </div>
    <div class="flex gap-2 mt-3 flex-wrap">
      <button onclick="setCity('Москва')" class="px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-sm font-semibold active:scale-95 transition">Москва</button>
      <button onclick="setCity('Санкт-Петербург')" class="px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-sm font-semibold active:scale-95 transition">СПб</button>
      <button onclick="setCity('Сочи')" class="px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-sm font-semibold active:scale-95 transition">Сочи</button>
      <button onclick="setCity('Казань')" class="px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-sm font-semibold active:scale-95 transition">Казань</button>
      <button onclick="setCity('Нью-Йорк')" class="px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-sm font-semibold active:scale-95 transition">Нью-Йорк</button>
      <button onclick="setCity('Токио')" class="px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-sm font-semibold active:scale-95 transition">Токио</button>
    </div>
  </div>

  <div id="loading" class="text-center py-20 hidden"><i class="fa-solid fa-spinner fa-spin text-5xl opacity-60"></i><p class="mt-4 opacity-80 font-semibold">Загружаю...</p></div>
  <div id="mainCard" class="animate-fade-in">
    <div class="text-center mb-8">
      <div id="cityName" class="text-3xl font-black">—</div>
      <div id="weatherDate" class="text-sm opacity-80 mt-1"></div>
      <div id="weatherIcon" class="text-8xl my-6 animate-float">☀️</div>
      <div id="temperature" class="text-8xl font-black leading-none">—°</div>
      <div id="condition" class="text-xl font-semibold opacity-90 mt-3">—</div>
      <div id="feelsLike" class="text-sm opacity-70 mt-1">—</div>
    </div>

    <div class="grid grid-cols-2 gap-3 mb-4">
      <div class="bg-white/15 backdrop-blur-md rounded-2xl p-4 border border-white/20">
        <div class="flex items-center gap-2 opacity-80 text-sm font-semibold mb-1"><i class="fa-solid fa-wind"></i> Ветер</div>
        <div id="wind" class="text-2xl font-black">— м/с</div>
      </div>
      <div class="bg-white/15 backdrop-blur-md rounded-2xl p-4 border border-white/20">
        <div class="flex items-center gap-2 opacity-80 text-sm font-semibold mb-1"><i class="fa-solid fa-droplet"></i> Влажность</div>
        <div id="humidity" class="text-2xl font-black">— %</div>
      </div>
      <div class="bg-white/15 backdrop-blur-md rounded-2xl p-4 border border-white/20">
        <div class="flex items-center gap-2 opacity-80 text-sm font-semibold mb-1"><i class="fa-solid fa-gauge-high"></i> Давление</div>
        <div id="pressure" class="text-2xl font-black">— мм</div>
      </div>
      <div class="bg-white/15 backdrop-blur-md rounded-2xl p-4 border border-white/20">
        <div class="flex items-center gap-2 opacity-80 text-sm font-semibold mb-1"><i class="fa-solid fa-eye"></i> Видимость</div>
        <div id="visibility" class="text-2xl font-black">— км</div>
      </div>
    </div>

    <div id="forecastTitle" class="text-lg font-bold mb-3 mt-6 opacity-90"><i class="fa-regular fa-clock mr-2"></i>Прогноз на 5 дней</div>
    <div id="forecastList" class="grid grid-cols-5 gap-2"></div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const $a = s => document.querySelectorAll(s);
const monthsR = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
const daysR = ['Вс','Пн','Вт','Ср','Чт','Пт','Сб'];

function setCity(c){ $('#cityInput').value=c; loadWeather(); }
$('#cityInput').addEventListener('keypress', e => { if(e.key==='Enter') loadWeather(); });

function pickBg(code, h){
  const b = $('#weatherBody');
  if(h<6||h>=21){ b.className='min-h-screen weather-bg-night text-white transition-all duration-700'; return; }
  if(code>=200&&code<300||code>=500&&code<600){ b.className='min-h-screen weather-bg-rainy text-white transition-all duration-700'; }
  else if(code>=803||code==802){ b.className='min-h-screen weather-bg-cloudy text-white transition-all duration-700'; }
  else { b.className='min-h-screen weather-bg-sunny text-white transition-all duration-700'; }
}
function wIcon(code, h){
  const night = h<6||h>=21;
  const map = {
    '2': '⛈️','3': '🌦️','5': '🌧️','6': '🌨️','7': '🌫️',
    '800': night?'🌙':'☀️','801':'🌤️','802':'⛅','803':'☁️','804':'☁️'
  };
  if(code==800) return map['800'];
  if(code>=801) return map[String(code)]||'☁️';
  return map[String(Math.floor(code/100))]||'🌡️';
}

async function loadWeather(){
  const city = $('#cityInput').value.trim();
  if(!city) return;
  $('#loading').classList.remove('hidden'); $('#mainCard').classList.add('hidden');
  try {
    const geo = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=1&language=ru`).then(r=>r.json());
    if(!geo.results?.length) throw new Error('Город не найден');
    const {latitude, longitude, name, country} = geo.results[0];
    const now = new Date();
    const w = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current=temperature_2m,relative_humidity_2m,apparent_temperature,pressure_msl,weather_code,wind_speed_10m,visibility&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=5`).then(r=>r.json());
    const c = w.current;
    const hour = now.getHours();
    pickBg(c.weather_code, hour);
    const condMap = {0:'Ясно',1:'Преим. ясно',2:'Перем. облачн.',3:'Пасмурно',45:'Туман',48:'Иней',51:'Морось',53:'Морось',55:'Морось',61:'Дождь',63:'Дождь',65:'Сильный дождь',71:'Снег',73:'Снег',75:'Снег',80:'Ливень',81:'Ливень',82:'Ливень',95:'Гроза',96:'Гроза с градом',99:'Гроза сильная'};

    $('#cityName').textContent = `${name}, ${country||''}`;
    $('#weatherDate').textContent = `${now.getDate()} ${monthsR[now.getMonth()]} · ${daysR[now.getDay()]}`;
    $('#weatherIcon').textContent = wIcon(c.weather_code, hour);
    $('#temperature').textContent = `${Math.round(c.temperature_2m)}°`;
    $('#condition').textContent = condMap[c.weather_code]||`Код ${c.weather_code}`;
    $('#feelsLike').textContent = `Ощущается как ${Math.round(c.apparent_temperature)}°`;
    $('#wind').textContent = `${Math.round(c.wind_speed_10m)} м/с`;
    $('#humidity').textContent = `${c.relative_humidity_2m} %`;
    $('#pressure').textContent = `${Math.round(c.pressure_msl*0.75)} мм`;
    $('#visibility').textContent = `${Math.round((c.visibility||0)/1000} км`;

    $('#forecastList').innerHTML = '';
    for(let i=0;i<5;i++){
      const d = new Date(w.daily.time[i]);
      $('#forecastList.innerHTML += `
        <div class="bg-white/10 backdrop-blur rounded-2xl p-3 border border-white/15 text-center">
          <div class="text-xs opacity-75 font-semibold">${daysR[d.getDay()]}</div>
          <div class="text-2xl my-1.5">${wIcon(w.daily.weather_code[i],14)}</div>
          <div class="text-sm font-black">${Math.round(w.daily.temperature_2m_max[i])}°</div>
          <div class="text-xs opacity-70">${Math.round(w.daily.temperature_2m_min[i])}°</div>
        </div>`;
    }
    localStorage.setItem('weather_city', city);
  } catch(err){
    $('#loading').innerHTML = `<div class="text-5xl mb-4 opacity-60">😕</div><p class="font-bold">Не удалось загрузить погоду</p><p class="text-sm opacity-80 mt-1">${err.message||'Проверь интернет'}</p>`;
    $('#loading').classList.remove('hidden'); return;
  } finally {
    $('#mainCard').classList.remove('hidden');
  }
}
if(localStorage.getItem('weather_city')) $('#cityInput').value = localStorage.getItem('weather_city');
loadWeather();
</script>
</body>
</html>""")),

    ("notes", ("📖 Заметки", """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#f59e0b">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Заметки</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>
try { if (window.Telegram && Telegram.WebApp) { const tg = Telegram.WebApp; tg.ready(); tg.expand(); try{ tg.setHeaderColor('#f59e0b'); tg.setBackgroundColor('#fffbeb');}catch(e){} if(tg.HapticFeedback) window.__tgHaptic=tg.HapticFeedback; if(tg.BackButton) tg.BackButton.hide(); try{tg.MainButton.hide();}catch(e){} window.__tg=tg; } } catch(e){}
function haptic(kind='light'){ try{ const h=window.__tgHaptic||(window.__tg&&__tg.HapticFeedback); if(!h) return; if(kind==='success')h.notificationOccurred('success'); else if(kind==='error')h.notificationOccurred('error'); else if(kind==='select')h.selectionChanged(); else h.impactOccurred(kind); }catch(e){} }
</script>
<script>
tailwind.config = { darkMode: 'class' };
</script>
<style>
body { -webkit-tap-highlight-color: transparent; }
.note-card { transition: all .2s ease; }
.note-card:hover { transform: translateY(-2px); }
</style>
</head>
<body class="min-h-screen bg-gradient-to-br from-amber-50 via-orange-50 to-yellow-50 dark:from-slate-900 dark:via-slate-800 dark:to-amber-950 text-slate-800 dark:text-slate-100 transition-colors duration-300">
<div class="max-w-2xl mx-auto px-4 py-6 pb-32">
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-3xl font-black bg-gradient-to-r from-amber-600 to-orange-600 bg-clip-text text-transparent">Заметки</h1>
      <p class="text-sm text-slate-500 dark:text-slate-400 mt-1"><span id="noteCount">0</span> заметок</p>
    </div>
    <div class="flex gap-2">
      <button onclick="toggleTheme()" class="w-11 h-11 rounded-2xl bg-white dark:bg-slate-800 shadow-lg border border-slate-200 dark:border-slate-700 flex items-center justify-center active:scale-95 transition"><i id="ntIcon" class="fa-solid fa-moon text-amber-500"></i></button>
    </div>
  </div>

  <div class="relative mb-6">
    <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-slate-400"></i>
    <input id="search" oninput="render()" type="text" placeholder="Поиск заметок..." class="w-full pl-11 pr-4 py-3.5 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-200 dark:focus:ring-amber-900 shadow-sm">
  </div>

  <div class="flex gap-2 mb-5 overflow-x-auto pb-2 -mx-4 px-4">
    <button onclick="setColorFilter('')" data-col="" class="color-filter flex-shrink-0 px-4 py-2 rounded-full text-sm font-bold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm active:scale-95 transition">Все</button>
    <button onclick="setColorFilter('yellow')" data-col="yellow" class="color-filter flex-shrink-0 px-4 py-2 rounded-full text-sm font-bold bg-yellow-200/70 dark:bg-yellow-900/40 text-yellow-900 dark:text-yellow-200 border border-yellow-300 dark:border-yellow-700 active:scale-95 transition">💛</button>
    <button onclick="setColorFilter('green')" data-col="green" class="color-filter flex-shrink-0 px-4 py-2 rounded-full text-sm font-bold bg-emerald-200/70 dark:bg-emerald-900/40 text-emerald-900 dark:text-emerald-200 border border-emerald-300 dark:border-emerald-700 active:scale-95 transition">💚</button>
    <button onclick="setColorFilter('blue')" data-col="blue" class="color-filter flex-shrink-0 px-4 py-2 rounded-full text-sm font-bold bg-sky-200/70 dark:bg-sky-900/40 text-sky-900 dark:text-sky-200 border border-sky-300 dark:border-sky-700 active:scale-95 transition">💙</button>
    <button onclick="setColorFilter('pink')" data-col="pink" class="color-filter flex-shrink-0 px-4 py-2 rounded-full text-sm font-bold bg-pink-200/70 dark:bg-pink-900/40 text-pink-900 dark:text-pink-200 border border-pink-300 dark:border-pink-700 active:scale-95 transition">💗</button>
    <button onclick="setColorFilter('purple')" data-col="purple" class="color-filter flex-shrink-0 px-4 py-2 rounded-full text-sm font-bold bg-violet-200/70 dark:bg-violet-900/40 text-violet-900 dark:text-violet-200 border border-violet-300 dark:border-violet-700 active:scale-95 transition">💜</button>
  </div>

  <div id="notesGrid" class="grid grid-cols-1 sm:grid-cols-2 gap-3"></div>
  <div id="emptyNotes" class="hidden text-center py-20">
    <div class="text-7xl mb-4 opacity-40">📝</div>
    <p class="text-lg font-bold text-slate-600 dark:text-slate-300">Заметок пока нет</p>
    <p class="text-sm text-slate-500 dark:text-slate-400 mt-2">Нажми + внизу, чтобы создать первую</p>
  </div>
</div>

<button onclick="openEditor()" class="fixed bottom-6 right-6 w-16 h-16 rounded-3xl bg-gradient-to-br from-amber-500 to-orange-500 text-white text-2xl font-black shadow-2xl shadow-amber-500/40 active:scale-90 transition z-40 flex items-center justify-center"><i class="fa-solid fa-plus"></i></button>

<div id="editor" class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 hidden items-end sm:items-center justify-center">
  <div class="bg-white dark:bg-slate-800 w-full sm:max-w-lg sm:rounded-3xl rounded-t-3xl max-h-[90vh] flex flex-col animate-slide-up border-t border-slate-200 dark:border-slate-700 sm:border shadow-2xl">
    <div class="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
      <h2 id="editorTitle" class="font-black text-lg">Новая заметка</h2>
      <button onclick="closeEditor()" class="w-10 h-10 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-700 flex items-center justify-center active:scale-90 transition"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <div class="p-4 flex-1 overflow-y-auto">
      <input id="titleInput" type="text" placeholder="Заголовок..." class="w-full text-2xl font-black bg-transparent outline-none mb-3 placeholder-slate-400">
      <textarea id="bodyInput" placeholder="Напиши что-нибудь..." class="w-full h-64 bg-transparent outline-none resize-none text-base placeholder-slate-400 leading-relaxed"></textarea>
      <div class="flex gap-2 mt-3">
        <button onclick="setColor('yellow')" data-ec="yellow" class="ec-btn w-9 h-9 rounded-full bg-yellow-200 dark:bg-yellow-900/40 border-2 border-yellow-300 dark:border-yellow-700 active:scale-90 transition"></button>
        <button onclick="setColor('green')" data-ec="green" class="ec-btn w-9 h-9 rounded-full bg-emerald-200 dark:bg-emerald-900/40 border-2 border-emerald-300 dark:border-emerald-700 active:scale-90 transition"></button>
        <button onclick="setColor('blue')" data-ec="blue" class="ec-btn w-9 h-9 rounded-full bg-sky-200 dark:bg-sky-900/40 border-2 border-sky-300 dark:border-sky-700 active:scale-90 transition"></button>
        <button onclick="setColor('pink')" data-ec="pink" class="ec-btn w-9 h-9 rounded-full bg-pink-200 dark:bg-pink-900/40 border-2 border-pink-300 dark:border-pink-700 active:scale-90 transition"></button>
        <button onclick="setColor('purple')" data-ec="purple" class="ec-btn w-9 h-9 rounded-full bg-violet-200 dark:bg-violet-900/40 border-2 border-violet-300 dark:border-violet-700 active:scale-90 transition"></button>
      </div>
    </div>
    <div class="p-4 border-t border-slate-200 dark:border-slate-700 flex gap-2">
      <button id="delBtn" onclick="deleteCurrent()" class="hidden px-4 py-3 rounded-2xl bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 font-bold active:scale-95 transition"><i class="fa-solid fa-trash mr-1"></i>Удалить</button>
      <div class="flex-1"></div>
      <button onclick="closeEditor()" class="px-5 py-3 rounded-2xl bg-slate-100 dark:bg-slate-700 font-bold active:scale-95 transition">Отмена</button>
      <button onclick="saveNote()" class="px-6 py-3 rounded-2xl bg-gradient-to-br from-amber-500 to-orange-500 text-white font-black shadow-lg shadow-amber-500/30 active:scale-95 transition">Сохранить</button>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let notes = JSON.parse(localStorage.getItem('notes_app') || '[]');
let currentId = null, currentColor = 'yellow', colorFilter = '';
const colBg = {
  yellow:'bg-yellow-100 dark:bg-yellow-900/30 border-yellow-200 dark:border-yellow-800/40',
  green:'bg-emerald-100 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800/40',
  blue:'bg-sky-100 dark:bg-sky-900/30 border-sky-200 dark:border-sky-800/40',
  pink:'bg-pink-100 dark:bg-pink-900/30 border-pink-200 dark:border-pink-800/40',
  purple:'bg-violet-100 dark:bg-violet-900/30 border-violet-200 dark:border-violet-800/40'
};

function save(){ localStorage.setItem('notes_app', JSON.stringify(notes)); }
function escapeHtml(s){ return (s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function toggleTheme(){
  document.documentElement.classList.toggle('dark');
  localStorage.setItem('notes_theme', document.documentElement.classList.contains('dark')?'dark':'light');
  $('#ntIcon').className = document.documentElement.classList.contains('dark') ? 'fa-solid fa-sun text-amber-400' : 'fa-solid fa-moon text-amber-500';
}
if(localStorage.getItem('notes_theme')==='dark'){ document.documentElement.classList.add('dark'); $('#ntIcon').className='fa-solid fa-sun text-amber-400'; }

function setColorFilter(c){
  colorFilter=c;
  document.querySelectorAll('.color-filter').forEach(b=>{
    const act = b.dataset.col===c;
    b.classList.toggle('ring-2', act); b.classList.toggle('ring-amber-500', act); b.classList.toggle('ring-offset-2', act);
  });
  render();
}

function openEditor(id=null){
  currentId = id;
  if(id){
    const n = notes.find(x=>x.id===id);
    $('#editorTitle').textContent='Редактирование';
    $('#titleInput').value=n.title||''; $('#bodyInput').value=n.body||'';
    currentColor = n.color||'yellow';
    $('#delBtn').classList.remove('hidden');
  } else {
    $('#editorTitle').textContent='Новая заметка';
    $('#titleInput').value=''; $('#bodyInput').value='';
    currentColor='yellow';
    $('#delBtn').classList.add('hidden');
  }
  setColor(currentColor);
  const ed = $('#editor'); ed.classList.remove('hidden'); ed.classList.add('flex');
  setTimeout(()=>$('#titleInput').focus(),100);
}
function closeEditor(){ $('#editor').classList.add('hidden'); $('#editor').classList.remove('flex'); }
$('#editor').addEventListener('click',e=>{ if(e.target.id==='editor') closeEditor(); });

function setColor(c){
  currentColor = c;
  document.querySelectorAll('.ec-btn').forEach(b=>{
    b.classList.toggle('ring-2', b.dataset.ec===c);
    b.classList.toggle('ring-slate-500', b.dataset.ec===c);
    b.classList.toggle('ring-offset-2', b.dataset.ec===c);
  });
}
function saveNote(){
  const title = $('#titleInput').value.trim();
  const body = $('#bodyInput').value.trim();
  if(!title && !body){ closeEditor(); return; }
  if(currentId){
    const n = notes.find(x=>x.id===currentId);
    Object.assign(n, {title, body, color:currentColor, updatedAt:Date.now()});
  } else {
    notes.unshift({id:Date.now(), title, body, color:currentColor, createdAt:Date.now(), updatedAt:Date.now()});
  }
  save(); closeEditor(); render();
}
function deleteCurrent(){
  if(!currentId) return;
  notes = notes.filter(n=>n.id!==currentId);
  save(); closeEditor(); render();
}

function render(){
  const q = $('#search').value.toLowerCase();
  const filtered = notes.filter(n=>(!colorFilter||n.color===colorFilter)&&(!q||(n.title+' '+n.body).toLowerCase().includes(q));
  $('#noteCount').textContent = notes.length;
  $('#emptyNotes').classList.toggle('hidden', filtered.length>0);
  $('#notesGrid').innerHTML = filtered.map(n=>{
    const d = new Date(n.updatedAt||n.createdAt);
    return `<div onclick="openEditor(${n.id})" class="note-card ${colBg[n.color]||colBg.yellow} border rounded-2xl p-4 cursor-pointer shadow-sm hover:shadow-md">
      <div class="font-black text-lg mb-1 break-words ${!n.title?'opacity-60 italic':''}">${escapeHtml(n.title||'(Без заголовка)')}</div>
      <div class="text-sm opacity-80 line-clamp-6 break-words whitespace-pre-wrap leading-relaxed">${escapeHtml(n.body||'')}</div>
      <div class="text-xs opacity-50 mt-3 font-semibold">${String(d.getDate()).padStart(2,'0')}.${String(d.getMonth()+1).padStart(2,'0')} · ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}</div>
    </div>`;
  }).join('');
}
setColorFilter('');
</script>
</body>
</html>""")),

    ("pomodoro", ("🍅 Pomodoro", """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#dc2626">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Pomodoro</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>
try { if (window.Telegram && Telegram.WebApp) { const tg = Telegram.WebApp; tg.ready(); tg.expand(); try{ tg.setHeaderColor('#dc2626'); tg.setBackgroundColor('#fef2f2');}catch(e){} if(tg.HapticFeedback) window.__tgHaptic=tg.HapticFeedback; if(tg.BackButton) tg.BackButton.hide(); try{tg.MainButton.hide();}catch(e){} window.__tg=tg; } } catch(e){}
function haptic(kind='light'){ try{ const h=window.__tgHaptic||(window.__tg&&__tg.HapticFeedback); if(!h) return; if(kind==='success')h.notificationOccurred('success'); else if(kind==='warn')h.notificationOccurred('warning'); else if(kind==='select')h.selectionChanged(); else h.impactOccurred(kind); }catch(e){} }
</script>
<style>
body { -webkit-tap-highlight-color: transparent; }
.tomato-svg { filter: drop-shadow(0 10px 25px rgba(220,38,38,.35)); }
@keyframes pulse-red { 0%,100% { box-shadow: 0 0 0 0 rgba(239,68,68,.5) } 50% { box-shadow: 0 0 0 15px rgba(239,68,68,0) } }
.running { animation: pulse-red 2s infinite; }
</style>
</head>
<body id="pmBody" class="min-h-screen bg-gradient-to-br from-red-50 via-rose-50 to-orange-50 dark:from-slate-900 dark:via-slate-800 dark:to-red-950 text-slate-800 dark:text-white transition-all duration-500">
<div class="max-w-xl mx-auto px-4 py-6 pb-24">
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-3xl font-black text-red-600 dark:text-red-400"><i class="fa-solid fa-tomato mr-2"></i>Pomodoro</h1>
      <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">Фокус · 25/5 · продуктивность</p>
    </div>
    <button onclick="toggleTheme()" class="w-11 h-11 rounded-2xl bg-white dark:bg-slate-800 shadow-lg border border-slate-200 dark:border-slate-700 flex items-center justify-center active:scale-95 transition"><i id="pmIcon" class="fa-solid fa-moon text-red-500"></i></button>
  </div>

  <div class="flex gap-2 mb-6 bg-white dark:bg-slate-800 rounded-2xl p-1.5 shadow-md border border-slate-100 dark:border-slate-700">
    <button onclick="setMode('work')" data-mode="work" class="mode-btn flex-1 py-2.5 rounded-xl font-bold text-sm active:scale-95 transition">🍅 Фокус</button>
    <button onclick="setMode('short')" data-mode="short" class="mode-btn flex-1 py-2.5 rounded-xl font-bold text-sm active:scale-95 transition">☕ Короткий</button>
    <button onclick="setMode('long')" data-mode="long" class="mode-btn flex-1 py-2.5 rounded-xl font-bold text-sm active:scale-95 transition">🌴 Длинный</button>
  </div>

  <div class="flex flex-col items-center mb-8 relative">
    <div class="tomato-svg relative">
      <svg width="260" height="260" viewBox="0 0 260 260">
        <defs><linearGradient id="tg" x1="0" y1="0" x2="1" y2="1">
          <stop id="stop1" offset="0%" stop-color="#ef4444"/>
          <stop id="stop2" offset="100%" stop-color="#dc2626"/>
        </linearGradient></defs>
        <circle cx="130" cy="140" r="115" fill="none" stroke="currentColor" class="text-slate-200 dark:text-slate-700" stroke-width="10" opacity="0.3"/>
        <circle id="pmRing" cx="130" cy="140" r="115" fill="none" stroke="url(#tg)" stroke-width="10" stroke-linecap="round" stroke-dasharray="722.57" stroke-dashoffset="0" style="transform:rotate(-90deg);transform-origin:130px 140px;transition:stroke-dashoffset .5s ease"/>
      </svg>
      <div class="absolute inset-0 flex flex-col items-center justify-center pt-2">
        <div id="pmTime" class="text-6xl font-black font-mono tabular-nums tracking-tight">25:00</div>
        <div id="pmStatus" class="text-sm font-bold text-slate-500 dark:text-slate-400 mt-2">Время фокусировки</div>
      </div>
    </div>
  </div>

  <div class="flex gap-3 justify-center mb-8">
    <button id="pmStart" onclick="toggleRun()" class="px-10 py-4 rounded-2xl bg-gradient-to-br from-red-500 to-rose-600 text-white text-lg font-black shadow-xl shadow-red-500/30 active:scale-95 transition flex items-center gap-2"><i class="fa-solid fa-play"></i> Старт</button>
    <button onclick="resetAll()" class="px-6 py-4 rounded-2xl bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 text-lg font-bold border border-slate-200 dark:border-slate-700 active:scale-95 transition shadow-sm"><i class="fa-solid fa-rotate-left"></i></button>
    <button onclick="skip()" class="px-6 py-4 rounded-2xl bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 text-lg font-bold border border-slate-200 dark:border-slate-700 active:scale-95 transition shadow-sm"><i class="fa-solid fa-forward-step"></i></button>
  </div>

  <div class="bg-white dark:bg-slate-800 rounded-3xl p-5 shadow-xl border border-slate-100 dark:border-slate-700 mb-6">
    <div class="flex items-center justify-between mb-4">
      <div class="font-black text-lg">Прогресс сегодня</div>
      <div id="pmRound" class="px-3 py-1 rounded-full bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-sm font-black">0 / 4</div>
    </div>
    <div id="pmDots" class="flex gap-2 mb-4"></div>
    <div class="grid grid-cols-2 gap-3 text-center">
      <div class="p-3 rounded-2xl bg-slate-50 dark:bg-slate-700/50"><div id="pmFocusMin" class="text-2xl font-black text-red-500">0</div><div class="text-xs text-slate-500 dark:text-slate-400 font-semibold">мин фокуса</div></div>
      <div class="p-3 rounded-2xl bg-slate-50 dark:bg-slate-700/50"><div id="pmSessions" class="text-2xl font-black text-emerald-500">0</div><div class="text-xs text-slate-500 dark:text-slate-400 font-semibold">сессий всего</div></div>
    </div>
  </div>

  <div class="bg-white dark:bg-slate-800 rounded-3xl p-5 shadow-md border border-slate-100 dark:border-slate-700">
    <div class="font-black mb-3"><i class="fa-solid fa-list-check mr-2 text-red-500"></i>Задача на сессию</div>
    <div class="flex gap-2">
      <input id="pmTask" onkeypress="if(event.key==='Enter')addTask()" type="text" placeholder="Над чем работаешь?" class="flex-1 px-4 py-3 rounded-2xl bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 outline-none focus:border-red-500">
      <button onclick="addTask()" class="px-5 py-3 rounded-2xl bg-red-500 text-white font-bold active:scale-95 transition"><i class="fa-solid fa-plus"></i></button>
    </div>
    <div id="pmTasks" class="mt-3 space-y-2"></div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const DURATIONS = { work: 25*60, short: 5*60, long: 15*60 };
const CIRC = 2 * Math.PI * 115;
let mode = 'work', remain = DURATIONS.work, running = false, interval = null;
let stats = JSON.parse(localStorage.getItem('pm_stats') || JSON.stringify({rounds:0,total:0,focusMin:0,today:new Date().toDateString(),tasks:[]}));
if(stats.today !== new Date().toDateString()){ stats = {rounds:0,total:stats.total||0,focusMin:0,today:new Date().toDateString(),tasks:[]}; }
if(!stats.tasks) stats.tasks = [];

function saveS(){ localStorage.setItem('pm_stats', JSON.stringify(stats)); }
function beep(){ try{ const ctx=new (window.AudioContext||window.webkitAudioContext)(); for(let i=0;i<2;i++){ const o=ctx.createOscillator(),g=ctx.createGain(); o.frequency.value=700-i*150; o.type='sine'; g.gain.setValueAtTime(0.0001,ctx.currentTime+i*0.35); g.gain.exponentialRampToValueAtTime(0.3,ctx.currentTime+0.01+i*0.35); g.gain.exponentialRampToValueAtTime(0.0001,ctx.currentTime+0.3+i*0.35); o.connect(g); g.connect(ctx.destination); o.start(ctx.currentTime+i*0.35); o.stop(ctx.currentTime+0.35+i*0.35);} }catch(e){} }

function fmt(s){ const m=Math.floor(s/60), sec=s%60; return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`; }
function updRing(){ const pct = remain/DURATIONS[mode]; $('#pmRing').style.strokeDashoffset = CIRC*(1-pct); }
function updDisplay(){ $('#pmTime').textContent = fmt(remain); document.title = `🍅 ${fmt(remain)}`; updRing(); }

function setMode(m, auto=false){
  if(running){ clearInterval(interval); running=false; $('#pmStart').innerHTML='<i class="fa-solid fa-play"></i> Старт'; $('.tomato-svg').classList.remove('running'); }
  mode = m; remain = DURATIONS[m];
  const labels = {work: {s:'Время фокусировки', b:'#ef4444', e:'#dc2626'}, short:{s:'Короткий перерыв', b:'#10b981', e:'#059669'}, long:{s:'Длинный перерыв', b:'#3b82f6', e:'#2563eb'}};
  $('#pmStatus').textContent = labels[m].s;
  $('#stop1').setAttribute('stop-color', labels[m].b); $('#stop2').setAttribute('stop-color', labels[m].e);
  $('#pmBody').className = 'min-h-screen transition-all duration-500 ' + (m==='work'
    ? 'bg-gradient-to-br from-red-50 via-rose-50 to-orange-50 dark:from-slate-900 dark:via-slate-800 dark:to-red-950 text-slate-800 dark:text-white'
    : m==='short'
    ? 'bg-gradient-to-br from-emerald-50 via-teal-50 to-green-50 dark:from-slate-900 dark:via-slate-800 dark:to-emerald-950 text-slate-800 dark:text-white'
    : 'bg-gradient-to-br from-blue-50 via-sky-50 to-indigo-50 dark:from-slate-900 dark:via-slate-800 dark:to-blue-950 text-slate-800 dark:text-white');
  document.querySelectorAll('.mode-btn').forEach(b=>{
    const active = b.dataset.mode===m;
    b.className = 'mode-btn flex-1 py-2.5 rounded-xl font-bold text-sm active:scale-95 transition ' + (active
      ? 'text-white shadow-md ' + (m==='work'?'bg-gradient-to-br from-red-500 to-rose-600':m==='short'?'bg-gradient-to-br from-emerald-500 to-teal-600':'bg-gradient-to-br from-blue-500 to-indigo-600')
      : 'text-slate-600 dark:text-slate-300');
  });
  updDisplay(); renderStats();
}

function toggleRun(){
  if(running){
    clearInterval(interval); running=false;
    $('#pmStart').innerHTML='<i class="fa-solid fa-play"></i> Продолжить';
    $('.tomato-svg').classList.remove('running'); return;
  }
  running = true; $('#pmStart').innerHTML='<i class="fa-solid fa-pause"></i> Пауза';
  $('.tomato-svg').classList.add('running');
  interval = setInterval(()=>{
    remain--; updDisplay();
    if(remain<=0){ clearInterval(interval); running=false; finish(); }
  },1000);
}
function finish(){
  beep();
  if(navigator.vibrate) navigator.vibrate([300,100,300]);
  $('#pmStart').innerHTML='<i class="fa-solid fa-play"></i> Старт';
  $('.tomato-svg').classList.remove('running');
  if(mode==='work'){
    stats.rounds++; stats.total++; stats.focusMin += 25;
    if(stats.tasks[0] && !stats.tasks[0].done) stats.tasks[0].done = true;
    saveS();
    setMode(stats.rounds%4===0 ? 'long' : 'short');
  } else {
    setMode('work');
  }
  renderStats();
}
function skip(){ remain=0; updDisplay(); finish(); }
function resetAll(){ setMode(mode,true); renderStats(); }

function renderStats(){
  $('#pmRound').textContent = `${stats.rounds} / 4`;
  const dots = '';
  let html = '';
  for(let i=0;i<4;i++){
    html += `<div class="flex-1 h-3 rounded-full ${i<stats.rounds%4||(stats.rounds>=4&&stats.rounds%4===0)?'bg-gradient-to-r from-red-500 to-rose-600':'bg-slate-200 dark:bg-slate-700'} shadow-inner"></div>`;
  }
  $('#pmDots').innerHTML = html;
  $('#pmFocusMin').textContent = stats.focusMin;
  $('#pmSessions').textContent = stats.total;
  renderTasks();
}
function addTask(){
  const v=$('#pmTask').value.trim();
  if(!v) return;
  stats.tasks.unshift({id:Date.now(),text:v,done:false});
  $('#pmTask').value=''; saveS(); renderTasks();
}
function toggleT(id){ const t=stats.tasks.find(x=>x.id===id); if(t){t.done=!t.done; saveS(); renderTasks();} }
function delT(id){ stats.tasks=stats.tasks.filter(x=>x.id!==id); saveS(); renderTasks(); }
function renderTasks(){
  $('#pmTasks').innerHTML = stats.tasks.slice(0,5).map(t=>`
    <div class="flex items-center gap-2 p-3 rounded-xl bg-slate-50 dark:bg-slate-700/50">
      <input type="checkbox" ${t.done?'checked':''} onchange="toggleT(${t.id})" class="w-5 h-5 accent-red-500 rounded">
      <div class="flex-1 font-semibold text-sm ${t.done?'line-through opacity-50':''} break-words">${t.text.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}</div>
      <button onclick="delT(${t.id})" class="w-8 h-8 rounded-lg text-slate-400 hover:text-red-500 active:scale-90 transition"><i class="fa-solid fa-xmark"></i></button>
    </div>`).join('');
}
function toggleTheme(){
  document.documentElement.classList.toggle('dark');
  localStorage.setItem('pm_theme', document.documentElement.classList.contains('dark')?'dark':'light');
  $('#pmIcon').className = document.documentElement.classList.contains('dark')?'fa-solid fa-sun text-amber-400':'fa-solid fa-moon text-red-500';
}
if(localStorage.getItem('pm_theme')==='dark'){ document.documentElement.classList.add('dark'); $('#pmIcon').className='fa-solid fa-sun text-amber-400'; }
setMode('work');
</script>
</body>
</html>""")),

    ("color", ("🎨 Выбор цветов", """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#8b5cf6">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Палитра</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<script>
try { if (window.Telegram && Telegram.WebApp) { const tg = Telegram.WebApp; tg.ready(); tg.expand(); try{ tg.setHeaderColor('#8b5cf6'); tg.setBackgroundColor('#fdf4ff');}catch(e){} if(tg.HapticFeedback) window.__tgHaptic=tg.HapticFeedback; if(tg.BackButton) tg.BackButton.hide(); try{tg.MainButton.hide();}catch(e){} window.__tg=tg; } } catch(e){}
function haptic(kind='light'){ try{ const h=window.__tgHaptic||(window.__tg&&__tg.HapticFeedback); if(!h) return; if(kind==='success')h.notificationOccurred('success'); else if(kind==='error')h.notificationOccurred('error'); else if(kind==='select')h.selectionChanged(); else h.impactOccurred(kind); }catch(e){} }
</script>
<style>
body { -webkit-tap-highlight-color: transparent; }
.swatch { transition: all .2s ease; }
.swatch:hover { transform: translateY(-3px) scale(1.03); }
input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; appearance:none; width:22px; height:22px; border-radius:50%; background:white; border:3px solid #6366f1; cursor:pointer; box-shadow:0 2px 8px rgba(0,0,0,.2); }
</style>
</head>
<body class="min-h-screen bg-gradient-to-br from-violet-50 via-fuchsia-50 to-pink-50 dark:from-slate-900 dark:via-slate-800 dark:to-violet-950 text-slate-800 dark:text-white transition-colors duration-300">
<div class="max-w-xl mx-auto px-4 py-6 pb-24">
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-3xl font-black bg-gradient-to-r from-violet-600 via-fuchsia-600 to-pink-600 bg-clip-text text-transparent">Палитра</h1>
      <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">Подбирай и копируй цвета</p>
    </div>
    <button onclick="toggleTheme()" class="w-11 h-11 rounded-2xl bg-white dark:bg-slate-800 shadow-lg border border-slate-200 dark:border-slate-700 flex items-center justify-center active:scale-95 transition"><i id="clIcon" class="fa-solid fa-moon text-violet-500"></i></button>
  </div>

  <div id="mainColorCard" class="rounded-3xl p-6 mb-6 shadow-2xl border border-white/40" style="background: #6366f1;">
    <div class="flex items-center justify-between mb-16">
      <div id="mcName" class="text-white/90 text-sm font-bold opacity-0">Основной</div>
      <button onclick="randColor()" class="w-10 h-10 rounded-xl bg-white/25 backdrop-blur text-white flex items-center justify-center active:scale-90 hover:bg-white/35 transition"><i class="fa-solid fa-shuffle"></i></button>
    </div>
    <div class="text-white font-black text-5xl tracking-widest mb-4 font-mono" id="mcHEX">#6366F1</div>
    <div class="grid grid-cols-3 gap-2">
      <button onclick="copy('mcHEX')" class="py-3 rounded-2xl bg-white/20 backdrop-blur text-white text-sm font-bold hover:bg-white/30 active:scale-95 transition flex items-center justify-center gap-2"><i class="fa-regular fa-copy"></i> HEX</button>
      <button onclick="copy('mcRGB')" class="py-3 rounded-2xl bg-white/20 backdrop-blur text-white text-sm font-bold hover:bg-white/30 active:scale-95 transition flex items-center justify-center gap-2"><i class="fa-regular fa-copy"></i> RGB</button>
      <button onclick="copy('mcHSL')" class="py-3 rounded-2xl bg-white/20 backdrop-blur text-white text-sm font-bold hover:bg-white/30 active:scale-95 transition flex items-center justify-center gap-2"><i class="fa-regular fa-copy"></i> HSL</button>
    </div>
    <div id="mcRGB" class="hidden">rgb(99, 102, 241)</div>
    <div id="mcHSL" class="hidden">hsl(239, 84%, 67%)</div>
  </div>

  <div class="bg-white dark:bg-slate-800 rounded-3xl p-5 shadow-xl border border-slate-100 dark:border-slate-700 mb-6">
    <div class="font-black mb-4 text-lg">🎨 Подобрать вручную</div>
    <div class="mb-3"><label class="text-xs font-bold text-slate-500 dark:text-slate-400">HUE</label><input type="range" id="hue" min="0" max="360" value="239" oninput="fromHSV()" class="w-full h-3 rounded-full appearance-none cursor-pointer" style="background:linear-gradient(to right,red,yellow,lime,cyan,blue,magenta,red)"></div>
    <div class="mb-3"><label class="text-xs font-bold text-slate-500 dark:text-slate-400">SATURATION</label><input type="range" id="sat" min="0" max="100" value="84" oninput="fromHSV()" class="w-full h-3 rounded-full appearance-none cursor-pointer bg-slate-200 dark:bg-slate-700"></div>
    <div class="mb-4"><label class="text-xs font-bold text-slate-500 dark:text-slate-400">LIGHTNESS</label><input type="range" id="lig" min="0" max="100" value="67" oninput="fromHSV()" class="w-full h-3 rounded-full appearance-none cursor-pointer bg-slate-200 dark:bg-slate-700"></div>
    <div class="flex gap-2">
      <input id="hexInput" oninput="fromHEX()" type="text" placeholder="#RRGGBB" maxlength="7" class="flex-1 px-4 py-3 rounded-2xl bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 outline-none focus:border-violet-500 font-mono font-bold text-center">
      <button onclick="fromHEX()" class="px-5 py-3 rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-600 text-white font-bold active:scale-95 transition">OK</button>
    </div>
  </div>

  <div class="grid grid-cols-2 gap-3 mb-6">
    <button onclick="harmony('analogous')" class="py-3 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-bold shadow-sm active:scale-95 hover:shadow-md transition">🎯 Аналогия</button>
    <button onclick="harmony('complementary')" class="py-3 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-bold shadow-sm active:scale-95 hover:shadow-md transition">⚡ Комплемент</button>
    <button onclick="harmony('triadic')" class="py-3 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-bold shadow-sm active:scale-95 hover:shadow-md transition">🔺 Триада</button>
    <button onclick="harmony('split')" class="py-3 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-bold shadow-sm active:scale-95 hover:shadow-md transition">💫 Сплит</button>
  </div>

  <div class="font-black text-lg mb-3">✨ Гармония палитры</div>
  <div id="paletteRow" class="grid grid-cols-5 gap-2 mb-6"></div>

  <div class="font-black text-lg mb-3">🌈 Оттенки</div>
  <div id="shadesRow" class="grid grid-cols-5 gap-2 mb-6"></div>

  <div class="font-black text-lg mb-3">❤️ Сохранённые</div>
  <div id="savedList" class="grid grid-cols-5 gap-2 mb-4"></div>
  <button onclick="clearSaved()" class="w-full py-3 rounded-2xl text-sm font-bold text-slate-500 dark:text-slate-400 bg-white/50 dark:bg-slate-800/50 hover:bg-white dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-700 active:scale-99 transition">🗑 Очистить</button>
</div>

<div id="toast" class="fixed bottom-6 left-1/2 -translate-x-1/2 px-6 py-3 rounded-2xl bg-slate-900 text-white font-bold shadow-2xl z-50 hidden">✓ Скопировано!</div>

<script>
const $ = s => document.querySelector(s);
let saved = JSON.parse(localStorage.getItem('cl_saved')||'[]');
let curHex = '#6366F1';

function saveS(){ localStorage.setItem('cl_saved', JSON.stringify(saved.slice(0,20)); }
function toggleTheme(){
  document.documentElement.classList.toggle('dark');
  localStorage.setItem('cl_theme', document.documentElement.classList.contains('dark')?'dark':'light');
  $('#clIcon').className = document.documentElement.classList.contains('dark')?'fa-solid fa-sun text-amber-400':'fa-solid fa-moon text-violet-500';
}
if(localStorage.getItem('cl_theme')==='dark'){ document.documentElement.classList.add('dark'); $('#clIcon').className='fa-solid fa-sun text-amber-400'; }

function hexToRgb(h){ h=h.replace('#',''); return {r:parseInt(h.substr(0,2),16),g:parseInt(h.substr(2,2),16),b:parseInt(h.substr(4,2),16)}; }
function rgbToHex(r,g,b){ return '#'+[r,g,b].map(v=>Math.max(0,Math.min(255,Math.round(v))).toString(16).padStart(2,'0')).join('').toUpperCase(); }
function rgbToHsl(r,g,b){ r/=255;g/=255;b/=255; const mx=Math.max(r,g,b),mn=Math.min(r,g,b); let h,s,l=(mx+mn)/2; if(mx===mn){h=s=0;}else{ const d=mx-mn; s=l>.5?d/(2-mx-mn):d/(mx+mn); switch(mx){case r:h=((g-b)/d+(g<b?6:0))/6;break;case g:h=((b-r)/d+2)/6;break;case b:h=((r-g)/d+4)/6;break;} } return {h:Math.round(h*360),s:Math.round(s*100),l:Math.round(l*100)}; }
function hslToRgb(h,s,l){ s/=100;l/=100; const k=n=>(n+h/30)%12, a=s*Math.min(l,1-l), f=n=>l-a*Math.max(-1,Math.min(k(n)-3,Math.min(9-k(n),1)))); return {r:Math.round(255*f(0)),g:Math.round(255*f(8)),b:Math.round(255*f(4))}; }
function luminance(r,g,b){ const a=[r,g,b].map(v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)}); return .2126*a[0]+.7152*a[1]+.0722*a[2]; }
function textColor(hex){ const {r,g,b}=hexToRgb(hex); return luminance(r,g,b)>.5?'#000000':'#FFFFFF'; }

function setColor(hex, updateInputs=true){
  hex = hex.toUpperCase(); if(!/^#[0-9A-F]{6}$/.test(hex)) return;
  curHex = hex;
  const rgb = hexToRgb(hex), hsl = rgbToHsl(rgb.r,rgb.g,rgb.b);
  $('#mainColorCard').style.background = hex;
  $('#mainColorCard').style.color = textColor(hex);
  $('#mcHEX').textContent = hex; $('#mcRGB').textContent = `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
  $('#mcHSL').textContent = `hsl(${hsl.h}, ${hsl.s}%, ${hsl.l}%)`;
  $('#mcName').style.color = textColor(hex)+'CC';
  if(updateInputs){ $('#hue').value=hsl.h; $('#sat').value=hsl.s; $('#lig').value=hsl.l; $('#hexInput').value=hex; }
  renderPalette(); renderShades(); renderSaved();
}
function fromHSV(){ const {r,g,b}=hslToRgb(+$('#hue').value,+$('#sat').value,+$('#lig').value); setColor(rgbToHex(r,g,b),false); $('#hexInput').value=curHex; }
function fromHEX(){ let v=$('#hexInput').value.trim(); if(!v.startsWith('#')) v='#'+v; if(v.length===4) v='#'+v[1]+v[1]+v[2]+v[2]+v[3]+v[3]; setColor(v); }
function randColor(){ setColor('#'+Math.floor(Math.random()*16777215).toString(16).padStart(6,'0')); }

function harmony(type){
  const hsl = rgbToHsl(...Object.values(hexToRgb(curHex)));
  let hues = [];
  switch(type){
    case 'analogous': hues = [(hsl.h-30+360)%360, hsl.h, (hsl.h+30)%360]; break;
    case 'complementary': hues = [hsl.h, (hsl.h+180)%360]; break;
    case 'triadic': hues = [hsl.h, (hsl.h+120)%360, (hsl.h+240)%360]; break;
    case 'split': hues = [hsl.h, (hsl.h+150)%360, (hsl.h+210)%360]; break;
  }
  const pal = hues.map(h=>{const {r,g,b}=hslToRgb(h,hsl.s,hsl.l); return rgbToHex(r,g,b);});
  while(pal.length<5) pal.push(pal[pal.length%pal.length]);
  showPalette(pal.slice(0,5));
}
function renderPalette(){
  const hsl = rgbToHsl(...Object.values(hexToRgb(curHex)));
  const pal = [];
  for(let i=-2;i<=2;i++){ const {r,g,b}=hslToRgb((hsl.h+i*30+360)%360, hsl.s, hsl.l); pal.push(rgbToHex(r,g,b)); }
  showPalette(pal);
}
function showPalette(arr){
  $('#paletteRow').innerHTML = arr.map(c=>`
    <div onclick="saveColor('${c}')" class="swatch aspect-square rounded-2xl shadow-md cursor-pointer shadow-black/10 flex items-end p-2 relative overflow-hidden group" style="background:${c};">
      <div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 bg-black/30 transition-opacity"><i class="fa-solid fa-floppy-disk text-white text-lg"></i></div>
      <div class="font-mono font-black text-[10px] px-1.5 py-0.5 rounded" style="color:${textColor(c)};background:${textColor(c)==='#FFFFFF'?'rgba(0,0,0,.3)':'rgba(255,255,255,.3)'}">${c}</div>
    </div>`).join('');
}
function renderShades(){
  const hsl = rgbToHsl(...Object.values(hexToRgb(curHex)));
  const arr = [];
  for(let i=0;i<5;i++){ const {r,g,b}=hslToRgb(hsl.h, hsl.s, 20+i*15); arr.push(rgbToHex(r,g,b)); }
  $('#shadesRow').innerHTML = arr.map(c=>`
    <div onclick="saveColor('${c}')" class="swatch aspect-square rounded-2xl shadow-md cursor-pointer shadow-black/10 flex items-end p-2 relative overflow-hidden group" style="background:${c};">
      <div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 bg-black/30 transition-opacity"><i class="fa-solid fa-floppy-disk text-white text-lg"></i></div>
      <div class="font-mono font-black text-[10px] px-1.5 py-0.5 rounded" style="color:${textColor(c)};background:${textColor(c)==='#FFFFFF'?'rgba(0,0,0,.3)':'rgba(255,255,255,.3)'}">${c}</div>
    </div>`).join('');
}
function renderSaved(){
  if(saved.length===0){ $('#savedList').innerHTML = '<div class="col-span-5 text-center py-8 text-sm opacity-60">Нажми на цвет, чтобы сохранить</div>'; return; }
  $('#savedList').innerHTML = saved.map((c,i)=>`
    <div onclick="copy(null,'${c}')" class="swatch aspect-square rounded-2xl shadow-md cursor-pointer shadow-black/10 flex items-end p-2 relative overflow-hidden group" style="background:${c};" title="${c}">
      <button onclick="event.stopPropagation();removeSaved(${i})" class="absolute top-1 right-1 w-6 h-6 rounded-full bg-black/40 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><i class="fa-solid fa-xmark text-xs"></i></button>
      <div class="font-mono font-black text-[10px] px-1.5 py-0.5 rounded" style="color:${textColor(c)};background:${textColor(c)==='#FFFFFF'?'rgba(0,0,0,.3)':'rgba(255,255,255,.3)'}">${c}</div>
    </div>`).join('');
}
function saveColor(c){ if(!saved.includes(c)){ saved.unshift(c); if(saved.length>20) saved.pop(); saveS(); renderSaved(); toast('💾 Сохранён: '+c); } else { copy(null,c); } }
function removeSaved(i){ saved.splice(i,1); saveS(); renderSaved(); }
function clearSaved(){ saved=[]; saveS(); renderSaved(); }
function copy(id, val=null){ const txt = val || $(id)?.textContent || ''; if(!txt) return; navigator.clipboard.writeText(txt).then(()=>toast('✓ '+txt)); }
function toast(t){ const el=$('#toast'); el.textContent=t; el.classList.remove('hidden'); setTimeout(()=>el.classList.add('hidden'),1400); }
setColor('#6366F1');
</script>
</body>
</html>""")),
])


def _kb_main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎨 Посмотреть шаблоны", callback_data="tpl:cat:menu")],
        [
            InlineKeyboardButton(text="📝 To-Do", callback_data="ready:todo"),
            InlineKeyboardButton(text="🧮 Калькулятор", callback_data="ready:calc"),
            InlineKeyboardButton(text="⏱️ Таймер", callback_data="ready:timer"),
        ],
        [
            InlineKeyboardButton(text="🌤️ Погода", callback_data="ready:weather"),
            InlineKeyboardButton(text="📖 Заметки", callback_data="ready:notes"),
        ],
        [
            InlineKeyboardButton(text="🍅 Pomodoro", callback_data="ready:pomodoro"),
            InlineKeyboardButton(text="🎨 Палитра", callback_data="ready:color"),
        ],
        [
            InlineKeyboardButton(text="📊 Моя статистика", callback_data="cmd:stats"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="cmd:help"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_categories() -> InlineKeyboardMarkup:
    rows = []
    cats = list(TEMPLATE_CATEGORIES.keys())
    for i in range(0, len(cats), 2):
        row = []
        for c in cats[i:i+2]:
            row.append(InlineKeyboardButton(text=c, callback_data=f"tpl:cat:{c}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="cmd:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_category_items(category_name: str) -> InlineKeyboardMarkup:
    items = TEMPLATE_CATEGORIES.get(category_name, [])
    rows = []
    for idx, (title, _prompt) in enumerate(items):
        rows.append([InlineKeyboardButton(
            text=f"• {title}",
            callback_data=f"tpl:run:{category_name}:{idx}",
        )])
    rows.append([
        InlineKeyboardButton(text="🎯 Все категории", callback_data="tpl:cat:menu"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="cmd:start"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


START_TEXT = (
    "👋 Привет! Я <b>CarBerry — AI</b>, который умеет генерировать "
    "полноценные веб-сайты и мини-приложения по твоему описанию.\n\n"
    "⚡ <b>Готовые приложения (запуск мгновенно):</b>\n"
    "  • 📝 <b>To-Do</b> — управление задачами с сохранением\n"
    "  • 🧮 <b>Калькулятор</b> — научный, с тригонометрией\n"
    "  • ⏱️ <b>Таймер</b> — круговой прогресс, звук, вибрация\n"
    "  • 🌤️ <b>Погода</b> — реальные данные по городу, прогноз 5 дней\n"
    "  • 📖 <b>Заметки</b> — цвета, поиск, сохранение в браузере\n"
    "  • 🍅 <b>Pomodoro</b> — фокус 25/5, статистика, задачи\n"
    "  • 🎨 <b>Палитра</b> — подбор цветов, HEX/RGB/HSL, гармонии\n\n"
    "🤖 <b>Что я ещё умею:</b>\n"
    "  • Принимаю текстовое описание идеи\n"
    "  • Создаю <b>один готовый HTML-файл</b> с Tailwind CSS\n"
    "  • Даю кнопку <b>Mini App</b> — открыть сразу внутри Telegram\n"
    "  • Прикрепляю файл с кодом для скачивания\n\n"
    "🚀 <b>Как начать:</b>\n"
    "  1. Нажми одну из кнопок выше — или напиши идею (например «сайт пиццерии»)\n"
    "  2. Если ИИ — подожди 10–30 секунд\n"
    "  3. Жми «Открыть Mini App» и проверяй результат\n\n"
    "💡 Совет: чем подробнее описание — тем лучше результат ИИ. Цвета, стиль, блоки."
)


HELP_TEXT = (
    "❓ <b>Справка и часто задаваемые вопросы</b>\n\n"
    "📌 <b>Основные команды:</b>\n"
    "  • <code>/start</code> — Приветствие и главное меню\n"
    "  • <code>/templates</code> — Каталог готовых шаблонов\n"
    "  • <code>/stats</code> — Твоя личная статистика\n"
    "  • <code>/help</code> — Этот раздел с советами\n\n"
    "⚡ <b>Готовые приложения (мгновенный запуск, БЕЗ ИИ):</b>\n"
    "  Нажми кнопку в меню /start или просто напиши в чат:\n"
    "  • 📝 <b>ту-ду / todo / задачи</b> — список дел с сохранением\n"
    "  • 🧮 <b>калькулятор / calc</b> — научный с тригонометрией\n"
    "  • ⏱️ <b>таймер / timer</b> — с прогрессом и звуком\n"
    "  • 🌤️ <b>погода / weather</b> — реальный прогноз по городу\n"
    "  • 📖 <b>заметки / notes</b> — цвета, поиск, хранение\n"
    "  • 🍅 <b>помидор / pomodoro</b> — фокус 25/5 + статистика\n"
    "  • 🎨 <b>цвета / palette / color</b> — подбор HEX/RGB/HSL\n\n"
    "🎨 <b>Как правильно формулировать запросы:</b>\n"
    "  ✅ Хорошо:\n"
    "    «Лендинг для онлайн-школы английского с тарифами, отзывами, блоком учителей и формой записи. "
    "Тёмная тема, зелёные акценты.»\n\n"
    "  ❌ Плохо:\n"
    "    «сделай сайт про школу»\n\n"
    "⚡ <b>Советы по скорости и качеству:</b>\n"
    "  • Между запросами пауза <b>10 сек</b> — защищаем API от перегрева\n"
    "  • Если ИИ пишет что модель не работает — не волнуйся, бот автоматически подбирает следующую\n"
    "  • Код живёт в кэше ~5 минут, потом ссылка на preview истекает — скачай файл если нужно сохранить\n"
    "  • Пробуй разные вариации одного и того же запроса — результат каждый раз получается уникальным\n\n"
    "🔧 <b>Если что-то сломалось:</b>\n"
    "  1. Перезапусти бота командой <code>/start</code>\n"
    "  2. Если ошибка API с текстом — подожди 1–2 минуты\n"
    "  3. Если кнопка Mini App не открывается — убедись, что переменная окружения "
    "<code>WEBAPP_URL</code> задана правильно (Railway автоматически пробрасывает HTTPS)"
)


@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    first_name = message.from_user.first_name if message.from_user else None
    _ensure_user_stats(user_id, username, first_name)
    await message.answer(START_TEXT, parse_mode="HTML", reply_markup=_kb_main_menu(), disable_web_page_preview=True)


@dp.message(Command("templates"))
async def templates_cmd(message: types.Message):
    count_cats = len(TEMPLATE_CATEGORIES)
    count_items = sum(len(v) for v in TEMPLATE_CATEGORIES.values())
    text = (
        "🎨 <b>Каталог готовых шаблонов</b>\n\n"
        f"Выбери категорию — всего <b>{count_cats}</b> категорий и <b>{count_items}</b> шаблонов.\n\n"
        "Нажимай на любую карточку — я сразу сгенерирую готовый сайт по этому шаблону."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_kb_categories(), disable_web_page_preview=True)


@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    first_name = message.from_user.first_name if message.from_user else None
    s = _ensure_user_stats(user_id, username, first_name)

    top_models = ""
    if s["used_models"]:
        items = sorted(s["used_models"].items(), key=lambda kv: -kv[1])[:5]
        parts = []
        for m, c in items:
            parts.append(f"   • <code>{_safe_html(m[:35])}</code> — {c} раз")
        top_models = "\n" + "\n".join(parts)
    else:
        top_models = "\n   • (ещё нет данных)"

    total_all = s["successful_apps"] + s["failed_requests"]
    text = (
        "📊 <b>Твоя личная статистика</b>\n\n"
        f"👤 Пользователь: <b>{_safe_html(s['first_name'] or username or 'Гость')}</b>\n"
        f"📅 Первый заход: <code>{_safe_html(s['first_seen'])}</code>\n"
        f"🕒 Последняя активность: <code>{_safe_html(s['last_seen'])}</code>\n\n"
        f"📝 Всего запросов к ИИ: <b>{s['total_requests']}</b>\n"
        f"✅ Успешно создано сайтов: <b>{s['successful_apps']}</b>\n"
        f"❌ Неудачных попыток: <b>{s['failed_requests']}</b>\n"
        f"🎯 Процент успеха: <b>{_stat_rate(s)}</b>\n\n"
        f"🤖 Любимые модели (TOP 5):{top_models}"
    )

    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@dp.callback_query(F.data.startswith("cmd:"))
async def cb_cmd_shortcut(query: types.CallbackQuery):
    cmd = query.data[len("cmd:"):]
    try:
        if cmd == "start":
            user_id = query.from_user.id
            username = query.from_user.username
            first_name = query.from_user.first_name
            _ensure_user_stats(user_id, username, first_name)
            await query.message.edit_text(START_TEXT, parse_mode="HTML", reply_markup=_kb_main_menu(), disable_web_page_preview=True)
        elif cmd == "stats":
            user_id = query.from_user.id
            username = query.from_user.username
            first_name = query.from_user.first_name
            s = _ensure_user_stats(user_id, username, first_name)
            top_models = ""
            if s["used_models"]:
                items = sorted(s["used_models"].items(), key=lambda kv: -kv[1])[:5]
                parts = []
                for m, c in items:
                    parts.append(f"   • <code>{_safe_html(m[:35])}</code> — {c} раз")
                top_models = "\n" + "\n".join(parts)
            else:
                top_models = "\n   • (ещё нет данных)"
            text = (
                "📊 <b>Твоя личная статистика</b>\n\n"
                f"👤 Пользователь: <b>{_safe_html(s['first_name'] or username or 'Гость')}</b>\n"
                f"📅 Первый заход: <code>{_safe_html(s['first_seen'])}</code>\n"
                f"🕒 Последняя активность: <code>{_safe_html(s['last_seen'])}</code>\n\n"
                f"📝 Всего запросов к ИИ: <b>{s['total_requests']}</b>\n"
                f"✅ Успешно создано сайтов: <b>{s['successful_apps']}</b>\n"
                f"❌ Неудачных попыток: <b>{s['failed_requests']}</b>\n"
                f"🎯 Процент успеха: <b>{_stat_rate(s)}</b>\n\n"
                f"🤖 Любимые модели (TOP 5):{top_models}"
            )
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="cmd:start")],
            ])
            await query.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb, disable_web_page_preview=True)
        elif cmd == "help":
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="cmd:start")],
            ])
            await query.message.edit_text(HELP_TEXT, parse_mode="HTML", reply_markup=back_kb, disable_web_page_preview=True)
    except Exception as e:
        logger.debug("Не удалось отредактировать сообщение (cmd %s): %s", cmd, e)
    try:
        await query.answer()
    except Exception:
        pass


async def serve_ready_template(message_obj: types.Message | types.CallbackQuery, template_id: str):
    """Выдаёт готовый HTML-шаблон пользователю без AI-генерации."""
    from_user = None
    chat_id: int | None = None
    if isinstance(message_obj, types.Message):
        from_user = message_obj.from_user
        chat_id = message_obj.chat.id
    elif isinstance(message_obj, types.CallbackQuery):
        from_user = message_obj.from_user
        chat_id = message_obj.message.chat.id if message_obj.message else None

    user_id = from_user.id if from_user else 0
    username = from_user.username if from_user else None
    first_name = from_user.first_name if from_user else None

    template = READY_APP_TEMPLATES.get(template_id)
    if not template:
        try:
            if isinstance(message_obj, types.CallbackQuery):
                await message_obj.answer("❌ Шаблон не найден", show_alert=True)
            else:
                await message_obj.answer("❌ Шаблон не найден")
        except Exception:
            pass
        return

    title, html_code = template
    _stat_inc_request(user_id, username, first_name)

    app_id = template_id
    PERMANENT_READY_APPS[template_id] = html_code
    try:
        GENERATED_APPS.put(f"ready__{template_id}", html_code)
        GENERATED_APPS.put(f"ready_{template_id}", html_code)
        GENERATED_APPS.put(template_id, html_code)
    except Exception:
        pass
    _stat_inc_success(user_id, "ready-template")

    caption = (
        f"✅ <b>{_safe_html(title)}</b> — готово!\n\n"
        "Жми кнопку <b>🚀 Открыть Mini App</b> — приложение откроется ПОЛНОСТЬЮ ВНУТРИ Telegram WebView (как родное окно, без внешнего браузера).\n"
        "• Открывается мгновенно — БЕЗ ожидания ИИ\n"
        "• Все данные (заметки/задачи/цвета/таймеры) сохраняются на твоём устройстве (localStorage)\n"
        "• URL вечный — /app/{template_id} — кэш шаблонов НИКОГДА не протухает"
    )

    sep_url = "&" if "?" in PUBLIC_URL else "?"
    web_app_url = f"{PUBLIC_URL}/app/{template_id}{sep_url}utm_source=tg_mini_app&tpl={template_id}"
    browser_url = f"{PUBLIC_URL}/app/{template_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 Открыть Mini App",
            web_app=WebAppInfo(url=web_app_url),
        )],
        [InlineKeyboardButton(text="🌐 Открыть в браузере", url=browser_url)],
    ])

    file_bytes = html_code.encode("utf-8")
    safe_title = re.sub(r"[^\w\-\sа-яА-ЯёЁ]", "", title, flags=re.UNICODE).strip() or template_id
    safe_title = safe_title.replace(" ", "_")[:40]
    file = types.BufferedInputFile(file_bytes, filename=f"{safe_title}_{app_id}.html")

    try:
        if isinstance(message_obj, types.CallbackQuery) and message_obj.message:
            await message_obj.message.delete()
    except Exception:
        pass

    try:
        if isinstance(message_obj, types.CallbackQuery):
            await message_obj.answer(f"✅ {title[:40]}", show_alert=False)
    except Exception:
        pass

    if chat_id is not None:
        await bot.send_document(
            chat_id=chat_id,
            document=file,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_content_type_detection=True,
        )


@dp.callback_query(F.data.startswith("ready:"))
async def cb_ready_templates(query: types.CallbackQuery):
    template_id = query.data[len("ready:"):]
    await serve_ready_template(query, template_id)


@dp.callback_query(F.data.startswith("tpl:"))
async def cb_templates(query: types.CallbackQuery):
    data = query.data
    parts = data.split(":", 3)
    # parts[0] = "tpl", parts[1] = "cat" or "run"
    try:
        if len(parts) >= 3 and parts[1] == "cat":
            cat = parts[2]
            if cat == "menu":
                count_cats = len(TEMPLATE_CATEGORIES)
                count_items = sum(len(v) for v in TEMPLATE_CATEGORIES.values())
                text = (
                    "🎨 <b>Каталог готовых шаблонов</b>\n\n"
                    f"Всего <b>{count_cats}</b> категорий и <b>{count_items}</b> шаблонов.\n\n"
                    "Выбери категорию:"
                )
                await query.message.edit_text(text, parse_mode="HTML", reply_markup=_kb_categories(), disable_web_page_preview=True)
            else:
                items = TEMPLATE_CATEGORIES.get(cat, [])
                text = (
                    f"📁 <b>Категория: {_safe_html(cat)}</b>\n\n"
                    f"В этой категории <b>{len(items)}</b> шаблонов. Жми на любой — я запущу генерацию:\n"
                )
                for i, (t, _) in enumerate(items, 1):
                    text += f"\n   {i}. {_safe_html(t)}"
                await query.message.edit_text(text, parse_mode="HTML", reply_markup=_kb_category_items(cat), disable_web_page_preview=True)
        elif len(parts) >= 4 and parts[1] == "run":
            cat_name = parts[2]
            try:
                idx = int(parts[3])
            except ValueError:
                idx = -1
            items = TEMPLATE_CATEGORIES.get(cat_name, [])
            if idx < 0 or idx >= len(items):
                try:
                    await query.answer("❌ Шаблон не найден")
                except Exception:
                    pass
                return
            title, prompt = items[idx]
            try:
                await query.message.delete()
            except Exception:
                pass
            try:
                await query.answer(f"✅ Запускаю: {title[:40]}")
            except Exception:
                pass
            fake = types.Message.model_construct(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=query.message.chat,
                from_user=query.from_user,
                text=prompt,
            )
            await generate_app(fake)
            return
    except Exception as e:
        logger.debug("Не удалось обработать callback tpl (%s): %s", data, e)
    try:
        await query.answer()
    except Exception:
        pass


def _strip_code_blocks(text: str) -> str:
    text = text.strip()
    pattern = re.compile(r"^```(?:html)?\s*\n(.*?)\n```$", re.DOTALL | re.IGNORECASE)
    match = pattern.match(text)
    if match:
        return match.group(1).strip()
    triple = text.find("```")
    if triple != -1:
        after = text.find("\n", triple)
        if after != -1:
            end = text.find("```", after)
            if end != -1:
                return text[after + 1 : end].strip()
    return text


def _safe_html(s: str) -> str:
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s


def _suggest_models_line() -> str:
    model_list = _dedupe_models(FALLBACK_MODELS)
    bullets = "\n".join(
        f"   • <code>{_safe_html(m)}</code>" for m in model_list
    )
    return (
        "Как починить:\n"
        "1. Открой файл <code>.env</code> в корне проекта\n"
        "2. Найди строку <code>AI_MODEL=</code> и замени её на ОДНУ из:\n"
        f"{bullets}\n"
        "3. Сохрани файл и перезапусти бота (Ctrl+C → запустить снова).\n\n"
        "💡 Совет: бот сам перебирает ВСЕ эти модели по очереди и берёт первую рабочую — "
        "попробуй просто написать новый запрос перед тем как править .env."
    )


def _format_ai_error(exc: BaseException) -> str:
    status_code: int | None = None
    resp = getattr(exc, "response", None)
    if resp is not None:
        status_code = getattr(resp, "status_code", None)

    ai_code = getattr(exc, "code", None)
    if isinstance(ai_code, str) and not ai_code:
        ai_code = None
    if ai_code is None:
        body = getattr(resp, "json", None) if resp is not None else None
        if callable(body):
            try:
                payload = body()
                err = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(err, dict):
                    ai_code = err.get("code") or ai_code
            except Exception:
                pass

    ai_message: str | None = getattr(exc, "message", None)
    if not isinstance(ai_message, str) or not ai_message:
        ai_message = None

    raw_text = str(exc)
    text_low = raw_text.lower()

    if (
        status_code == 401
        or ai_code == "invalid_api_key"
        or "unauthorized" in text_low
        or "invalid api key" in text_low
    ):
        return (
            "❌ Ошибка Groq API: неверный <b>GROQ_API_KEY</b>.\n\n"
            "Как исправить:\n"
            "1. Открой <a href=\"https://console.groq.com/keys\">console.groq.com/keys</a>\n"
            "2. Нажми <b>Create API Key</b>, введи имя, скопируй ключ\n"
            "3. В файле <code>.env</code> вставь его в строку <code>GROQ_API_KEY=</code>\n"
            "4. Перезапусти бота."
        )

    model_invalid = (
        status_code == 404
        or status_code == 400
        or (isinstance(ai_code, str) and "model" in ai_code.lower())
        or "not found" in text_low
        or "decommissioned" in text_low
        or "no longer supported" in text_low
        or "invalid_request_error" in text_low
    )
    if model_invalid:
        hint = ""
        if ai_message:
            hint = f"\nСообщение Groq: {_safe_html(ai_message[:200])}\n"
        elif status_code == 400:
            m = re.search(r"The model `([^`]+)`", raw_text)
            if m:
                hint = f"\nМодель <code>{_safe_html(m.group(1))}</code> отключена у Groq.\n"
        return (
            "❌ Ошибка Groq API: модель <code>"
            + _safe_html(AI_MODEL)
            + "</code> не поддерживается (отключена / переименована / не существует)."
            + hint
            + "\n\n"
            + _suggest_models_line()
        )

    if (
        status_code == 429
        or (isinstance(ai_code, str) and "rate" in ai_code.lower())
        or "rate limit" in text_low
        or "quota" in text_low
        or "requests per minute" in text_low
        or "requests per day" in text_low
    ):
        return (
            "⏳ Ошибка Groq API: исчерпан лимит запросов.\n\n"
            "Что делать:\n"
            "• Подожди 1-2 минуты и попробуй снова\n"
            "• Или в <a href=\"https://console.groq.com/keys\">console.groq.com</a> создай второй API ключ "
            "и подставь его в <code>GROQ_API_KEY=</code> в файле <code>.env</code>"
        )

    if status_code in (500, 502, 503, 504) or "server error" in text_low or "bad gateway" in text_low:
        return (
            "🔧 Ошибка на стороне Groq (упал их сервер).\n"
            "Ничего исправлять не нужно — просто попробуй снова через 2-5 минут. "
            "Статус: <a href=\"https://status.groq.com\">status.groq.com</a>"
        )

    if (
        "connect" in text_low
        or "network" in text_low
        or "serverdisconnected" in text_low
        or "temporary failure" in text_low
        or "name or service not known" in text_low
    ):
        return "📡 Нет подключения к Groq API — проверь интернет, WiFi/VPN и попробуй снова."

    if isinstance(exc, AllModelsFailedError):
        return (
            "💥 <b>Ни одна из моделей Groq не сработала</b>.\n\n"
            "Что это значит:\n"
            "• Бот перепробовал все 6 моделей по очереди — каждая вернула ошибку.\n"
            "• Самые частые причины:\n"
            "  1. Неверный <code>GROQ_API_KEY</code> (использовали не тот ключ / его удалили)\n"
            "  2. У ключа закончились бесплатные кредиты / rate limit на аккаунт целиком\n"
            "  3. У тебя нет интернета или провайдер блокирует доступ к api.groq.com\n"
            "  4. У Groq глобальный даунтайм на всех моделях\n\n"
            "Как проверить:\n"
            "1. Открой <a href=\"https://console.groq.com/keys\">console.groq.com/keys</a> — там ли твой ключ?\n"
            "2. Открой <a href=\"https://status.groq.com\">status.groq.com</a> — жив ли сервис?\n"
            "3. Попробуй создать НОВЫЙ ключ и вставить в <code>.env</code> строку <code>GROQ_API_KEY=</code>.\n\n"
            f"Техническая причина: {_safe_html(str(exc)[:200])}"
        )

    if "ai api вернул пустой ответ" in text_low or "вернул код не в том формате" in text_low:
        return (
            "🤖 AI сгенерировал ответ не в том формате (вернул текст вместо HTML).\n"
            "Попробуй переформулировать запрос: опиши, что должно быть на странице, "
            "какие секции, кнопки, цвета. Чем подробнее — тем выше шанс получить чистый код."
        )

    detail = ai_message if ai_message else raw_text
    if len(detail) > 220:
        detail = detail[:217] + "..."
    detail_html = _safe_html(detail)

    return (
        "❌ Не удалось сгенерировать приложение.\n"
        f"Причина: {detail_html}\n\n"
        "Если повторяется — проверь файл <code>.env</code>:\n"
        "• <code>GROQ_API_KEY=</code> должен быть валидным ключом с console.groq.com\n"
        "• <code>AI_MODEL=</code> должен быть из списка: llama-3.1-70b-versatile / llama-3.1-8b-instant / mixtral-8x7b-32768 / llama3-70b-8192"
    )


def _cleanup_rate_users(now: float):
    if len(USER_LAST_REQUEST) > MAX_RATE_USERS:
        threshold = now - RATE_LIMIT_SECONDS * 2
        stale = [u for u, ts in USER_LAST_REQUEST.items() if ts < threshold]
        for u in stale:
            del USER_LAST_REQUEST[u]
        if len(USER_LAST_REQUEST) > MAX_RATE_USERS:
            users = sorted(USER_LAST_REQUEST.keys())
            for u in users[: len(users) - MAX_RATE_USERS]:
                del USER_LAST_REQUEST[u]


def _short_error(exc: BaseException) -> str:
    sc = getattr(getattr(exc, "response", None), "status_code", None)
    code = getattr(exc, "code", None)
    msg = getattr(exc, "message", None)
    if isinstance(msg, str) and msg:
        head = msg[:90].replace("\n", " ")
    else:
        head = str(exc)[:100].replace("\n", " ")
    parts = []
    if sc is not None:
        parts.append(f"HTTP {sc}")
    if isinstance(code, str) and code:
        parts.append(f"code={code}")
    parts.append(head)
    return " | ".join(parts)


def _is_model_error(exc: BaseException) -> bool:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    code = getattr(exc, "code", None)
    text = str(exc).lower()
    if status_code in (400, 404):
        if status_code == 400 and (
            isinstance(code, str) and ("invalid_api" in code.lower() or "auth" in code.lower())
        ):
            return False
        return True
    if isinstance(code, str):
        c = code.lower()
        if "invalid_api_key" in c or "unauthorized" in c or "auth" in c:
            return False
        if "model" in c or "invalid" in c:
            return True
    for bad_stop in ("invalid_api_key", "unauthorized", "quota", "rate limit"):
        if bad_stop in text:
            return False
    return any(k in text for k in ("model", "decommissioned", "not found", "no longer supported", "invalid_request_error"))


class AllModelsFailedError(Exception):
    pass


async def _chat_with_model_fallback(messages: list[dict]) -> tuple[str, str]:
    model_list = _dedupe_models(FALLBACK_MODELS)
    if not model_list:
        raise RuntimeError("Список моделей пуст — задайте AI_MODEL в .env")

    print(f"\n{'='*70}\n  🤖 [FALLBACK] Начинаю перебор {len(model_list)} моделей...\n{'='*70}")
    last_exc: BaseException | None = None
    for idx, model in enumerate(model_list, start=1):
        tag = f"[{idx}/{len(model_list)}]"
        print(f"  ⏳ {tag} Пробую модель: {model}")
        try:
            resp = await ai_client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=45.0,
                max_tokens=8192,
            )
            content = resp.choices[0].message.content
            if not content or not content.strip():
                raise RuntimeError(f"Модель {model} вернула пустой ответ")
            print(f"  ✅ {tag} УСПЕХ — модель {model} сработала. Ответ {len(content)} символов.")
            if idx > 1:
                logger.info("Fallback сработал — использована модель %s (первые %s не подошли)", model, idx - 1)
            print("=" * 70 + "\n")
            return content, model
        except Exception as e:
            last_exc = e
            short = _short_error(e)
            is_model_bad = _is_model_error(e)
            if is_model_bad:
                print(f"  🚫 {tag} Модель {model} — ОТКЛЮЧЕНА/НЕ СУЩЕСТВУЕТ. {short}")
                logger.warning("Модель %s не подходит — пробую следующую. Ошибка: %s", model, e)
                continue
            print(f"  💥 {tag} Модель {model} — СТОП-ОШИБКА (не перебираю дальше). {short}")
            logger.exception("Ошибка при запросе к модели %s (не связана с моделью) — останавливаю fallback", model)
            print("=" * 70 + "\n")
            raise

    print(f"  ❌ ВСЕ {len(model_list)} МОДЕЛЕЙ ОТВЕРГНУТЫ — fallback провалился.\n" + "=" * 70 + "\n")
    assert last_exc is not None
    tried = ", ".join(_safe_html(m) for m in model_list)
    raise AllModelsFailedError(
        f"Ни одна из {len(model_list)} моделей не сработала у Groq. Пробовали: {tried}. "
        f"Последняя ошибка — {str(last_exc)[:180]}"
    ) from last_exc


async def _fetch_groq_chat_models_online() -> list[str]:
    """Забираем живой список моделей напрямую с Groq /v1/models. Работает только локально (песочница блокирует)."""
    try:
        import httpx  # если вдруг есть
    except Exception:
        try:
            import aiohttp  # type: ignore
        except Exception:
            aiohttp = None  # type: ignore
            httpx = None  # fallback на urllib ниже

    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    raw: bytes | None = None
    try:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=18.0) as client:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    raw = r.read()
        except Exception:
            raw = None

        if raw is None:
            from urllib.request import Request, urlopen
            req = Request(url, headers=headers)
            try:
                with urlopen(req, timeout=20) as resp:
                    raw = resp.read()
            except Exception:
                raw = None

        if raw is None:
            return []
        import json as _json
        payload = _json.loads(raw.decode("utf-8"))
        data = payload.get("data", []) if isinstance(payload, dict) else []
        all_ids = [m.get("id") for m in data if isinstance(m, dict)]
        chat_ids: list[str] = []
        for mid in all_ids:
            if not isinstance(mid, str) or not mid.strip():
                continue
            s = mid.lower()
            if any(k in s for k in ("whisper", "embed", "speech", "tts", "audio", "vision", "prompt-guard", "guard-", "safeguard")):
                continue
            chat_ids.append(mid)
        def _rank_score(mid: str) -> tuple[int, int, str]:
            s = mid.lower()
            score = 100
            if any(k in s for k in ("70b", "120b", "72b", "405b", "671b", "maverick")):
                score += 40
            if "versatile" in s or "gpt-oss-120" in s:
                score += 30
            if "scout" in s:
                score += 25
            if "qwen3-32" in s or "compound" in s:
                score += 15
            if "8b-instant" in s or "instant" in s:
                score += 10
            if any(k in s for k in ("gpt-oss-20", "qwen3.8", "27b", "m2.7", "kimi")):
                score += 5
            if mid.startswith("meta-llama/") or mid.startswith("openai/"):
                score += 1  # слегка поднимаем
            return (-score, -len(mid), mid)
        return sorted(set(chat_ids), key=_rank_score)
    except Exception as e:
        logger.debug("Не удалось забрать /v1/models с Groq (ok, fallback остаётся): %s", e)
        return []


def _merge_models(user_and_hardcoded: list[str], online: list[str]) -> list[str]:
    """Онлайн модели подмешиваем ПОСЛЕ пользовательской + hardcoded production, чтобы не сломать ожидаемый приоритет."""
    seen: set[str] = set()
    out: list[str] = []
    for m in user_and_hardcoded:
        key = (m or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(m.strip())
    for m in online:
        key = (m or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(m.strip())
    return out


async def _diagnose_all_models_on_startup():
    sep = "=" * 70
    print("\n" + sep)
    print("  🔍 [СТАРТ] Предстартовая проверка моделей Groq API")
    print(sep)

    models = _dedupe_models(FALLBACK_MODELS)

    if not GROQ_API_KEY or not GROQ_API_KEY.strip() or "xxx" in GROQ_API_KEY.lower() or "your" in GROQ_API_KEY.lower():
        print("  ❌ GROQ_API_KEY в .env — ПУСТОЙ / НЕ ЗАДАН / ПЛАЦХОЛДЕР!")
        print("     ➡️  Иди на https://console.groq.com/keys, Create API Key, вставь в .env:")
        print("        GROQ_API_KEY=gsk_.........")
        print(sep + "\n")
        return

    print(f"  🗝  Ключ GROQ_API_KEY: задан ({len(GROQ_API_KEY)} символов)")  # Не печатаем фрагмент в лог
    print(f"  📋 Всего моделей в списке: {len(models)}")
    print(sep)

    test_messages = [{"role": "user", "content": "Напиши ровно одно слово: OK"}]
    ok, fail = 0, 0
    for idx, model in enumerate(models, start=1):
        tag = f"[{idx:>2}/{len(models)}]"
        try:
            resp = await ai_client.chat.completions.create(
                model=model,
                messages=test_messages,
                timeout=15.0,
                max_tokens=8,
            )
            txt = (resp.choices[0].message.content or "").strip() or "<пусто>"
            print(f"  🟢 {tag} {model:<48s} ОК ({txt[:30]})")
            ok += 1
        except Exception as e:
            fail += 1
            short = _short_error(e)
            print(f"  🔴 {tag} {model:<48s} FAIL — {short}")

    print(sep)
    if ok == 0:
        print("  💀 ВСЕ МОДЕЛИ ОТВАЛИЛИСЬ.")
        print("     Частые причины (в порядке вероятности):")
        print("      1. GROQ_API_KEY неверный / просроченный / удалённый — возьми новый с console.groq.com/keys")
        print("      2. У ключа закончились бесплатные кредиты / rate limit на весь аккаунт")
        print("      3. Нет интернета / антивирус / VPN / провайдер блокирует api.groq.com (проверь через браузер)")
        print("      4. У Groq даунтайм — проверяй https://status.groq.com")
    else:
        print(f"  🎉 РАБОТАЕТ: {ok} моделей | ОТВАЛИЛИСЬ: {fail} моделей.")
        print("     Бот будет использовать первую рабочую из списка.")
    print(sep + "\n")


READY_APP_KEYWORDS: "dict[str, tuple[str, ...]]" = {
    "todo": ("ту-ду", "tudu", "todo", "задач", "список дел", "дела", "todos"),
    "calc": ("калькулятор", "calculator", "calc", "считалк", "посчитать", "математик"),
    "timer": ("таймер", "timer", "секундо", "секундомер", "засеч", "отсчёт"),
    "weather": ("погода", "weather", "температур", "прогноз", "дождь", "ветер"),
    "notes": ("заметк", "note", "notes", "записк", "notepad", "блокнот"),
    "pomodoro": ("помидор", "pomodoro", "помидорка", "фокус", "фокусировк", "25 минут"),
    "color": ("цвет", "color", "palette", "палитр", "hex", "rgb", "hsl", "подбор цвет"),
}


def _detect_ready_template(text: str) -> str | None:
    if not text:
        return None
    t = text.lower().replace("ё", "е").strip()
    # Если запрос явно про сайт/лендинг/страницу — не перехватываем готовыми шаблонами
    _site_words = ("сайт", "лендинг", "страниц", "landing", "website", "web", "дизайн сайт", "главная страниц")
    if any(w in t for w in _site_words):
        return None
    # Только короткие запросы (до 80 символов) можем матчить как команды
    if len(t) > 80:
        return None
    for template_id, keywords in READY_APP_KEYWORDS.items():
        for kw in keywords:
            kw_norm = kw.lower().replace("ё", "е")
            # Требуем точное совпадение слова (не substring любого слова), чтобы "сделай" не ловило "дела"
            if re.search(r'\b' + re.escape(kw_norm) + r'\b', t, flags=re.UNICODE):
                return template_id
    return None


@dp.message(F.text & ~F.text.startswith("/"))
async def generate_app(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    first_name = message.from_user.first_name if message.from_user else None

    tpl_id = _detect_ready_template(message.text or "")
    if tpl_id and tpl_id in READY_APP_TEMPLATES:
        await serve_ready_template(message, tpl_id)
        return

    now = time.time()
    _cleanup_rate_users(now)
    last_ts = USER_LAST_REQUEST.get(user_id, 0)
    if now - last_ts < RATE_LIMIT_SECONDS:
        wait = RATE_LIMIT_SECONDS - int(now - last_ts)
        await message.answer(
            f"⏳ Пожалуйста, подожди ещё {wait} сек. перед следующим запросом — "
            "защищаем твоё железо и API от перегрузки."
        )
        return
    USER_LAST_REQUEST[user_id] = now
    _stat_inc_request(user_id, username, first_name)

    user_request = (message.text or "").strip()

    # ── Detect edit requests for existing sites ───────────────────────────────
    last_site_id = USER_LAST_SITE.get(user_id, "")
    if (
        last_site_id
        and last_site_id in SITE_PLANS
        and _detect_edit_intent(user_request)
        and not any(kw in user_request.lower() for kw in ("сайт для", "сделай сайт", "новый сайт", "создай сайт", "landing for", "make a site"))
    ):
        await _edit_website(message, user_request, user_id, last_site_id)
        return

    # ── Detect website requests → use Site Engine ────────────────────────────
    _website_keywords = (
        "сайт", "лендинг", "страниц", "landing", "website", "web",
        "барбершоп", "ресторан", "кафе", "портфолио", "portfolio",
        "gym", "фитнес", "startup", "стартап", "агентство", "agency",
        "магазин", "shop", "фото", "photo", "студия", "studio"
    )
    use_site_engine = _SITE_ENGINE_OK and any(
        kw in user_request.lower() for kw in _website_keywords
    )

    if use_site_engine:
        await _generate_website(message, user_request, user_id, username, first_name)
    else:
        await _generate_app_legacy(message, user_request, user_id, username, first_name)


async def _generate_website(
    message: types.Message,
    user_request: str,
    user_id: int,
    username: str | None,
    first_name: str | None,
):
    """NEW FLOW: user → AI planner → JSON plan → site_engine → HTML"""
    status_msg = await message.answer("🎨 Планирую дизайн сайта...")

    # ── Step 1: AI produces a JSON plan ──────────────────────────────────────
    try:
        system_prompt = get_system_prompt()
    except Exception:
        system_prompt = (
            "You are a website design planner. Return ONLY valid JSON with "
            "site_type, theme, font_pair, sections (array of {type,variant}), and content object. "
            "No HTML, no markdown, no code fences."
        )

    ai_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request},
    ]

    raw_json: str = ""
    used_model: str = ""
    plan: dict = {}

    MAX_PLAN_RETRIES = 2
    for attempt in range(MAX_PLAN_RETRIES):
        try:
            try:
                await status_msg.edit_text("🎨 Планирую структуру сайта..." if attempt == 0 else "🔄 Повторная попытка...")
            except Exception:
                pass

            raw_json, used_model = await _chat_with_model_fallback(ai_messages)
            plan = extract_json(raw_json)
            validate_plan(plan)  # validate raises if structure is broken
            break  # success
        except Exception as plan_err:
            logger.warning("[SiteEngine] Attempt %d: plan failed — %s", attempt + 1, plan_err)
            if attempt == MAX_PLAN_RETRIES - 1:
                # All retries exhausted — fall back to legacy generator
                logger.warning("[SiteEngine] All retries failed, falling back to legacy")
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                await _generate_app_legacy(
                    message, user_request, user_id, username, first_name
                )
                return
            # Brief delay before retry
            await asyncio.sleep(1)

    # ── Step 2: Build HTML from plan ─────────────────────────────────────────
    try:
        try:
            await status_msg.edit_text("⚙️ Собираю страницы и компоненты...")
        except Exception:
            pass

        html_code = build_html(plan)

        if not html_code or len(html_code) < 500:
            raise RuntimeError("Site engine produced empty or too-short HTML")

    except Exception as build_err:
        logger.exception("[SiteEngine] build_html failed: %s", build_err)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await _generate_app_legacy(
            message, user_request, user_id, username, first_name
        )
        return

    # ── Step 3: Store, track and deliver ─────────────────────────────────────
    app_id = str(uuid.uuid4())[:12]  # 12 chars = ~68 bits of randomness, much harder to enumerate
    GENERATED_APPS.put(app_id, html_code)
    # Save plan for future edits (keep last 300 to avoid memory growth)
    if len(SITE_PLANS) > 300:
        try:
            SITE_PLANS.pop(next(iter(SITE_PLANS)))
        except Exception:
            pass
    SITE_PLANS[app_id] = {**plan, "__owner_id": user_id}
    USER_LAST_SITE[user_id] = app_id
    _stat_inc_success(user_id, used_model)

    theme_name = plan.get("theme", "")
    site_type  = plan.get("site_type", "")
    brand      = (plan.get("content") or {}).get("brand", "")

    caption = (
        f"✨ <b>Сайт готов!</b>\n"
        f"<b>{_safe_html(brand)}</b> · {_safe_html(site_type)} · {_safe_html(theme_name)}\n\n"
        "Нажми <b>🚀 Открыть Mini App</b> — сайт откроется внутри Telegram.\n"
        "Также прикреплён HTML-файл для скачивания.\n\n"
        "💬 <i>Напиши что изменить — «убрать блок цен», «поменяй тему», «другие картинки» — и я переделаю.</i>"
    )
    if used_model and used_model.lower() != AI_MODEL.lower():
        caption += (
            f"\n\nℹ️ Использована модель "
            f"<code>{_safe_html(used_model)}</code>"
        )

    edit_btn = InlineKeyboardButton(
        text="✏️ Изменить сайт",
        callback_data=f"edit_site:{app_id}",
    )

    sep_url = "&" if "?" in PUBLIC_URL else "?"
    web_app_url = f"{PUBLIC_URL}/preview/{app_id}{sep_url}utm_source=tg_mini_app"
    browser_url = f"{PUBLIC_URL}/preview/{app_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 Открыть Mini App",
            web_app=WebAppInfo(url=web_app_url),
        )],
        [InlineKeyboardButton(text="🌐 Открыть в браузере", url=browser_url)],
        [edit_btn],
    ])

    file = types.BufferedInputFile(
        html_code.encode("utf-8"),
        filename=f"{site_type}_{app_id}.html"
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    try:
        await message.answer_document(
            document=file,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_content_type_detection=True,
        )
    except Exception as send_err:
        logger.exception("[SiteEngine] send failed: %s", send_err)
        try:

            await message.answer(
                "✅ Сайт создан, но не удалось отправить файл. Попробуй снова."
            )
        except Exception:
            pass


async def _generate_app_legacy(
    message: types.Message,
    user_request: str,
    user_id: int,
    username: str | None,
    first_name: str | None,
):
    """SMART FLOW: AI analyzes request and builds an app/game from design blocks."""

    # ── Detect type of requested output ──────────────────────────────────────
    req_lower = user_request.lower()
    is_game = any(w in req_lower for w in (
        "игр", "game", "quiz", "викторин", "змейк", "крестики", "шахмат",
        "пазл", "memory", "платформ", "аркад", "стрелялк", "runner",
        "flappy", "тетрис", "tetris", "minesweep", "сапёр", "бой",
        "battle", "стратег", "симулятор", "simulator", "war", "войн",
        "fight", "shooter", "clicker", "кликер",
    ))
    is_app = any(w in req_lower for w in (
        "приложени", "app", "трекер", "tracker", "калькулятор", "calculator",
        "таймер", "timer", "конвертер", "конвертор", "дашборд", "dashboard",
        "список", "заметк", "notes", "todo", "задач", "форм", "генератор",
        "generator", "чат", "chat", "погод", "weather", "финанс", "budget",
    ))

    if is_game:
        status_text = "🎮 Разрабатываю игру..."
        output_hint = "GAME"
    elif is_app:
        status_text = "📱 Создаю приложение..."
        output_hint = "APP"
    else:
        status_text = "🧠 Генерирую..."
        output_hint = "APP_OR_WEBSITE"

    status_msg = await message.answer(status_text)

    # ── Design block system (constructor) ────────────────────────────────────
    DESIGN_BLOCKS = """
╔══════════════════════════════════════════════════════════════════╗
║               🎨 DESIGN BLOCK SYSTEM — USE AS CONSTRUCTOR        ║
╚══════════════════════════════════════════════════════════════════╝

TYPOGRAPHY BLOCKS — pick ONE pair based on theme:
  [FONT-A] Luxury/editorial: font-family:'Playfair Display',Georgia,serif (headings) + 'DM Sans',system-ui (body)
  [FONT-B] Modern/tech:      font-family:'Space Grotesk',system-ui (headings) + 'Manrope',system-ui (body)
  [FONT-C] Clean/minimal:    font-family:'Inter',system-ui (all)
  [FONT-D] Creative/game:    font-family:'Syne',system-ui (headings) + 'DM Sans',system-ui (body)
  [FONT-E] Gaming/pixel:     font-family:'Orbitron','Courier New',monospace (headings) + 'Share Tech Mono' (body)
  Load via: <link href="https://fonts.googleapis.com/css2?family=FONT_NAME:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">

COLOR PALETTE BLOCKS — pick ONE theme:
  [DARK-GOLD]    bg:#0a0a0f  accent:#d4af37  text:#f5f0e8  card:#12121a  (luxury, premium)
  [DARK-NEON]    bg:#0d0d1a  accent:#00f5a0  text:#e0fff0  card:#111122  (tech, sci-fi, gaming)
  [DARK-CRIMSON] bg:#0f0508  accent:#e63946  text:#ffeef0  card:#1a0810  (war, drama, thriller)
  [DARK-COBALT]  bg:#050510  accent:#4361ee  text:#eef2ff  card:#0a0a20  (space, ai, futuristic)
  [DARK-AMBER]   bg:#0c0800  accent:#f4a261  text:#fff8ee  card:#1a1000  (desert, adventure, history)
  [LIGHT-CREAM]  bg:#faf7f2  accent:#3d405b  text:#1a1a2e  card:#fff    (minimal, editorial, calm)
  [LIGHT-FRESH]  bg:#f0fdf4  accent:#16a34a  text:#14532d  card:#fff    (health, nature, finance)

LAYOUT BLOCKS — combine as needed:
  [NAV]    Sticky top navigation: logo left, links right, hamburger on mobile
  [HERO]   Full-width opening section: big headline + subtext + CTA button
  [GRID]   CSS Grid: repeat(auto-fill, minmax(280px,1fr)) gap:1.5rem
  [CARD]   border-radius:16px; backdrop-filter:blur(10px); box-shadow; hover scale
  [MODAL]  Centered overlay with backdrop-filter:blur(8px); slide-in animation
  [CANVAS] <canvas> element for games: requestAnimationFrame game loop
  [SCORE]  Score/progress bar: top fixed HUD with lives, score, timer
  [BTN]    Button: padding:12px 28px; border-radius:12px; hover/active animations

ANIMATION BLOCKS — use freely:
  [FADE-IN]    @keyframes fadeIn{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}
  [PULSE]      @keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}
  [SHAKE]      @keyframes shake{0%,100%{transform:none}25%{transform:translateX(-8px)}75%{transform:translateX(8px)}}
  [SLIDE-IN]   @keyframes slideIn{from{transform:translateX(-100%)}to{transform:translateX(0)}}
  [GLOW]       text-shadow: 0 0 20px currentColor; box-shadow: 0 0 30px accent-color
  [PARTICLE]   Small CSS dots animated with random positions and opacity

GAME ENGINE BLOCKS (for [CANVAS] games):
  [LOOP]    const loop=(ts)=>{ctx.clearRect(0,0,W,H);update(ts);draw();raf=requestAnimationFrame(loop)};
  [INPUT]   document.addEventListener('keydown', e=>{keys[e.key]=true}); touchstart/touchend for mobile
  [COLL]    Rect collision: (a.x<b.x+b.w && a.x+a.w>b.x && a.y<b.y+b.h && a.y+a.h>b.y)
  [SPAWN]   setInterval(()=>{enemies.push({x:Math.random()*W, y:-50, speed:2+Math.random()*3})}, 1500)
  [STORAGE] localStorage for high score: localStorage.setItem('hs', score); getItem('hs')
"""

    # ── Instruction varies by type ────────────────────────────────────────────
    if is_game:
        task_instruction = f"""
OUTPUT TYPE: GAME

The user wants a GAME. Build a complete, playable HTML5 game that is:
- STRICTLY themed around: "{user_request}"
- Fully playable on mobile (touch controls) AND desktop (keyboard/mouse)

MANDATORY PREMIUM GAME STYLING (CRITICAL):
1. The game UI MUST look "expensive" and beautiful, just like a premium modern website.
2. Use a gorgeous CSS background (e.g., deep gradients like `linear-gradient(135deg, #0f172a, #1e1b4b)`).
3. Any game board (like chess, grids, or playing areas) MUST have `border-radius: 16px;`, soft drop shadows (`box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);`), and a glassmorphism container (`backdrop-filter: blur(16px); background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);`).
4. Typography must be modern (use Inter, Orbitron, or Playfair Display depending on theme). Buttons must have beautiful hover effects (`transform: translateY(-2px)`, glow).
5. If it's a board game (like chess), do NOT use flat standard colors. Use beautiful thematic palettes (e.g., translucent frosty glass and deep obsidian for cells). Use high-quality Unicode icons or SVG for pieces.

MECHANICS & RULES:
1. The game must match the requested theme visually and mechanically.
2. Include a Start Screen and Game Over screen using styled overlays.
3. Output ONLY <!DOCTYPE html>...</html>, no markdown, no explanation.
"""
    else:
        task_instruction = f"""
OUTPUT TYPE: {'APP' if is_app else 'INTERACTIVE APP OR MINI-WEBSITE'}

Build a complete, interactive HTML5 application STRICTLY about: "{user_request}"

MANDATORY RULES:
1. The app/page MUST be 100% themed around the user's exact topic — no generic templates
2. Content, labels, sections, data must reflect the specific subject matter
3. Use real, topic-relevant text, not "Item 1" or "Section A"
4. Include actual interactivity (filters, inputs, animations, modal dialogs)
5. Output ONLY <!DOCTYPE html>...</html>, no markdown, no explanation
"""

    system_prompt = f"""{DESIGN_BLOCKS}

═══════════════════════════════════════════════════════════════════
CRITICAL RULES — NEVER VIOLATE:
  ① YOU ARE A BUILDER, NOT AN ANALYST. Build the app immediately. Do NOT explain, list, or describe.
  ② Return ONLY valid HTML starting with <!DOCTYPE html> — no code fences, no markdown, no text before or after
  ③ The output MUST be a SINGLE self-contained HTML file with all CSS in <style> and JS in <script>
  ④ Use CDN only: Google Fonts, Tailwind CDN (https://cdn.tailwindcss.com), or vanilla CSS — no npm
  ⑤ NEVER output a To-Do list, calculator, or generic app unless the user specifically asked for it
  ⑥ Mobile-first: viewport meta tag, touch events, responsive layout
  ⑦ Use design blocks above as a construction kit — combine them to build premium UI
═══════════════════════════════════════════════════════════════════

{task_instruction}

BUILD IT NOW. Start your response with <!DOCTYPE html> immediately."""

    try:
        raw_code, used_model = await _chat_with_model_fallback([
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_request},
        ])
        code = _strip_code_blocks(raw_code)
        if not code or not code.strip().lower().startswith("<!doctype"):
            raise RuntimeError("AI вернул не HTML код.")

        app_id = str(uuid.uuid4())[:12]
        GENERATED_APPS.put(app_id, code)
        
        # Save to SITE_PLANS so we can edit it later
        SITE_PLANS[app_id] = {
            "__is_legacy": True,
            "__html": code,
            "__owner_id": user_id,
            "__type": "game" if is_game else "app"
        }
        USER_LAST_SITE[user_id] = app_id
        
        _stat_inc_success(user_id, used_model)

        type_label = "🎮 Игра" if is_game else ("📱 Приложение" if is_app else "✨ Страница")
        caption = (
            f"{type_label} <b>готово!</b>\n"
            f"Нажми <b>🚀 Открыть Mini App</b> — откроется прямо в Telegram.\n"
            f"Также прикреплён HTML-файл для скачивания.\n\n"
            f"💬 <i>Напиши что изменить — и я переделаю.</i>"
        )
        if used_model.lower() != AI_MODEL.lower():
            caption += f"\n\nℹ️ Модель: <code>{_safe_html(used_model)}</code>"

        sep_url = "&" if "?" in PUBLIC_URL else "?"
        web_app_url = f"{PUBLIC_URL}/preview/{app_id}{sep_url}utm_source=tg_mini_app"
        browser_url = f"{PUBLIC_URL}/preview/{app_id}"
        
        edit_btn_text = "✏️ Изменить игру" if is_game else "✏️ Изменить приложение"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🚀 Открыть Mini App",
                web_app=WebAppInfo(url=web_app_url),
            )],
            [InlineKeyboardButton(text="🌐 Открыть в браузере", url=browser_url)],
            [InlineKeyboardButton(text=edit_btn_text, callback_data=f"edit_site:{app_id}")],
        ])

        file_bytes = code.encode("utf-8")
        ext_label = "game" if is_game else "app"
        file = types.BufferedInputFile(file_bytes, filename=f"{ext_label}_{app_id}.html")

        try:
            await status_msg.delete()
        except Exception:
            pass

        await message.answer_document(
            document=file,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_content_type_detection=True,
        )

    except Exception as exc:

        _stat_inc_fail(user_id)
        user_msg = _format_ai_error(exc)
        logger.exception("Не удалось сгенерировать приложение: %s", user_msg)
        try:
            await status_msg.edit_text(user_msg, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            try:
                await message.answer(user_msg, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════
# ✏️  EDIT SITE SYSTEM
# ═══════════════════════════════════════════════════════════

@dp.callback_query(F.data.startswith("edit_site:"))
async def on_edit_site_callback(call: types.CallbackQuery):
    """User clicked '✏️ Изменить сайт' button."""
    try:
        await call.answer()
    except Exception:
        pass
    user_id = call.from_user.id if call.from_user else 0
    app_id = call.data.split(":", 1)[1] if ":" in call.data else ""

    if not app_id or app_id not in SITE_PLANS:
        await call.message.answer(
            "⚠️ Сайт не найден в кэше (возможно, истёк срок хранения). "
            "Создай новый сайт — просто напиши запрос."
        )
        return

    # ── Ownership check: only the original creator can edit their site ────────────────────
    owner_id = SITE_PLANS[app_id].get("__owner_id")
    if owner_id and owner_id != user_id:
        await call.answer("⚠️ Это не твой сайт — редактировать нельзя.", show_alert=True)
        return

    # Link this site to the requesting user for future text edits
    USER_LAST_SITE[user_id] = app_id
    plan = SITE_PLANS[app_id]
    is_legacy = plan.get("__is_legacy")
    
    if is_legacy:
        type_str = "игру" if plan.get("__type") == "game" else "приложение"
        await call.message.answer(
            f"✏️ <b>Редактирование ({type_str})</b>\n\n"
            "Напиши что хочешь изменить. Например:\n"
            "• <i>Сделай фон тёмным</i>\n"
            "• <i>Ускорь движение персонажа</i>\n"
            "• <i>Добавь таймер</i>\n"
            "• <i>Поменяй цвета на неоновые</i>",
            parse_mode="HTML",
        )
    else:
        brand = (plan.get("content") or {}).get("brand", "сайт")
        await call.message.answer(
            f"✏️ <b>Редактирование «{_safe_html(brand)}»</b>\n\n"
            "Напиши что хочешь изменить. Например:\n"
            "• <i>Убери блок с ценами</i>\n"
            "• <i>Смени тему на тёмную</i>\n"
            "• <i>Поменяй название на «МойСайт»</i>\n"
            "• <i>Другие картинки</i>\n"
            "• <i>Добавь раздел FAQ</i>\n"
            "• <i>Убери галерею</i>",
            parse_mode="HTML",
        )


def _detect_edit_intent(text: str) -> bool:
    """Return True if the message looks like a site edit request (not a new site request)."""
    t = text.lower().strip()
    # Specific edit-action keywords only — avoid vague words that fire for new site requests
    keywords = (
        "убер", "удал", "убрать", "удалить",
        "добавь", "добав раздел", "добав блок", "добав",
        "смени тему", "поменяй тему", "поменяй название",
        "измени тему", "перекрась",
        "другие картинк", "другую тему", "другой стиль", "другие фото",
        "без блок", "без отзыв", "без цен", "без галере",
        "переделай блок", "переделай секцию",
        "remove", "delete", "rename to", "change theme",
        "different image", "new image",
        "убери", "измени", "замени", "сделай фон", "сделай цвет",
        "ускорь", "уменьши", "увеличь", "сделай больше", "сделай меньше", "быстрее", "медленнее",
    )
    return any(kw in t for kw in keywords)


async def _edit_website(
    message: types.Message,
    edit_request: str,
    user_id: int,
    app_id: str,
):
    """Patch an existing plan based on the user's edit request and rebuild HTML."""
    plan = SITE_PLANS.get(app_id)
    if not plan:
        await message.answer("⚠️ Исходный сайт не найден в кэше. Создай новый — просто напиши запрос.")
        return

    if plan.get("__is_legacy"):
        await _edit_app_legacy(message, edit_request, user_id, app_id, plan)
        return

    status_msg = await message.answer("🔄 Вношу изменения...")

    import copy, json as _json
    new_plan = copy.deepcopy(plan)
    t = edit_request.lower()

    # We now pass the ENTIRE plan back to the AI so it can structurally edit the site
    try:
        await status_msg.edit_text("🧠 Запрашиваю AI для внесения изменений...")
    except Exception:
        pass

    try:
        from site_engine.generator import get_system_prompt, extract_json
        from site_engine.schema import validate_plan
        
        current_plan_json = _json.dumps(new_plan, ensure_ascii=False, indent=2)
        
        regen_prompt = (
            f"Here is the current JSON plan for the user's website:\n"
            f"```json\n{current_plan_json}\n```\n\n"
            f"USER EDIT REQUEST: {edit_request}\n\n"
            "INSTRUCTIONS:\n"
            "Modify the JSON plan according to the user's request.\n"
            "You can change the 'theme', 'font_pair', add/remove items in the 'sections' array, "
            "and update the 'content' object as needed to fulfill the request.\n"
            "Return the FULL updated JSON plan. Output ONLY valid JSON, no markdown, no explanations."
        )
        ai_messages = [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": regen_prompt},
        ]
        raw, used_model = await _chat_with_model_fallback(ai_messages)
        regen_plan = extract_json(raw)
        
        # Merge AI changes safely
        if "theme" in regen_plan: new_plan["theme"] = regen_plan["theme"]
        if "font_pair" in regen_plan: new_plan["font_pair"] = regen_plan["font_pair"]
        if "site_type" in regen_plan: new_plan["site_type"] = regen_plan["site_type"]
        if "sections" in regen_plan: new_plan["sections"] = regen_plan["sections"]
        if "content" in regen_plan: new_plan["content"] = regen_plan["content"]
        
    except Exception as ae:
        logger.warning("[Edit] AI re-plan failed: %s", ae)
        try:
            await status_msg.edit_text("❌ Не удалось перестроить сайт. Ошибка AI.")
        except Exception:
            pass
        return

    # ── Rebuild HTML ──────────────────────────────────────────────────────────
    try:
        from site_engine.generator import build_html
        from site_engine.schema import validate_plan
        validated = validate_plan(new_plan)
        new_html = build_html(validated)
    except Exception as build_err:
        logger.exception("[Edit] build_html failed: %s", build_err)
        try:
            await status_msg.edit_text("❌ Не удалось применить изменения. Попробуй переформулировать.")
        except Exception:
            pass
        return

    # ── Store and deliver ─────────────────────────────────────────────────────
    new_app_id = str(uuid.uuid4())[:12]  # 12 chars, harder to enumerate
    GENERATED_APPS.put(new_app_id, new_html)
    SITE_PLANS[new_app_id] = {**validated, "__owner_id": user_id}
    USER_LAST_SITE[user_id] = new_app_id

    brand     = (validated.get("content") or {}).get("brand", "")
    site_type = validated.get("site_type", "")
    theme     = validated.get("theme", "")

    caption = (
        f"✅ <b>Изменения применены!</b>\n"
        f"<b>{_safe_html(brand)}</b> · {_safe_html(site_type)} · {_safe_html(theme)}\n\n"
        "💬 <i>Снова напиши что изменить — или создай новый сайт с нуля.</i>"
    )

    edit_btn = InlineKeyboardButton(
        text="✏️ Изменить ещё",
        callback_data=f"edit_site:{new_app_id}",
    )

    sep_url = "&" if "?" in PUBLIC_URL else "?"
    web_app_url = f"{PUBLIC_URL}/preview/{new_app_id}{sep_url}utm_source=tg_mini_app"
    browser_url = f"{PUBLIC_URL}/preview/{new_app_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 Открыть Mini App",
            web_app=WebAppInfo(url=web_app_url),
        )],
        [InlineKeyboardButton(text="🌐 Открыть в браузере", url=browser_url)],
        [edit_btn],
    ])

    file_obj = types.BufferedInputFile(
        new_html.encode("utf-8"),
        filename=f"{site_type}_{new_app_id}_edited.html",
    )
    try:
        await status_msg.delete()
    except Exception:
        pass
    try:
        await message.answer_document(
            document=file_obj,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_content_type_detection=True,
        )
    except Exception as se:
        logger.exception("[Edit] send failed: %s", se)
        await message.answer("✅ Изменения применены, но файл не удалось отправить.")


async def _edit_app_legacy(
    message: types.Message,
    edit_request: str,
    user_id: int,
    app_id: str,
    plan: dict,
):
    """Directly edit legacy HTML games/apps using the AI."""
    status_msg = await message.answer("🔄 Вношу изменения в код...")
    old_html = plan.get("__html", "")
    
    system_prompt = (
        "Ты — AI-разработчик. Пользователь просит изменить существующий HTML/JS/CSS код.\n"
        "Тебе дается текущий код приложения/игры и запрос на изменение.\n"
        "ВАЖНО: Верни ТОЛЬКО обновленный HTML-код начиная с <!DOCTYPE html>.\n"
        "Никаких пояснений или блоков markdown. Верни ВЕСЬ код целиком с изменениями."
    )
    user_prompt = f"Вот текущий код:\n```html\n{old_html}\n```\n\nЗапрос на изменение: {edit_request}"
    
    try:
        raw_code, used_model = await _chat_with_model_fallback([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        code = _strip_code_blocks(raw_code)
        if not code or not code.strip().lower().startswith("<!doctype"):
            raise RuntimeError("AI вернул не HTML код.")

        new_app_id = str(uuid.uuid4())[:12]
        GENERATED_APPS.put(new_app_id, code)
        SITE_PLANS[new_app_id] = {**plan, "__html": code, "__owner_id": user_id}
        USER_LAST_SITE[user_id] = new_app_id
        
        type_str = "Игры" if plan.get("__type") == "game" else "Приложения"
        caption = (
            f"✅ <b>Изменения применены ({type_str})!</b>\n"
            f"Нажми <b>🚀 Открыть Mini App</b> — откроется прямо в Telegram.\n"
            f"Также прикреплён HTML-файл для скачивания.\n\n"
            f"💬 <i>Напиши что изменить — и я переделаю.</i>"
        )
        if used_model.lower() != AI_MODEL.lower():
            caption += f"\n\nℹ️ Модель: <code>{_safe_html(used_model)}</code>"

        sep_url = "&" if "?" in PUBLIC_URL else "?"
        web_app_url = f"{PUBLIC_URL}/preview/{new_app_id}{sep_url}utm_source=tg_mini_app"
        browser_url = f"{PUBLIC_URL}/preview/{new_app_id}"
        
        edit_btn_text = "✏️ Изменить ещё"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🚀 Открыть Mini App",
                web_app=WebAppInfo(url=web_app_url),
            )],
            [InlineKeyboardButton(text="🌐 Открыть в браузере", url=browser_url)],
            [InlineKeyboardButton(text=edit_btn_text, callback_data=f"edit_site:{new_app_id}")],
        ])

        file_bytes = code.encode("utf-8")
        ext_label = "game" if plan.get("__type") == "game" else "app"
        file = types.BufferedInputFile(file_bytes, filename=f"{ext_label}_{new_app_id}_edited.html")

        try:
            await status_msg.delete()
        except Exception:
            pass

        await message.answer_document(
            document=file,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_content_type_detection=True,
        )

    except Exception as exc:
        _stat_inc_fail(user_id)
        user_msg = _format_ai_error(exc)
        logger.exception("Не удалось изменить legacy app: %s", user_msg)
        try:
            await status_msg.edit_text("❌ " + user_msg, parse_mode="HTML")
        except:
            pass


# ================= ЗАПУСК =================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
