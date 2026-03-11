import io
import speech_recognition as sr
from pydub import AudioSegment

def voice_to_text(voice_file_content):
    """
    Конвертирует голосовое сообщение в текст
    Возвращает распознанный текст или None при ошибке
    """
    try:
        # Конвертируем OGG (Telegram) в WAV
        audio = AudioSegment.from_ogg(io.BytesIO(voice_file_content))
        wav_data = io.BytesIO()
        audio.export(wav_data, format='wav')
        
        # Распознаем речь
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_data) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language='ru-RU')
        
        return text
        
    except sr.UnknownValueError:
        return None  # не удалось распознать
    except Exception as e:
        print(f"Ошибка распознавания: {e}")
        return None

def process_voice(message, bot):
    """
    Обрабатывает голосовое сообщение:
    1. Скачивает
    2. Распознает
    3. Отправляет в GPT
    """
    user_id = message.from_user.id
    
    # Показываем, что обрабатываем
    processing_msg = bot.send_message(
        user_id,
        "🎤 Распознаю голосовое сообщение..."
    )
    
    try:
        # Скачиваем файл
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Распознаем
        text = voice_to_text(downloaded_file)
        
        # Удаляем сообщение о процессе
        bot.delete_message(user_id, processing_msg.message_id)
        
        if text:
            # Показываем, что распознали
            bot.send_message(
                user_id,
                f"📝 Распознано: _{text}_",
                parse_mode='Markdown'
            )
            
            # Отправляем в GPT-помощник
            from ai_assistant import process_with_gpt
            process_with_gpt(text, user_id, bot, message)
        else:
            bot.send_message(
                user_id,
                "❌ Не удалось распознать голосовое сообщение.\n"
                "Попробуйте говорить четче или напишите текстом."
            )
            
    except Exception as e:
        bot.edit_message_text(
            f"❌ Ошибка: {e}",
            user_id,
            processing_msg.message_id
        )