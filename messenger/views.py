from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, FileResponse
from django.db.models import Q, Max, Count
from django.contrib.auth import get_user_model
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
import json
import os
import mimetypes
import io
import subprocess
import tempfile
from pathlib import Path
import struct

from .models import ChatRoom, Message, Contact, MediaFile
from accounts.models import CustomUser

User = get_user_model()


# ==================== ОСНОВНЫЕ VIEWS ====================

@login_required
def chat_list(request):
    """Список чатов пользователя"""
    chats = ChatRoom.objects.filter(participants=request.user).annotate(
        last_message_time=Max('messages__timestamp')
    ).order_by('-last_message_time', '-updated_at')

    return render(request, 'messenger/chat_list.html', {'chats': chats})


@login_required
def chat_detail(request, chat_id):
    """Детали чата с сообщениями"""
    chat = get_object_or_404(ChatRoom, id=chat_id, participants=request.user)
    messages = chat.messages.select_related('sender', 'media_file').order_by('timestamp')

    return render(request, 'messenger/chat_detail.html', {
        'chat': chat,
        'messages': messages,
        'max_file_size': 50 * 1024 * 1024,  # 50MB
    })


@login_required
def start_chat(request, user_id):
    """Начать чат с пользователем"""
    other_user = get_object_or_404(User, id=user_id)

    chat = ChatRoom.objects.filter(
        participants=request.user
    ).filter(
        participants=other_user
    ).filter(is_group=False).first()

    if not chat:
        chat = ChatRoom.objects.create(is_group=False)
        chat.participants.add(request.user, other_user)

    return redirect('chat_detail', chat_id=chat.id)


@login_required
def create_group_chat(request):
    """Создать групповой чат"""
    if request.method == 'POST':
        chat_name = request.POST.get('name')
        participant_ids = request.POST.getlist('participants')

        chat = ChatRoom.objects.create(
            name=chat_name,
            is_group=True
        )
        chat.participants.add(request.user)

        for user_id in participant_ids:
            user = User.objects.get(id=user_id)
            chat.participants.add(user)

        return redirect('chat_detail', chat_id=chat.id)

    users = User.objects.exclude(id=request.user.id)
    return render(request, 'messenger/create_group.html', {'users': users})


@login_required
def add_contact(request, user_id):
    """Добавить пользователя в контакты"""
    contact_user = get_object_or_404(User, id=user_id)
    Contact.objects.get_or_create(
        user=request.user,
        contact=contact_user
    )
    return redirect('user_list')


@login_required
def search_users(request):
    """Поиск пользователей"""
    query = request.GET.get('q', '')
    if query:
        users = User.objects.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query)
        ).exclude(id=request.user.id)
    else:
        users = User.objects.exclude(id=request.user.id)

    return render(request, 'messenger/search.html', {'users': users})


@login_required
def get_unread_count(request):
    """Количество непрочитанных сообщений"""
    unread_count = Message.objects.filter(
        chat__participants=request.user
    ).exclude(
        read_by=request.user
    ).exclude(
        sender=request.user
    ).count()

    return JsonResponse({'unread_count': unread_count})


# ==================== MEDIA VIEWS ====================

