import os
from telethon import TelegramClient, events
import aiohttp
import asyncio
from aiohttp import web
import json
import hashlib
from datetime import datetime

# ===== НАСТРОЙКИ БОТА =====
API_ID = 25851310
API_HASH = "6e623f9734f999d0ca50f8b9d81247ae"
BOT_TOKEN = "8100386629:AAGr3hwt9EoeGRRiubIJwIYOSJ1qLKtB9h8"
SOURCE_CHANNEL = "@testmytest138"
WEBHOOK_URL = "https://hook.us1.make.com/1u09zg5rt4p6e2bu8j44rk2niktvrjv1"  # Ваш webhook

# Порт для API сервера
API_PORT = int(os.environ.get('PORT', 8080))

# ===== TELEGRAM КЛИЕНТ =====
client = TelegramClient('bot_session', API_ID, API_HASH)

# Хранилище для временных ссылок
file_cache = {}

# ===== WEB API ДЛЯ MAKE.COM =====
app = web.Application()
routes = web.RouteTableDef()

@routes.get('/')
async def index(request):
    return web.json_response({
        'status': 'Bot API is running',
        'endpoints': {
            '/upload': 'POST - Upload file and get URL',
            '/process': 'POST - Process Telegram file_id'
        }
    })

@routes.post('/upload')
async def upload_file(request):
    """Endpoint для загрузки файла из Make.com"""
    try:
        reader = await request.multipart()
        file_data = None
        caption = ""
        
        # Читаем данные из формы
        async for field in reader:
            if field.name == 'file':
                file_data = await field.read()
                filename = field.filename or 'video.mp4'
            elif field.name == 'caption':
                caption = await field.text()
        
        if not file_data:
            return web.json_response({'error': 'No file provided'}, status=400)
        
        # Загружаем на хостинг
        print(f"Получен файл размером {len(file_data)} байт")
        
        async with aiohttp.ClientSession() as session:
            # Используем 0x0.st для загрузки
            data = aiohttp.FormData()
            data.add_field('file', file_data, filename=filename)
            
            response = await session.post('https://0x0.st', data=data)
            file_url = await response.text()
            file_url = file_url.strip()
            
            if not file_url.startswith('http'):
                # Пробуем file.io как запасной вариант
                data = {'file': (filename, file_data)}
                response = await session.post('https://file.io', data=data)
                result = await response.json()
                file_url = result.get('link', '')
        
        print(f"Файл загружен: {file_url}")
        
        return web.json_response({
            'success': True,
            'url': file_url,
            'caption': caption,
            'size': len(file_data)
        })
        
    except Exception as e:
        print(f"Ошибка при загрузке: {e}")
        return web.json_response({'error': str(e)}, status=500)

@routes.post('/process')
async def process_telegram_file(request):
    """Endpoint для обработки file_id из Telegram"""
    try:
        data = await request.json()
        file_id = data.get('file_id')
        message_id = data.get('message_id')
        chat_id = data.get('chat_id')
        
        if not all([file_id, message_id, chat_id]):
            return web.json_response({'error': 'Missing parameters'}, status=400)
        
        # Проверяем кеш
        cache_key = f"{chat_id}:{message_id}"
        if cache_key in file_cache:
            return web.json_response({
                'success': True,
                'url': file_cache[cache_key],
                'from_cache': True
            })
        
        # Здесь можно добавить загрузку через Telegram API
        # Пока возвращаем заглушку
        return web.json_response({
            'success': False,
            'error': 'Direct Telegram download not implemented yet',
            'hint': 'Use /upload endpoint with file data'
        })
        
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

# ===== TELEGRAM ОБРАБОТЧИКИ =====
@client.on(events.NewMessage(chats=[SOURCE_CHANNEL]))
async def handler(event):
    """Обработчик сообщений из канала"""
    if event.media:
        print(f"Обнаружен файл в канале!")
        
        try:
            # Получаем информацию о файле
            file_info = await get_file_info(event)
            
            # Кешируем для быстрого доступа
            cache_key = f"{event.chat_id}:{event.id}"
            
            if file_info['size'] > 20 * 1024 * 1024:  # Больше 20 МБ
                print(f"Большой файл ({file_info['size']} байт), загружаем...")
                
                # Скачиваем и загружаем
                file_bytes = await event.download_media(bytes)
                file_url = await upload_to_hosting(file_bytes, file_info['extension'])
                
                file_cache[cache_key] = file_url
                
                # Отправляем в webhook
                await send_to_webhook({
                    'type': 'large_file',
                    'url': file_url,
                    'caption': event.text or '',
                    'file_size': file_info['size'],
                    'message_id': event.id,
                    'chat_id': event.chat_id
                })
            else:
                # Маленький файл - отправляем как обычно
                await send_small_file(event, file_info)
                
        except Exception as e:
            print(f"Ошибка: {e}")

async def get_file_info(event):
    """Получает информацию о файле"""
    file_extension = "bin"
    file_size = 0
    
    if hasattr(event.media, 'document'):
        file_size = event.media.document.size
        for attr in event.media.document.attributes:
            if hasattr(attr, 'file_name'):
                if '.' in attr.file_name:
                    file_extension = attr.file_name.split('.')[-1]
                break
    elif hasattr(event.media, 'video'):
        file_size = event.media.video.size if hasattr(event.media.video, 'size') else 0
        file_extension = "mp4"
    elif hasattr(event.media, 'photo'):
        file_extension = "jpg"
    
    return {
        'size': file_size,
        'extension': file_extension
    }

async def upload_to_hosting(file_bytes, extension):
    """Загружает файл на хостинг"""
    async with aiohttp.ClientSession() as session:
        data = aiohttp.FormData()
        data.add_field('file', file_bytes, filename=f'file.{extension}')
        
        response = await session.post('https://0x0.st', data=data)
        file_url = await response.text()
        return file_url.strip()

async def send_to_webhook(data):
    """Отправляет данные в Make.com webhook"""
    if WEBHOOK_URL == "https://hook.eu1.make.com/your_webhook":
        print("⚠️  Webhook не настроен!")
        return
    
    async with aiohttp.ClientSession() as session:
        await session.post(WEBHOOK_URL, json=data)
        print("Отправлено в Make.com!")

async def send_small_file(event, file_info):
    """Отправляет маленький файл напрямую"""
    file_bytes = await event.download_media(bytes)
    
    async with aiohttp.ClientSession() as session:
        data = aiohttp.FormData()
        data.add_field('file', file_bytes, filename=f'file.{file_info["extension"]}')
        data.add_field('caption', event.text or '')
        data.add_field('type', 'direct_file')
        
        await session.post(WEBHOOK_URL, data=data)
        print("Маленький файл отправлен в Make.com!")

# ===== ЗАПУСК =====
async def start_telegram():
    """Запускает Telegram клиент"""
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Telegram бот запущен!")
    print(f"📡 Слежу за каналом: {SOURCE_CHANNEL}")

async def start_web_server():
    """Запускает веб-сервер"""
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', API_PORT)
    await site.start()
    print(f"🌐 API сервер запущен на порту {API_PORT}")
    print(f"📍 Endpoints:")
    print(f"   - POST http://localhost:{API_PORT}/upload - для загрузки файлов")
    print(f"   - POST http://localhost:{API_PORT}/process - для обработки file_id")

async def main():
    """Главная функция"""
    # Запускаем оба сервиса
    await asyncio.gather(
        start_telegram(),
        start_web_server()
    )
    
    # Работаем пока не остановят
    await client.run_until_disconnected()

if __name__ == '__main__':
    print("🚀 Запуск системы...")
    asyncio.run(main())