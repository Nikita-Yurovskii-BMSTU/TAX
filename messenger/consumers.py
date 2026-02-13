import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import ChatRoom, Message, MediaFile

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            self.chat_id = self.scope['url_route']['kwargs']['chat_id']
            self.room_group_name = f'chat_{self.chat_id}'

            if await self.is_participant():
                await self.channel_layer.group_add(
                    self.room_group_name,
                    self.channel_name
                )
                await self.accept()
                await self.update_user_status(True)
            else:
                await self.close()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

        if self.user.is_authenticated:
            await self.update_user_status(False)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'chat_message':
                message = data.get('message', '').strip()
                if message:
                    saved_message = await self.save_message(message)

                    # ОТПРАВЛЯЕМ В ГРУППУ - ЭТО КЛЮЧЕВОЕ!
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'chat_message',
                            'message': message,
                            'sender_id': self.user.id,
                            'sender_username': self.user.username,
                            'timestamp': saved_message.timestamp.isoformat(),
                            'message_id': saved_message.id,
                        }
                    )

            elif message_type == 'media_message':
                # Получаем данные медиа из БД после загрузки
                message_id = data.get('message_id')
                if message_id:
                    media_data = await self.get_media_data(message_id)
                    if media_data:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                'type': 'media_message',
                                'sender_id': self.user.id,
                                'sender_username': self.user.username,
                                'message_id': message_id,
                                'media': media_data,
                                'content': data.get('caption', '')
                            }
                        )

            elif message_type == 'voice_message':
                message_id = data.get('message_id')
                if message_id:
                    voice_data = await self.get_voice_data(message_id)
                    if voice_data:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                'type': 'voice_message',
                                'sender_id': self.user.id,
                                'sender_username': self.user.username,
                                'message_id': message_id,
                                'voice': voice_data
                            }
                        )

            elif message_type == 'typing':
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'typing',
                        'user_id': self.user.id,
                        'username': self.user.username,
                        'is_typing': data.get('is_typing', False)
                    }
                )

        except Exception as e:
            print(f"Ошибка в WebSocket: {e}")

    async def chat_message(self, event):
        """Отправка текстового сообщения"""
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'sender_id': event['sender_id'],
            'sender_username': event['sender_username'],
            'timestamp': event['timestamp'],
            'message_id': event['message_id'],
        }))

    async def media_message(self, event):
        """Отправка медиа-сообщения"""
        await self.send(text_data=json.dumps({
            'type': 'media_message',
            'sender_id': event['sender_id'],
            'sender_username': event['sender_username'],
            'message_id': event['message_id'],
            'media': event['media'],
            'content': event.get('content', '')
        }))

    async def voice_message(self, event):
        """Отправка голосового сообщения"""
        await self.send(text_data=json.dumps({
            'type': 'voice_message',
            'sender_id': event['sender_id'],
            'sender_username': event['sender_username'],
            'message_id': event['message_id'],
            'voice': event['voice']
        }))

    async def typing(self, event):
        """Индикатор набора текста"""
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'user_id': event['user_id'],
            'username': event['username'],
            'is_typing': event['is_typing']
        }))

    @database_sync_to_async
    def is_participant(self):
        try:
            chat = ChatRoom.objects.get(id=self.chat_id)
            return self.user in chat.participants.all()
        except ChatRoom.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, content):
        chat = ChatRoom.objects.get(id=self.chat_id)
        message = Message.objects.create(
            chat=chat,
            sender=self.user,
            content=content
        )
        chat.updated_at = message.timestamp
        chat.save()
        return message

    @database_sync_to_async
    def get_media_data(self, message_id):
        """Получение данных медиафайла для отправки"""
        try:
            message = Message.objects.select_related('media_file').get(id=message_id)
            if message.media_file:
                return {
                    'id': message.media_file.id,
                    'url': message.media_file.file.url,
                    'thumbnail_url': message.media_file.get_thumbnail_url(),
                    'type': message.media_file.file_type,
                    'name': message.media_file.file_name,
                    'size': message.media_file.get_file_size_display(),
                }
        except Message.DoesNotExist:
            return None
        return None

    @database_sync_to_async
    def get_voice_data(self, message_id):
        """Получение данных голосового сообщения"""
        try:
            message = Message.objects.select_related('media_file').get(id=message_id)
            if message.media_file and message.media_file.file_type == 'voice':
                return {
                    'id': message.media_file.id,
                    'url': message.media_file.file.url,
                    'duration': message.media_file.duration,
                    'size': message.media_file.get_file_size_display(),
                }
        except Message.DoesNotExist:
            return None
        return None

    @database_sync_to_async
    def update_user_status(self, online):
        try:
            user = User.objects.get(id=self.user.id)
            user.online = online
            user.save()
        except User.DoesNotExist:
            pass