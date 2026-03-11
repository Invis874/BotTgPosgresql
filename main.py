import time
import telebot
import traceback
from telebot import types
from sql_app import models
from sql_app.database import Session, engine
import config
from datetime import datetime
from requests.exceptions import ReadTimeout, ConnectionError

from ai_assistant import process_with_gpt, check_gigachat_connection
from voice_handler import process_voice

from telebot.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton


bot = telebot.TeleBot(config.TOKEN)

# Создаем таблицы (если их нет)
models.Base.metadata.create_all(bind=engine)

# Хранилище состояний пользователей
user_states = {}  # {user_id: {'action': 'know'/'record', 'department_id': id, 'group_id': id}}

def send_or_edit_message(bot, text, chat_id, message_id=None, from_user_id=None, **kwargs):
    """
    Отправляет новое сообщение или редактирует существующее (если оно от бота)
    """
    # Если нет message_id или сообщение от пользователя - отправляем новое
    if not message_id or from_user_id != bot.get_me().id:
        return bot.send_message(chat_id, text, **kwargs)
    
    # Иначе редактируем
    try:
        return bot.edit_message_text(text, chat_id, message_id, **kwargs)
    except Exception as e:
        # Если не вышло редактировать - отправляем новое
        print(f"Не удалось отредактировать: {e}")
        return bot.send_message(chat_id, text, **kwargs)

def get_cancel_keyboard():
    """Создать клавиатуру с кнопкой отмены"""
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard = add_cancel_button(keyboard)
    return keyboard

def add_cancel_button(keyboard):
    """Добавить кнопку отмены к существующей клавиатуре"""
    cancel_btn = types.InlineKeyboardButton(
        text="❌ Отмена / В начало",
        callback_data="cancel_action"
    )
    keyboard.add(cancel_btn)
    return keyboard

@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    user_states[user_id] = {}  # Сбрасываем состояние
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    key_know = types.InlineKeyboardButton(text="📊 Узнать", callback_data="action_know")
    key_record = types.InlineKeyboardButton(text="✏️ Записать", callback_data="action_record")
    keyboard.add(key_know, key_record)
    
    bot.send_message(
        user_id,
        "👋 Добро пожаловать!\nВы хотите узнать данные или записать новые?",
        reply_markup=keyboard
    )

@bot.message_handler(commands=['webapp'])
def webapp_command(message):
    """Открывает Web App"""
    keyboard = InlineKeyboardMarkup()
    webapp_button = InlineKeyboardButton(
        text="📱 Открыть панель управления",
        web_app=WebAppInfo(url=config.WEBAPP_URL)  # URL из .env
    )
    keyboard.add(webapp_button)
    
    bot.send_message(
        message.chat.id,
        "📊 *Панель управления контингентом*\n\n"
        "Здесь вы можете удобно просматривать и редактировать данные:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data == "cancel_action")
def handle_cancel(call):
    """Обработка отмены действия - возврат в начало"""
    user_id = call.from_user.id
    user_states[user_id] = {}  # Полностью сбрасываем состояние
    
    # Убираем кнопки у текущего сообщения
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    
    # Отправляем новое стартовое сообщение
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    key_know = types.InlineKeyboardButton(text="📊 Узнать", callback_data="action_know")
    key_record = types.InlineKeyboardButton(text="✏️ Записать", callback_data="action_record")
    keyboard.add(key_know, key_record)
    
    bot.send_message(
        user_id,
        "👋 Действие отменено. Что хотите сделать?",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('action_'))
def handle_action(call):
    """Обработка выбора действия (Узнать/Записать)"""
    user_id = call.from_user.id
    action = call.data.replace('action_', '')
    
    user_states[user_id]['action'] = action
    user_states[user_id]['working_message_id'] = call.message.message_id
    
    # Показываем список отделений с кнопкой отмены
    show_departments(call.message)

def show_departments(message):
    """Показать список отделений"""
    session = Session()
    try:
        departments = session.query(models.Departments).all()
        
        if not departments:
            bot.send_message(message.chat.id, "❌ Нет отделений в базе")
            start_new_cycle(message.chat.id)
            return
        
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for dept in departments:
            btn = types.InlineKeyboardButton(
                text=dept.name,
                callback_data=f"dept_{dept.id}"
            )
            keyboard.add(btn)
        
        # Добавляем кнопку отмены
        keyboard = add_cancel_button(keyboard)
        
        bot.edit_message_text(
            "🏢 Выберите отделение:",
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=keyboard
        )
    finally:
        session.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith('dept_'))
