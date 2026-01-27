import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import ChatRoom, Message

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            self.chat_id = self.scope['url_route']['kwargs']['chat_id']
            self.room_group_name = f'chat_{self.chat_id}'

            # Проверяем, является ли пользователь участником чата
            if await self.is_participant():
                # Подключаемся к группе
                await self.channel_layer.group_add(
                    self.room_group_name,
                    self.channel_name
                )
                await self.accept()

                # Обновляем статус пользователя на онлайн
                await self.update_user_status(True)

                # Отправляем приветственное сообщение
                await self.send(text_data=json.dumps({
                    'type': 'system',
                    'message': 'Вы подключились к чату'
                }))
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

        # Обновляем статус пользователя на оффлайн
        if self.user.is_authenticated:
            await self.update_user_status(False)

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')

            if message_type == 'chat_message':
                message = text_data_json.get('message', '').strip()

                if message:
                    # Сохраняем сообщение в БД
                    saved_message = await self.save_message(message)

                    # Отправляем сообщение в группу
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

            elif message_type == 'typing':
                is_typing = text_data_json.get('is_typing', False)

                # Отправляем информацию о наборе текста в группу
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'typing',
                        'user_id': self.user.id,
                        'username': self.user.username,
                        'is_typing': is_typing
                    }
                )

        except json.JSONDecodeError:
            print("Ошибка декодирования JSON")
        except Exception as e:
            print(f"Ошибка обработки сообщения: {e}")

    async def chat_message(self, event):
        # Отправляем сообщение WebSocket
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'sender_id': event['sender_id'],
            'sender_username': event['sender_username'],
            'timestamp': event['timestamp'],
            'message_id': event['message_id'],
        }))

    async def typing(self, event):
        # Отправляем информацию о наборе текста
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
    def update_user_status(self, online):
        user = User.objects.get(id=self.user.id)
        user.online = online
        user.save()