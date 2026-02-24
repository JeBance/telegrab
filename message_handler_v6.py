#!/usr/bin/env python3
"""
Telegrab v6.0 - Обработчик новых сообщений
Поддержка RAW + Meta архитектуры, отслеживание редактирований и удалений
"""

import logging
from datetime import datetime
from save_v6 import save_message_v6, check_message_edited_v6
from database_v6 import db_v6

logger = logging.getLogger('telegrab')


class MessageHandlerV6:
    """
    Обработчик новых сообщений для Telegrab v6.0
    
    Функции:
    - Сохранение новых сообщений в формате RAW + Meta
    - Отслеживание редактирований
    - Отслеживание удалений
    - WebSocket уведомления
    """
    
    def __init__(self, manager=None):
        """
        Инициализация обработчика
        
        Args:
            manager: WebSocket менеджер для уведомлений
        """
        self.manager = manager
        self.processed_messages = set()  # Кэш обработанных сообщений
        self.max_cache_size = 10000
    
    async def handle_new_message(self, event):
        """
        Обработка нового сообщения
        
        Args:
            event: Событие NewMessage от Telethon
        """
        try:
            message = event.message
            chat_id = event.chat_id
            
            # Уникальный ключ сообщения
            msg_key = f"{chat_id}_{message.id}"
            
            # Проверяем не обработано ли уже
            if msg_key in self.processed_messages:
                logger.debug(f"Сообщение {msg_key} уже обработано")
                return
            
            # Проверяем размер кэша
            if len(self.processed_messages) > self.max_cache_size:
                # Удаляем половину старых записей
                self.processed_messages = set(list(self.processed_messages)[self.max_cache_size // 2:])
            
            # Получаем информацию о чате
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or f"chat_{chat_id}"
            
            logger.info(f"📩 Новое сообщение в чате {chat_title}: {message.text[:50] if message.text else '[медиа]'}...")
            
            # 1. Проверяем редактирование (если сообщение уже было в БД)
            edited = check_message_edited_v6(message, chat_id, message.id)
            if edited:
                logger.info(f"✏️ Сообщение {message.id} отредактировано")
                await self._send_edit_notification(message, chat_id, chat_title)
            
            # 2. Сохраняем сообщение
            saved = save_message_v6(message, chat_id, chat_title)
            
            if saved:
                logger.info(f"✅ Сообщение сохранено в БД: {message.id}")
                
                # 3. Отправляем WebSocket уведомление
                await self._send_new_message_notification(message, chat_id, chat_title)
                
                # 4. Добавляем в кэш
                self.processed_messages.add(msg_key)
            else:
                logger.warning(f"⚠️ Не удалось сохранить сообщение {message.id}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}", exc_info=True)
    
    async def _send_new_message_notification(self, message, chat_id: int, chat_title: str):
        """Отправка уведомления о новом сообщении через WebSocket"""
        if not self.manager:
            return
        
        # Определяем тип медиа
        media_type = None
        if message.photo:
            media_type = 'photo'
        elif message.video:
            media_type = 'video'
        elif message.document:
            media_type = 'document'
        
        # Формируем уведомление
        notification = {
            'type': 'new_message',
            'message': {
                'message_id': message.id,
                'chat_id': chat_id,
                'chat_title': chat_title,
                'text': message.text[:500] if message.text else f"[{media_type}]" if media_type else "[без текста]",
                'sender_name': await self._get_sender_name(message),
                'message_date': message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date),
                'has_media': media_type is not None,
                'media_type': media_type,
                'views': getattr(message, 'views', None)
            }
        }
        
        await self.manager.broadcast(notification)
    
    async def _send_edit_notification(self, message, chat_id: int, chat_title: str):
        """Отправка уведомления об редактировании сообщения"""
        if not self.manager:
            return
        
        notification = {
            'type': 'message_edited',
            'message': {
                'message_id': message.id,
                'chat_id': chat_id,
                'chat_title': chat_title,
                'text': message.text[:500] if message.text else '',
                'edit_date': message.edit_date.isoformat() if hasattr(message, 'edit_date') and message.edit_date else None
            }
        }
        
        await self.manager.broadcast(notification)
    
    async def _get_sender_name(self, message):
        """Получение имени отправителя"""
        try:
            sender = await message.get_sender()
            if sender:
                return getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')
        except:
            pass
        return 'Unknown'
    
    async def check_deleted_messages(self, client, chat_id: int):
        """
        Проверка удалённых сообщений в чате
        
        Args:
            client: Telethon клиент
            chat_id: ID чата для проверки
        """
        try:
            # Получаем последние message_id из БД
            messages_from_db = db_v6.get_messages(chat_id=chat_id, limit=100)
            
            if not messages_from_db:
                return
            
            # Проверяем каждое сообщение
            for msg_data in messages_from_db:
                message_id = msg_data['message_id']
                
                try:
                    # Пытаемся получить сообщение
                    msg = await client.get_messages(chat_id, ids=message_id)
                    
                    if not msg or (hasattr(msg, 'text') and not msg.text and not msg.media):
                        # Сообщение удалено
                        logger.info(f"🗑️ Сообщение {message_id} удалено из чата {chat_id}")
                        db_v6.mark_message_deleted(chat_id, message_id)
                        
                        # Отправляем уведомление
                        if self.manager:
                            await self.manager.broadcast({
                                'type': 'message_deleted',
                                'chat_id': chat_id,
                                'message_id': message_id
                            })
                
                except Exception as e:
                    # Ошибка при получении = сообщение удалено
                    logger.debug(f"Сообщение {message_id} недоступно: {e}")
                    db_v6.mark_message_deleted(chat_id, message_id)
                    
        except Exception as e:
            logger.error(f"Ошибка проверки удалённых сообщений: {e}")


# Глобальный обработчик
message_handler_v6 = MessageHandlerV6()
