import requests
import json
import config
from sql_app import models
from sql_app.database import Session
import telebot
from telebot import types
import uuid
from datetime import datetime, timedelta
import urllib3

# Отключаем предупреждения о SSL (для разработки)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Константы GigaChat API
GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# Хранилище токенов (в памяти, для простоты)
# В продакшене лучше использовать Redis или БД
access_tokens = {}  # {user_id: {'token': str, 'expires_at': datetime}}

def get_access_token(user_id=None):
    """
    Получает access token для GigaChat API.
    Токен действует 30 минут [citation:4][citation:6]
    """
    # Проверяем, есть ли еще валидный токен
    if user_id and user_id in access_tokens:
        token_data = access_tokens[user_id]
        if token_data['expires_at'] > datetime.now():
            return token_data['token']
    
    # Подготавливаем данные
    auth_header = f"Basic {config.GIGACHAT_CREDENTIALS}"
    rq_uuid = str(uuid.uuid4())
    
    # Важно: кодируем заголовки в UTF-8, потом декодируем в latin-1
    # Это стандартный костыль для requests с русскими символами
    headers = {
        "Authorization": auth_header.encode('utf-8').decode('latin-1'),
        "Content-Type": "application/x-www-form-urlencoded",
        "RqUID": rq_uuid.encode('utf-8').decode('latin-1')
    }
    
    data = {
        "scope": "GIGACHAT_API_PERS"  # Для физических лиц 
    }
    
    try:
        # ВАЖНО: Отключаем проверку SSL для разработки
        # В продакшене нужно настроить сертификаты Минцифры [citation:4]
        response = requests.post(
            GIGACHAT_AUTH_URL,
            headers=headers,
            data=data,
            verify=False  # Для разработки. В продакшене - настрой сертификаты!
        )
        response.raise_for_status()
        
        result = response.json()
        token = result['access_token']
        expires_in = result.get('expires_in', 1800)  # 30 минут по умолчанию
        
        # Сохраняем токен
        if user_id:
            access_tokens[user_id] = {
                'token': token,
                'expires_at': datetime.now() + timedelta(seconds=expires_in - 60)  # Запас 1 минута
            }
        
        return token
        
    except requests.exceptions.RequestException as e:
        print(f"Ошибка получения токена GigaChat: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Статус: {e.response.status_code}")
            print(f"Ответ: {e.response.text}")
        return None

def gigachat_completion(messages, temperature=0.3, max_tokens=1000, user_id=None):
    """
    Отправляет запрос к GigaChat API
    Формат совместим с OpenAI API [citation:4][citation:9]
    """
    token = get_access_token(user_id)
    if not token:
        return "Ошибка авторизации GigaChat"
    
    # Кодируем заголовок авторизации
    auth_header = f"Bearer {token}"
    
    headers = {
        "Authorization": auth_header.encode('utf-8').decode('latin-1'),
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "GigaChat",  # Базовая модель 
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }
    
    try:
        # Сериализуем JSON с русскими символами
        json_data = json.dumps(data, ensure_ascii=False).encode('utf-8')

        # Отключаем проверку SSL для разработки
        response = requests.post(
            GIGACHAT_API_URL,
            headers=headers,
            json=data,
            verify=False  # Для разработки. В продакшене - настрой сертификаты!
        )
        response.raise_for_status()
        
        result = response.json()
        
        # Извлекаем ответ в формате, совместимом с OpenAI [citation:4]
        if 'choices' in result and len(result['choices']) > 0:
            return result['choices'][0]['message']['content']
        
        return "Не удалось получить ответ от GigaChat"
        
    except requests.exceptions.RequestException as e:
        print(f"Ошибка запроса к GigaChat: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Статус: {e.response.status_code}")
            print(f"Ответ: {e.response.text}")
        return None


def find_group(group_name):
    """Найти группу по названию (cipher)"""
    session = Session()
    try:
        group = session.query(models.Group).filter(
            models.Group.cipher.ilike(f"%{group_name}%")
        ).first()
        return group
    finally:
        session.close()

def find_department(dept_name):
    """Найти отделение по названию"""
    session = Session()
    try:
        dept = session.query(models.Departments).filter(
            models.Departments.name.ilike(f"%{dept_name}%")
        ).first()
        return dept
    finally:
        session.close()