@login_required
@csrf_exempt
def upload_media(request, chat_id):
    """
    Загрузка медиафайла (фото, видео, документ)
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Метод не разрешен'
        }, status=405)

    try:
        chat = get_object_or_404(ChatRoom, id=chat_id, participants=request.user)

        if 'file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'Файл не найден'
            }, status=400)

        uploaded_file = request.FILES['file']
        caption = request.POST.get('caption', '').strip()

        # Проверка размера файла (макс 50MB)
        max_size = 50 * 1024 * 1024
        if uploaded_file.size > max_size:
            return JsonResponse({
                'success': False,
                'error': f'Файл слишком большой. Максимальный размер: 50MB'
            }, status=400)

        # Определяем тип файла по расширению
        file_type, mime_type = determine_file_type_by_extension(uploaded_file.name)

        if not file_type:
            return JsonResponse({
                'success': False,
                'error': 'Тип файла не поддерживается'
            }, status=400)

        # Создаем миниатюру для изображений
        thumbnail = None
        if file_type == 'image':
            thumbnail = create_image_thumbnail(uploaded_file)

        # Создаем запись в базе данных
        media_file = MediaFile.objects.create(
            chat=chat,
            sender=request.user,
            file=uploaded_file,
            file_type=file_type,
            file_name=uploaded_file.name,
            file_size=uploaded_file.size,
            mime_type=mime_type,
            caption=caption,
            thumbnail=thumbnail
        )

        # Создаем сообщение с медиафайлом
        message = Message.objects.create(
            chat=chat,
            sender=request.user,
            content=caption,
            media_file=media_file
        )

        # Обновляем статистику чата
        chat.update_media_stats()

        # Подготавливаем данные для ответа
        response_data = {
            'success': True,
            'message_id': message.id,
            'message': {
                'id': message.id,
                'sender_id': request.user.id,
                'sender_username': request.user.username,
                'content': caption,
                'timestamp': message.timestamp.isoformat(),
                'message_type': file_type,
                'has_media': True,
            },
            'media': {
                'id': media_file.id,
                'url': media_file.file.url,
                'thumbnail_url': media_file.get_thumbnail_url(),
                'type': file_type,
                'name': media_file.file_name,
                'size': media_file.get_file_size_display(),
                'caption': caption,
            }
        }

        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@csrf_exempt
def upload_voice_message(request, chat_id):
    """
    Загрузка голосового сообщения
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Метод не разрешен'
        }, status=405)

    try:
        chat = get_object_or_404(ChatRoom, id=chat_id, participants=request.user)

        if 'voice' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'Аудиофайл не найден'
            }, status=400)

        audio_file = request.FILES['voice']
        duration = int(request.POST.get('duration', 0))

        # Проверка размера (макс 10MB для голосовых)
        if audio_file.size > 10 * 1024 * 1024:
            return JsonResponse({
                'success': False,
                'error': 'Голосовое сообщение слишком большое'
            }, status=400)

        # Создаем уникальное имя файла
        original_name = audio_file.name
        if not original_name.lower().endswith(('.webm', '.mp3', '.wav', '.ogg', '.m4a')):
            original_name = f"voice_{int(timezone.now().timestamp())}.webm"

        # Создаем запись в базе данных
        media_file = MediaFile.objects.create(
            chat=chat,
            sender=request.user,
            file=audio_file,
            file_type='voice',
            file_name=original_name,
            file_size=audio_file.size,
            mime_type='audio/webm',
            duration=duration
        )

        # Создаем сообщение
        message = Message.objects.create(
            chat=chat,
            sender=request.user,
            content='🎤 Голосовое сообщение',
            media_file=media_file
        )

        # Обновляем статистику чата
        chat.update_media_stats()

        return JsonResponse({
            'success': True,
            'message_id': message.id,
            'message': {
                'id': message.id,
                'sender_id': request.user.id,
                'sender_username': request.user.username,
                'content': '🎤 Голосовое сообщение',
                'timestamp': message.timestamp.isoformat(),
                'message_type': 'voice',
                'has_media': True,
            },
            'voice': {
                'id': media_file.id,
                'url': media_file.file.url,
                'duration': duration,
                'size': media_file.get_file_size_display(),
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def media_gallery(request, chat_id):
    """
    HTML страница с галереей медиафайлов чата
    """
    chat = get_object_or_404(ChatRoom, id=chat_id, participants=request.user)

    # Получаем медиафайлы сгруппированные по типу
    media_files = MediaFile.objects.filter(
        chat=chat,
        is_deleted=False
    ).select_related('sender').order_by('-uploaded_at')

    # Группируем по типу для удобного отображения
    media_by_type = {
        'images': media_files.filter(file_type='image'),
        'videos': media_files.filter(file_type='video'),
        'documents': media_files.filter(file_type='document'),
        'audio': media_files.filter(file_type='audio'),
        'voice': media_files.filter(file_type='voice'),
    }

    return render(request, 'messenger/media_gallery.html', {
        'chat': chat,
        'media_by_type': media_by_type,
        'total_media': media_files.count(),
        'image_count': media_by_type['images'].count(),
        'video_count': media_by_type['videos'].count(),
        'document_count': media_by_type['documents'].count(),
    })

@login_required
def get_chat_media(request, chat_id):
    """
    Получить все медиафайлы чата
    """
    chat = get_object_or_404(ChatRoom, id=chat_id, participants=request.user)

    # Фильтруем по типу если указан
    file_type = request.GET.get('type', 'all')
    page = int(request.GET.get('page', 1))
    per_page = 20

    # Базовый queryset
    media_files = MediaFile.objects.filter(
        chat=chat,
        is_deleted=False
    ).select_related('sender')

    # Фильтрация по типу
    if file_type != 'all' and file_type in ['image', 'video', 'audio', 'document', 'voice']:
        media_files = media_files.filter(file_type=file_type)

    # Пагинация
    total_count = media_files.count()
    total_pages = (total_count + per_page - 1) // per_page

    media_files = media_files.order_by('-uploaded_at')[
                  (page - 1) * per_page: page * per_page
                  ]

    # Подготавливаем данные
    media_list = []
    for media in media_files:
        media_list.append({
            'id': media.id,
            'url': media.file.url,
            'thumbnail_url': media.get_thumbnail_url(),
            'type': media.file_type,
            'name': media.file_name,
            'size': media.get_file_size_display(),
            'duration': media.duration,
            'caption': media.caption,
            'timestamp': media.uploaded_at.isoformat(),
            'sender': {
                'id': media.sender.id,
                'username': media.sender.username,
            },
        })

    return JsonResponse({
        'success': True,
        'media': media_list,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
        }
    })


@login_required
def download_media(request, media_id):
    """
    Скачать медиафайл
    """
    media_file = get_object_or_404(MediaFile, id=media_id)

    # Проверяем доступ
    if not media_file.chat.participants.filter(id=request.user.id).exists():
        return HttpResponse('Доступ запрещен', status=403)

    # Увеличиваем счетчик скачиваний
    media_file.increment_downloads()

    # Отдаем файл
    response = FileResponse(media_file.file.open('rb'))

    # Угадываем MIME тип по расширению
    mime_type, _ = mimetypes.guess_type(media_file.file_name)
    response['Content-Type'] = mime_type or 'application/octet-stream'
    response['Content-Disposition'] = f'attachment; filename="{media_file.file_name}"'

    return response


@login_required
def view_media(request, media_id):
    """
    Просмотр медиафайла
    """
    media_file = get_object_or_404(MediaFile, id=media_id)

    # Проверяем доступ
    if not media_file.chat.participants.filter(id=request.user.id).exists():
        return HttpResponse('Доступ запрещен', status=403)

    # Увеличиваем счетчик просмотров
    media_file.increment_views()

    # Отдаем файл
    response = FileResponse(media_file.file.open('rb'))

    # Угадываем MIME тип
    mime_type, _ = mimetypes.guess_type(media_file.file_name)
    response['Content-Type'] = mime_type or 'application/octet-stream'
    response['Content-Disposition'] = f'inline; filename="{media_file.file_name}"'

    return response


@login_required
@csrf_exempt
def delete_media(request, media_id):
    """
    Удалить медиафайл (мягкое удаление)
    """
    if request.method not in ['DELETE', 'POST']:
        return JsonResponse({
            'success': False,
            'error': 'Метод не разрешен'
        }, status=405)

    try:
        media_file = get_object_or_404(MediaFile, id=media_id, sender=request.user)

        # Мягкое удаление
        media_file.soft_delete()

        # Обновляем статистику чата
        media_file.chat.update_media_stats()

        return JsonResponse({
            'success': True,
            'message': 'Файл удален'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def determine_file_type_by_extension(filename):
    """
    Определяет тип файла по расширению
    """
    ext = os.path.splitext(filename)[1].lower()

    # Изображения
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
    if ext in image_extensions:
        mime_type = mimetypes.guess_type(filename)[0] or 'image/jpeg'
        return 'image', mime_type

    # Видео
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv']
    if ext in video_extensions:
        mime_type = mimetypes.guess_type(filename)[0] or 'video/mp4'
        return 'video', mime_type

    # Аудио (кроме голосовых)
    audio_extensions = ['.mp3', '.wav', '.ogg', '.m4a', '.flac']
    if ext in audio_extensions:
        mime_type = mimetypes.guess_type(filename)[0] or 'audio/mpeg'
        return 'audio', mime_type

    # Документы
    document_extensions = ['.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt']
    if ext in document_extensions:
        mime_type = mimetypes.guess_type(filename)[0] or 'application/pdf'
        return 'document', mime_type

    # Архивы
    archive_extensions = ['.zip', '.rar', '.7z', '.tar', '.gz']
    if ext in archive_extensions:
        return 'document', 'application/octet-stream'

    return None, None


def is_valid_image(file):
    """
    Проверяет, является ли файл валидным изображением
    """
    try:
        # Читаем начало файла для проверки сигнатур
        header = file.read(12)
        file.seek(0)

        # JPEG: FF D8 FF
        if header.startswith(b'\xff\xd8\xff'):
            return True
        # PNG: 89 50 4E 47 0D 0A 1A 0A
        elif header.startswith(b'\x89PNG\r\n\x1a\n'):
            return True
        # GIF: GIF87a или GIF89a
        elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
            return True
        # BMP: BM
        elif header.startswith(b'BM'):
            return True
        # WebP: RIFF....WEBP
        elif header.startswith(b'RIFF') and header[8:12] == b'WEBP':
            return True

        return False
    except:
        return False





def create_image_thumbnail(file):
    """
    Создает миниатюру для изображения
    """
    try:
        # Проверяем, что это изображение
        if not is_valid_image(file):
            return None

        # Открываем изображение
        image = Image.open(file)

        # Конвертируем в RGB если нужно
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        # Создаем миниатюру (макс 320px по большей стороне)
        image.thumbnail((320, 320), Image.Resampling.LANCZOS)

        # Сохраняем в буфер
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=85, optimize=True)
        buffer.seek(0)

        # Создаем файл миниатюры
        from django.core.files.base import ContentFile
        thumbnail_file = ContentFile(buffer.read())
        thumbnail_file.name = f"thumb_{int(timezone.now().timestamp())}.jpg"

        return thumbnail_file

    except Exception as e:
        print(f"Ошибка создания миниатюры: {e}")
        return None


def compress_image_if_needed(image_file, max_width=1920, max_height=1080, quality=85):
    """
    Сжимает изображение если оно слишком большое
    """
    try:
        image = Image.open(image_file)

        # Проверяем нужно ли сжимать
        if image.width <= max_width and image.height <= max_height:
            return image_file

        # Изменяем размер
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        # Сохраняем сжатое изображение
        buffer = io.BytesIO()

        # Определяем формат
        if image_file.name.lower().endswith('.png'):
            image.save(buffer, format='PNG', optimize=True)
        else:
            image.save(buffer, format='JPEG', quality=quality, optimize=True)

        buffer.seek(0)

        # Создаем новый файл
        from django.core.files.base import ContentFile
        compressed_file = ContentFile(buffer.read())
        compressed_file.name = image_file.name

        return compressed_file

    except Exception as e:
        print(f"Ошибка сжатия изображения: {e}")
        return image_file