#!/usr/bin/env python3
"""
Telegrab v6.0 - API Endpoints
Новые endpoints для работы с архитектурой RAW + Meta
"""

import json
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Query, Security
from fastapi.security import APIKeyHeader

# ============================================================
# V6 API ROUTER
# ============================================================

def create_v6_routes(app: FastAPI, get_api_key, db_v6, CONFIG):
    """
    Создание API routes для v6.0
    
    Args:
        app: FastAPI приложение
        get_api_key: Функция проверки API ключа
        db_v6: Экземпляр DatabaseV6
        CONFIG: Конфигурация
    """
    
    # ============================================================
    # СТАТИСТИКА V6
    # ============================================================
    @app.get("/v6/stats")
    async def get_v6_stats(api_key: str = Depends(get_api_key)):
        """Получение статистики v6.0"""
        stats = db_v6.get_stats()
        return {
            'version': '6.0',
            'architecture': 'RAW + Meta',
            **stats
        }
    
    # ============================================================
    # ЧАТЫ V6
    # ============================================================
    @app.get("/v6/chats")
    async def get_v6_chats(
        api_key: str = Depends(get_api_key),
        limit: int = Query(100, ge=1, le=1000)
    ):
        """Получение списка чатов v6.0"""
        chats = db_v6.get_all_chats()[:limit]
        
        # Форматируем ответ
        formatted_chats = []
        for chat in chats:
            formatted_chats.append({
                'chat_id': chat['chat_id'],
                'title': chat['title'],
                'username': chat.get('username'),
                'type': chat.get('type'),
                'updated_at': chat.get('updated_at')
            })
        
        return {'count': len(formatted_chats), 'chats': formatted_chats}
    
    @app.get("/v6/chats/{chat_id}")
    async def get_v6_chat(
        chat_id: int,
        api_key: str = Depends(get_api_key)
    ):
        """Получение информации о чате"""
        chat = db_v6.get_chat(chat_id)
        
        if not chat:
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        return chat
    
    # ============================================================
    # СООБЩЕНИЯ V6
    # ============================================================
    @app.get("/v6/messages")
    async def get_v6_messages(
        chat_id: Optional[int] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        search: Optional[str] = Query(None),
        media_type: Optional[str] = Query(None),
        api_key: str = Depends(get_api_key)
    ):
        """
        Получение сообщений v6.0
        
        Параметры:
        - chat_id: Фильтр по чату
        - limit: Лимит сообщений
        - offset: Смещение
        - search: Поисковый запрос
        - media_type: Фильтр по типу медиа (photo, video, document, etc.)
        """
        messages = db_v6.get_messages(
            chat_id=chat_id,
            limit=limit,
            offset=offset,
            search=search,
            media_type=media_type
        )
        
        # Форматируем ответ
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                'message_id': msg['message_id'],
                'chat_id': msg['chat_id'],
                'sender_name': msg.get('sender_name'),
                'message_date': msg.get('message_date'),
                'text': msg.get('text_preview'),
                'has_media': bool(msg.get('has_media')),
                'media_type': msg.get('media_type'),
                'views': msg.get('views')
            })
        
        return {
            'count': len(formatted_messages),
            'messages': formatted_messages
        }
    
    @app.get("/v6/messages/{chat_id}/{message_id}")
    async def get_v6_message(
        chat_id: int,
        message_id: int,
        api_key: str = Depends(get_api_key)
    ):
        """Получение конкретного сообщения с RAW данными"""
        msg = db_v6.get_message_raw(chat_id, message_id)
        
        if not msg:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        return msg
    
    @app.get("/v6/messages/{chat_id}/{message_id}/raw")
    async def get_v6_message_raw(
        chat_id: int,
        message_id: int,
        api_key: str = Depends(get_api_key)
    ):
        """Получение RAW JSON дампа сообщения"""
        msg = db_v6.get_message_raw(chat_id, message_id)
        
        if not msg:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        return {
            'chat_id': chat_id,
            'message_id': message_id,
            'raw_data': msg.get('raw_data'),
            'saved_at': msg.get('saved_at')
        }
    
    # ============================================================
    # МЕДИА V6
    # ============================================================
    @app.get("/v6/media")
    async def get_v6_media(
        chat_id: Optional[int] = Query(None),
        media_type: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        api_key: str = Depends(get_api_key)
    ):
        """Получение сообщений с медиа"""
        messages = db_v6.get_messages(
            chat_id=chat_id,
            media_type=media_type,
            limit=limit
        )
        
        return {
            'count': len(messages),
            'messages': messages
        }
    
    # ============================================================
    # ИСТОРИЯ РЕДАКТИРОВАНИЙ V6
    # ============================================================
    @app.get("/v6/edits/{chat_id}/{message_id}")
    async def get_message_edits(
        chat_id: int,
        message_id: int,
        api_key: str = Depends(get_api_key)
    ):
        """Получение истории редактирования сообщения"""
        conn = db_v6._get_connection() if hasattr(db_v6, '_get_connection') else None
        if not conn:
            import sqlite3
            conn = sqlite3.connect(db_v6.db_path)
        
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM message_edits
            WHERE chat_id = ? AND message_id = ?
            ORDER BY edit_date DESC
        ''', (chat_id, message_id))
        
        edits = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return {
            'chat_id': chat_id,
            'message_id': message_id,
            'edit_count': len(edits),
            'edits': edits
        }
    
    # ============================================================
    # СОБЫТИЯ V6
    # ============================================================
    @app.get("/v6/events")
    async def get_v6_events(
        chat_id: Optional[int] = Query(None),
        event_type: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        api_key: str = Depends(get_api_key)
    ):
        """Получение событий (удаления, etc.)"""
        conn = None
        try:
            import sqlite3
            conn = sqlite3.connect(db_v6.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = 'SELECT * FROM message_events WHERE 1=1'
            params = []
            
            if chat_id:
                query += ' AND chat_id = ?'
                params.append(chat_id)
            
            if event_type:
                query += ' AND event_type = ?'
                params.append(event_type)
            
            query += ' ORDER BY event_date DESC LIMIT ?'
            params.append(limit)
            
            cursor.execute(query, params)
            events = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return {
                'count': len(events),
                'events': events
            }
        except Exception as e:
            if conn:
                conn.close()
            raise HTTPException(status_code=500, detail=str(e))
    
    # ============================================================
    # ЭКСПОРТ V6
    # ============================================================
    @app.get("/v6/export/{chat_id}")
    async def export_chat_v6(
        chat_id: int,
        format: str = Query('json', pattern='^(json|raw|csv)$'),
        api_key: str = Depends(get_api_key)
    ):
        """
        Экспорт сообщений чата
        
        Форматы:
        - json: Красивый JSON с основными полями
        - raw: RAW JSON дампы всех сообщений
        - csv: CSV формат (текст)
        """
        export_data = db_v6.export_chat(chat_id, format)
        
        if format == 'raw':
            return {
                'chat_id': chat_id,
                'format': 'raw',
                'message_count': len(export_data),
                'messages': export_data
            }
        
        return export_data
    
    @app.post("/v6/export/{chat_id}/download")
    async def download_export_v6(
        chat_id: int,
        format: str = Query('json'),
        api_key: str = Depends(get_api_key)
    ):
        """Скачивание экспорта в виде файла"""
        from fastapi.responses import JSONResponse
        import json
        
        export_data = db_v6.export_chat(chat_id, format)
        
        filename = f"telegrab_chat_{chat_id}_export.json"
        
        return JSONResponse(
            content=export_data,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
    
    # ============================================================
    # ПОИСК V6
    # ============================================================
    @app.get("/v6/search")
    async def search_v6(
        q: str = Query(..., min_length=1),
        chat_id: Optional[int] = Query(None),
        limit: int = Query(50, ge=1, le=500),
        api_key: str = Depends(get_api_key)
    ):
        """
        Полнотекстовый поиск по сообщениям
        
        Поиск осуществляется по:
        - Тексту сообщений
        - Метаданным
        """
        messages = db_v6.get_messages(
            chat_id=chat_id,
            search=q,
            limit=limit
        )
        
        # Подсветка найденного текста
        for msg in messages:
            text = msg.get('text_preview', '')
            if q.lower() in text.lower():
                msg['match_highlighted'] = True
        
        return {
            'query': q,
            'count': len(messages),
            'results': messages
        }
    
    # ============================================================
    # УДАЛЁННЫЕ СООБЩЕНИЯ V6
    # ============================================================
    @app.get("/v6/deleted")
    async def get_deleted_messages(
        chat_id: Optional[int] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        api_key: str = Depends(get_api_key)
    ):
        """Получение удалённых сообщений"""
        conn = None
        try:
            import sqlite3
            conn = sqlite3.connect(db_v6.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = '''
                SELECT m.chat_id, m.message_id, meta.sender_name, 
                       meta.message_date, meta.text_preview, 
                       meta.deleted_at
                FROM message_meta meta
                JOIN messages_raw m ON m.chat_id = meta.chat_id AND m.message_id = meta.message_id
                WHERE meta.is_deleted = 1
            '''
            params = []
            
            if chat_id:
                query += ' AND m.chat_id = ?'
                params.append(chat_id)
            
            query += ' ORDER BY meta.deleted_at DESC LIMIT ?'
            params.append(limit)
            
            cursor.execute(query, params)
            deleted = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return {
                'count': len(deleted),
                'messages': deleted
            }
        except Exception as e:
            if conn:
                conn.close()
            raise HTTPException(status_code=500, detail=str(e))