def handle_department(call):
    """Обработка выбора отделения"""
    user_id = call.from_user.id
    department_id = int(call.data.replace('dept_', ''))
    
    user_states[user_id]['department_id'] = department_id
    
    # Показываем список групп с кнопкой отмены
    show_groups(call.message, department_id)

def show_groups(message, department_id):
    """Показать список групп отделения"""
    session = Session()
    try:
        groups = session.query(models.Group).filter(
            models.Group.id_departments == department_id
        ).all()
        
        if not groups:
            bot.send_message(message.chat.id, "❌ Нет групп в этом отделении")
            # Возвращаемся к выбору отделения
            show_departments(message)
            return
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        for group in groups:
            btn = types.InlineKeyboardButton(
                text=group.cipher,
                callback_data=f"group_{group.id}"
            )
            keyboard.add(btn)
        
        # Кнопка "Назад к отделениям"
        back_btn = types.InlineKeyboardButton(
            text="◀️ Назад к отделениям",
            callback_data="back_to_departments"
        )
        keyboard.add(back_btn)
        
        # Добавляем кнопку отмены
        keyboard = add_cancel_button(keyboard)
        
        send_or_edit_message(
            bot,
            "👥 Выберите группу:",
            message.chat.id,
            message.message_id,
            message.from_user.id,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    finally:
        session.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_'))
def handle_group(call):
    """Обработка выбора группы"""
    user_id = call.from_user.id
    group_id = int(call.data.replace('group_', ''))
    
    user_states[user_id]['group_id'] = group_id
    action = user_states[user_id].get('action')
    
    if action == 'record':
        # Для записи - показываем подтверждение выбора группы
        show_group_confirmation(call.message, user_id, group_id)
    else:
        # Для просмотра - показываем данные
        show_contingent_and_restart(call.message, user_id, group_id)

def show_group_confirmation(message, user_id, group_id):
    """Показать подтверждение выбора группы для записи"""
    session = Session()
    try:
        group = session.query(models.Group).filter(models.Group.id == group_id).first()
        department = session.query(models.Departments).filter(
            models.Departments.id == group.id_departments
        ).first() if group else None
        
        text = f"✏️ *Запись данных*\n\n"
        text += f"👥 Группа: {group.cipher}\n"
        text += f"🏢 Отделение: {department.name if department else 'Неизвестно'}\n\n"
        text += "Подтвердите выбор или вернитесь назад:"
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        confirm_btn = types.InlineKeyboardButton(
            text="✅ Подтвердить",
            callback_data=f"confirm_record_{group_id}"
        )
        back_btn = types.InlineKeyboardButton(
            text="◀️ Назад к группам",
            callback_data=f"back_to_groups_{group.id_departments}"
        )
        cancel_btn = types.InlineKeyboardButton(
            text="❌ В начало",
            callback_data="cancel_action"
        )
        keyboard.add(confirm_btn, back_btn)
        keyboard.add(cancel_btn)
        
        send_or_edit_message(
            bot,
            text,
            message.chat.id,
            message.message_id,
            message.from_user.id,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    finally:
        session.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_record_'))
def handle_confirm_record(call):
    """Подтверждение записи - переход к вводу данных"""
    user_id = call.from_user.id
    group_id = int(call.data.replace('confirm_record_', ''))
    
    user_states[user_id]['group_id'] = group_id
    
    # Убираем кнопки у текущего сообщения
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    
    # Отправляем сообщение с запросом ввода и кнопкой отмены
    keyboard = get_cancel_keyboard()
    
    bot.send_message(
        user_id,
        "📝 Введите дату и количество в формате:\n`дд.мм.гггг количество`\n\nПример: `15.03.2024 25`",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    # Регистрируем следующий шаг
    bot.register_next_step_handler_by_chat_id(user_id, process_record)

def show_contingent_and_restart(message, user_id, group_id):
    """Показать данные и перезапустить с новым стартовым сообщением"""
    session = Session()
    try:
        contingent = session.query(models.Contingent).filter(
            models.Contingent.id_groups == group_id
        ).order_by(models.Contingent.date.desc()).all()
        
        group = session.query(models.Group).filter(models.Group.id == group_id).first()
        department = session.query(models.Departments).filter(
            models.Departments.id == group.id_departments
        ).first() if group else None
        
        header = f"📊 *Данные по группе {group.cipher}*\n"
        if department:
            header += f"🏢 Отделение: {department.name}\n\n"
        
        if contingent:
            text = header
            for item in contingent:
                date_str = item.date.strftime('%d.%m.%Y') if item.date else 'Н/Д'
                text += f"📅 {date_str}: {item.number_of_students} чел.\n"
        else:
            text = header + "\n📭 Нет данных по этой группе"
        
        # Добавляем подсказку для дальнейших действий
        text += "\n\n---\n_Выберите действие в новом меню ниже_"
        
        send_or_edit_message(
            bot,
            text,
            message.chat.id,
            message.message_id,
            message.from_user.id,
            parse_mode='Markdown'
        )
        
        # Запускаем новый цикл
        start_new_cycle(user_id)
        
    finally:
        session.close()

def process_record(message):
    """Обработка ввода данных для записи"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Проверяем, не нажал ли пользователь кнопку отмены
    if message.text and message.text.startswith('/'):
        # Если пользователь ввел команду - обрабатываем её
        bot.process_new_messages([message])
        return
    
    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("Неверный формат. Нужно: дата количество")
        
        date_str, count_str = parts
        
        try:
            record_date = datetime.strptime(date_str, '%d.%m.%Y').date()
        except ValueError:
            raise ValueError("Неверный формат даты. Используйте ДД.ММ.ГГГГ")
        
        try:
            count = int(count_str)
            if count < 0:
                raise ValueError("Количество не может быть отрицательным")
        except ValueError:
            raise ValueError("Количество должно быть целым числом")
        
        session = Session()
        try:
            contingent = models.Contingent(
                id_groups=user_states[user_id]['group_id'],
                date=record_date,
                number_of_students=count
            )
            session.add(contingent)
            session.commit()
            
            group = session.query(models.Group).filter(
                models.Group.id == user_states[user_id]['group_id']
            ).first()
            
            # Отправляем подтверждение
            bot.send_message(
                user_id,
                f"✅ *Данные сохранены!*\n"
                f"👥 Группа: {group.cipher if group else 'Неизвестно'}\n"
                f"📅 Дата: {date_str}\n"
                f"👤 Количество: {count} чел.",
                parse_mode='Markdown'
            )
            
            # Спрашиваем, хочет ли пользователь добавить еще
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            yes_btn = types.InlineKeyboardButton(
                text="✅ Да, добавить еще",
                callback_data=f"add_more_{user_states[user_id]['group_id']}"
            )
            no_btn = types.InlineKeyboardButton(
                text="❌ Нет, в меню",
                callback_data="cancel_action"
            )
            keyboard.add(yes_btn, no_btn)
            
            bot.send_message(
                user_id,
                "Хотите добавить еще запись для этой группы?",
                reply_markup=keyboard
            )
            
        except Exception as e:
            session.rollback()
            bot.send_message(user_id, f"❌ Ошибка сохранения: {e}")
            # Возвращаем к вводу
            retry_input(user_id)
        finally:
            session.close()
            
    except Exception as e:
        # При ошибке формата - просим повторить с кнопкой отмены
        retry_input(user_id, str(e))

def retry_input(user_id, error_msg=None):
    """Повторить ввод данных с возможностью отмены"""
    keyboard = get_cancel_keyboard()
    
    text = "📝 Попробуйте снова в формате `дд.мм.гггг количество`:\n\nПример: `15.03.2024 25`"
    if error_msg:
        text = f"❌ *Ошибка:* {error_msg}\n\n{text}"
    
    msg = bot.send_message(
        user_id,
        text,
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    bot.register_next_step_handler(msg, process_record)

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_more_'))
def handle_add_more(call):
    """Обработка кнопки 'Добавить еще'"""
    user_id = call.from_user.id
    group_id = int(call.data.replace('add_more_', ''))
    
    user_states[user_id]['group_id'] = group_id
    
    # Убираем кнопки у текущего сообщения
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    
    # Запрашиваем новые данные с кнопкой отмены
    keyboard = get_cancel_keyboard()
    msg = bot.send_message(
        user_id,
        "📝 Введите дату и количество в формате:\n`дд.мм.гггг количество`\n\nПример: `15.03.2024 25`",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    bot.register_next_step_handler(msg, process_record)

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_departments')
def handle_back_to_departments(call):
    """Обработка кнопки 'Назад к отделениям'"""
    show_departments(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('back_to_groups_'))
def handle_back_to_groups(call):
    """Обработка кнопки 'Назад к группам'"""
    department_id = int(call.data.replace('back_to_groups_', ''))
    show_groups(call.message, department_id)

def start_new_cycle(user_id):
    """Отправить новое стартовое сообщение и подготовить состояние"""
    
    # ВАЖНО: Сбрасываем состояние, но сохраняем факт, что бот активен
    if user_id not in user_states:
        user_states[user_id] = {}
    
    # Очищаем предыдущие данные, но оставляем запись о пользователе
    user_states[user_id] = {
        'active': True  # Просто маркер, что пользователь есть
    }
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    key_know = types.InlineKeyboardButton(text="📊 Узнать", callback_data="action_know")
    key_record = types.InlineKeyboardButton(text="✏️ Записать", callback_data="action_record")
    keyboard.add(key_know, key_record)
    
    msg = bot.send_message(
        user_id,
        "👋 Что хотите сделать дальше?\nМожете узнать данные или записать новые:",
        reply_markup=keyboard
    )
    
    # Сохраняем ID этого сообщения
    user_states[user_id]['last_bot_message_id'] = msg.message_id

# ========== GPT ОБРАБОТЧИКИ ==========
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """
    Обрабатывает ВСЕ текстовые сообщения, которые не команды
    """
    user_id = message.from_user.id
    text = message.text
    
    # Игнорируем команды (начинаются с /)
    if text.startswith('/'):
        return
    
    # Если пользователь в процессе ввода данных (ждем дату/количество)
    if user_id in user_states and user_states[user_id].get('awaiting_input'):
        # Пропускаем, пусть process_record обрабатывает
        return
    
    # Отправляем в GPT
    process_with_gpt(text, user_id, bot, message)

@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    """
    Обрабатывает голосовые сообщения
    """
    process_voice(message, bot)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_ai_add_'))
def handle_ai_confirm(call):
    """
    Подтверждение добавления данных от GPT
    """
    user_id = call.from_user.id
    
    # Парсим данные: confirm_ai_add_GROUPID_DATE_COUNT
    parts = call.data.replace('confirm_ai_add_', '').split('_')
    group_id = int(parts[0])
    date_str = parts[1]
    count = int(parts[2])
    
    # Сохраняем в user_states
    user_states[user_id] = {
        'action': 'record',
        'group_id': group_id
    }
    
    # Убираем кнопки
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    
    # Парсим дату
    try:
        record_date = datetime.strptime(date_str, '%d.%m.%Y').date()
    except:
        record_date = datetime.now().date()
        date_str = record_date.strftime('%d.%m.%Y')
    
    # Сохраняем
    session = Session()
    try:
        contingent = models.Contingent(
            id_groups=group_id,
            date=record_date,
            number_of_students=count
        )
        session.add(contingent)
        session.commit()
        
        group = session.query(models.Group).filter(models.Group.id == group_id).first()
        
        bot.send_message(
            user_id,
            f"✅ *Данные сохранены!*\n"
            f"👥 Группа: {group.cipher}\n"
            f"📅 Дата: {date_str}\n"
            f"👤 Количество: {count} чел.",
            parse_mode='Markdown'
        )
        
        start_new_cycle(user_id)
        
    except Exception as e:
        session.rollback()
        bot.send_message(user_id, f"❌ Ошибка сохранения: {e}")
        start_new_cycle(user_id)
    finally:
        session.close()


def safe_polling(bot):
    """
    Безопасный polling с автоматическим перезапуском при сетевых ошибках
    """
    while True:
        try:
            print("🔄 Бот запущен и ожидает сообщения...")
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except (ReadTimeout, ConnectionError) as e:
            print(f"⚠️ Сетевая ошибка: {e}")
            print("🔄 Перезапуск через 5 секунд...")
            time.sleep(5)
            continue
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")
            traceback.print_exc()
            print("🔄 Перезапуск через 10 секунд...")
            time.sleep(10)
            continue

# Запуск бота
if __name__ == '__main__':
    print("🤖 Бот запущен...")

    # Проверяем GigaChat
    if check_gigachat_connection():
        print("✅ GigaChat подключен")
    else:
        print("⚠️ GigaChat не отвечает, но бот продолжит работу")
    print("✅ Голосовой ввод активен")
    print("Нажми Ctrl+C для остановки")
    
    # Запускаем с защитой
    safe_polling(bot)