def process_with_gpt(user_text, user_id, bot, message):
    """
    Главная функция: принимает текст, отправляет в GigaChat, выполняет действие
    """
    try:
        # Формируем сообщения для GigaChat (формат как у OpenAI)
        messages = [
            {
                "role": "system",
                "content": """
Ты — помощник бота для учета контингента (студентов).
Твоя задача — понять, что хочет пользователь, и вернуть ТОЛЬКО JSON.

Доступные действия:
1. view_group — показать данные группы
   Параметры: {"group": "название группы"} (пример: "Д-112")

2. view_department — показать все группы отделения
   Параметры: {"department": "название отделения"} (пример: "Энергетическое")

3. add_data — добавить данные
   Параметры: {"group": "название", "date": "дд.мм.гггг", "count": число}

4. help — если не поняли запрос
   Параметры: {"message": "пояснение"}

Примеры запросов и ответов:
- "Покажи Д-112" → {"action": "view_group", "params": {"group": "Д-112"}}
- "Сколько студентов в энергетическом?" → {"action": "view_department", "params": {"department": "Энергетическое"}}
- "Запиши 25 человек в Д-112 15.03.2024" → {"action": "add_data", "params": {"group": "Д-112", "date": "15.03.2024", "count": 25}}
- "Привет" → {"action": "help", "params": {"message": "Я могу показать данные или записать новые. Например: 'Покажи Д-112' или 'Запиши 20 человек в Д-112 01.04.2024'"}}

Верни ТОЛЬКО JSON, без пояснений.
                """
            },
            {
                "role": "user",
                "content": user_text
            }
        ]
        
        # Отправляем запрос в GigaChat
        response_text = gigachat_completion(messages, temperature=0.3, user_id=user_id)
        
        if not response_text:
            bot.send_message(
                user_id,
                "❌ Не удалось получить ответ от GigaChat. Проверьте API ключ."
            )
            return
        
        # Очищаем ответ от возможных маркдеров
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()
        elif response_text.startswith("```"):
            response_text = response_text.replace("```", "").strip()
        
        # Парсим JSON
        action_data = json.loads(response_text)
        
        # Выполняем действие (КОД НИЖЕ БЕЗ ИЗМЕНЕНИЙ)
        if action_data['action'] == 'view_group':
            group_name = action_data['params']['group']
            group = find_group(group_name)
            
            if group:
                from main import show_contingent_and_restart
                show_contingent_and_restart(message, user_id, group.id)
            else:
                bot.send_message(
                    user_id,
                    f"❌ Группа '{group_name}' не найдена.\n"
                    "Попробуйте: Д-112, Э-42, Т-21"
                )
        
        elif action_data['action'] == 'view_department':
            dept_name = action_data['params']['department']
            dept = find_department(dept_name)
            
            if dept:
                from main import show_groups
                show_groups(message, dept.id)
            else:
                bot.send_message(
                    user_id,
                    f"❌ Отделение '{dept_name}' не найдено.\n"
                    "Попробуйте: Энергетическое, Механическое, Строительное"
                )
        
        elif action_data['action'] == 'add_data':
            params = action_data['params']
            group = find_group(params['group'])
            
            if group:
                from main import user_states
                user_states[user_id] = {
                    'action': 'record',
                    'group_id': group.id
                }
                
                # Создаем клавиатуру для подтверждения
                keyboard = types.InlineKeyboardMarkup(row_width=2)
                confirm_btn = types.InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_ai_add_{group.id}_{params['date']}_{params['count']}"
                )
                cancel_btn = types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_action"
                )
                keyboard.add(confirm_btn, cancel_btn)
                
                bot.send_message(
                    user_id,
                    f"📝 *Подтвердите добавление:*\n\n"
                    f"👥 Группа: {group.cipher}\n"
                    f"📅 Дата: {params['date']}\n"
                    f"👤 Количество: {params['count']} чел.",
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            else:
                bot.send_message(
                    user_id,
                    f"❌ Группа '{params['group']}' не найдена."
                )
        
        elif action_data['action'] == 'help':
            bot.send_message(
                user_id,
                f"ℹ️ {action_data['params']['message']}"
            )
        
    except json.JSONDecodeError:
        bot.send_message(
            user_id,
            "❌ Не удалось обработать запрос. Попробуйте перефразировать.\n"
            "Пример: 'Покажи Д-112' или 'Запиши 20 человек 15.03.2024 в Д-112'"
        )
    except KeyError as e:
        bot.send_message(
            user_id,
            f"❌ Ошибка в формате ответа: {e}"
        )
    except Exception as e:
        bot.send_message(
            user_id,
            f"❌ Ошибка: {e}"
        )

def check_gigachat_connection():
    """Проверка подключения к GigaChat"""
    test_messages = [
        {
            "role": "system",
            "content": "Ответь одним словом: привет"
        }
    ]
    result = gigachat_completion(test_messages, temperature=0.1, max_tokens=10)
    if result:
        print(f"✅ GigaChat подключен. Тест: {result}")
        return True
    else:
        print("❌ Ошибка подключения к GigaChat")
        return False