#!/usr/bin/env python3
"""
Telegrab v6.0 - Функции сохранения сообщений
Архитектура RAW + Meta
"""

import logging
from datetime import datetime
from database_v6 import db_v6

logger = logging.getLogger('telegrab')


def save_message_v6(message, chat_id: int, chat_title: str):
    """
    Сохранение сообщения в формате RAW + Meta (v6.0)
    
    Args:
        message: Объект сообщения Telethon
        chat_id: ID чата
        chat_title: Название чата
    
    Returns:
        bool: True если сообщение сохранено
    """
    try:
        # 1. Определяем тип медиа
        media_type = None
        file_id = None
        file_name = None
        file_size = None
        
        if message.photo:
            media_type = 'photo'
            file_id = str(message.photo.id) if hasattr(message.photo, 'id') else None
        elif message.video:
            media_type = 'video'
            file_id = str(message.video.id) if hasattr(message.video, 'id') else None
            file_size = message.video.size if hasattr(message.video, 'size') else None
            file_name = f"video_{message.id}.mp4"
        elif message.document:
            media_type = 'document'
            file_id = str(message.document.id) if hasattr(message.document, 'id') else None
            file_size = message.document.size if hasattr(message.document, 'size') else None
            file_name = message.document.file_name if hasattr(message.document, 'file_name') else None
        elif message.audio:
            media_type = 'audio'
            file_id = str(message.audio.id) if hasattr(message.audio, 'id') else None
            file_size = message.audio.size if hasattr(message.audio, 'size') else None
        elif message.voice:
            media_type = 'voice'
            file_id = str(message.voice.id) if hasattr(message.voice, 'id') else None
        elif message.sticker:
            media_type = 'sticker'
            file_id = str(message.sticker.id) if hasattr(message.sticker, 'id') else None
        elif message.gif:
            media_type = 'gif'
            file_id = str(message.gif.id) if hasattr(message.gif, 'id') else None
        
        # Пропускаем только системные сообщения без текста и медиа
        if not message.text and not media_type:
            return False
        
        # 2. Получаем текст
        text = message.text or ""
        if media_type and not text:
            text = f"[{media_type}]"
        
        # 3. Получаем отправителя
        sender = None
        sender_id = None
        sender_name = 'Unknown'
        try:
            sender = message.get_sender() if hasattr(message, 'get_sender') else None
            if sender:
                sender_id = getattr(sender, 'id', None)
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')
        except:
            pass
        
        # 4. Сохраняем чат
        chat_type = 'channel' if str(chat_id).startswith('-100') else 'private'
        db_v6.save_chat(
            chat_id=chat_id,
            title=chat_title,
            chat_type=chat_type
        )
        
        # 5. Формируем RAW данные
        raw_data = {}
        if hasattr(message, 'to_dict'):
            raw_data = message.to_dict()
        else:
            raw_data = {
                'id': message.id,
                'chat_id': chat_id,
                'chat_title': chat_title,
                'message': message.text,
                'date': message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date),
                'sender_id': sender_id,
                'sender_name': sender_name,
                'media': {
                    'type': media_type,
                    'file_id': file_id,
                    'file_name': file_name,
                    'file_size': file_size
                } if media_type else None
            }
        
        # 6. Формируем метаданные
        message_date = message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
        edit_date = None
        if hasattr(message, 'edit_date') and message.edit_date:
            edit_date = message.edit_date.isoformat()
        
        meta = {
            'sender_id': sender_id,
            'sender_name': sender_name,
            'message_date': message_date,
            'has_media': media_type is not None,
            'media_type': media_type,
            'text_preview': text[:500],
            'has_forward': hasattr(message, 'fwd_from') and message.fwd_from is not None,
            'has_reply': hasattr(message, 'reply_to') and message.reply_to is not None,
            'edit_date': edit_date,
            'views': getattr(message, 'views', None)
        }
        
        # 7. Формируем список файлов
        files_list = []
        if media_type and file_id:
            files_list.append({
                'file_id': file_id,
                'file_type': media_type,
                'file_size': file_size,
                'file_name': file_name
            })
        
        # 8. Сохраняем сообщение
        saved = db_v6.save_message_raw(
            chat_id=chat_id,
            message_id=message.id,
            raw_data=raw_data,
            meta=meta,
            files=files_list
        )
        
        if saved:
            media_log = f" с медиа: {media_type}" if media_type else ""
            logger.debug(f"Сохранено сообщение {message.id}{media_log}")
        
        return saved
        
    except Exception as e:
        logger.error(f"Ошибка сохранения сообщения v6: {e}")
        return False


def check_message_edited_v6(message, chat_id: int, message_id: int):
    """
    Проверка и сохранение истории редактирования
    
    Args:
        message: Объект сообщения Telethon
        chat_id: ID чата
        message_id: ID сообщения
    
    Returns:
        bool: True если сообщение было отредактировано
    """
    try:
        if not hasattr(message, 'edit_date') or not message.edit_date:
            return False
        
        edit_date = message.edit_date.isoformat()
        
        # Проверяем есть ли уже запись об этом редактировании
        conn = db_v6._get_connection() if hasattr(db_v6, '_get_connection') else None
        if not conn:
            import sqlite3
            conn = sqlite3.connect(db_v6.db_path)
        
        cursor = conn.cursor()
        cursor.execute('''
            SELECT edit_date FROM message_meta
            WHERE chat_id = ? AND message_id = ?
        ''', (chat_id, message_id))
        
        result = cursor.fetchone()
        if result and result[0] == edit_date:
            conn.close()
            return False  # Уже сохранено
        
        # Получаем старое сообщение из RAW
        old_data = db_v6.get_message_raw(chat_id, message_id)
        old_text = None
        if old_data and old_data.get('raw_data'):
            old_text = old_data['raw_data'].get('message')
        
        # Сохраняем редактирование
        new_text = message.text or ""
        db_v6.save_message_edit(
            chat_id=chat_id,
            message_id=message_id,
            old_text=old_text,
            new_text=new_text,
            old_raw_data=old_data.get('raw_data') if old_data else None
        )
        
        conn.close()
        logger.info(f"Сообщение {message_id} отредактировано")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка проверки редактирования: {e}")
        return False
