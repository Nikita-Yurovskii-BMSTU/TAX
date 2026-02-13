from django.db import models
from django.conf import settings
from django.utils import timezone
import os


def media_upload_path(instance, filename):
    """
    Генерирует путь для сохранения медиафайлов.
    Формат: media/chat_{chat_id}/{тип_файла}/{год}/{месяц}/{имя_файла}
    """
    # Извлекаем расширение файла
    ext = filename.split('.')[-1]

    # Генерируем уникальное имя файла
    new_filename = f"{timezone.now().timestamp()}_{instance.sender.id}.{ext}"

    # Структура папок для организации файлов
    return f"chat_{instance.chat.id}/{instance.file_type}/{timezone.now().year}/{timezone.now().month}/{new_filename}"


def thumbnail_upload_path(instance, filename):
    """Путь для сохранения превью (миниатюр)"""
    ext = filename.split('.')[-1]
    return f"thumbnails/chat_{instance.chat.id}/{timezone.now().timestamp()}.{ext}"


class MediaFile(models.Model):
    """
    Модель для хранения медиафайлов: фото, видео, документы, голосовые
    """
    FILE_TYPES = [
        ('image', 'Изображение'),
        ('video', 'Видео'),
        ('audio', 'Аудио'),
        ('document', 'Документ'),
        ('voice', 'Голосовое сообщение'),
    ]

    # Связи
    chat = models.ForeignKey('ChatRoom', on_delete=models.CASCADE, related_name='media_files')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='uploaded_media')

    # Основные поля файла
    file = models.FileField(
        upload_to=media_upload_path,
        verbose_name="Файл"
    )
    file_type = models.CharField(
        max_length=10,
        choices=FILE_TYPES,
        verbose_name="Тип файла"
    )
    file_name = models.CharField(
        max_length=255,
        verbose_name="Имя файла"
    )
    file_size = models.BigIntegerField(
        verbose_name="Размер файла (байты)"
    )

    # Метаданные
    mime_type = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="MIME-тип"
    )
    duration = models.IntegerField(
        default=0,
        help_text="Длительность аудио/видео в секундах",
        verbose_name="Длительность"
    )

    # Миниатюра (для видео и изображений)
    thumbnail = models.ImageField(
        upload_to=thumbnail_upload_path,
        blank=True,
        null=True,
        verbose_name="Миниатюра"
    )

    # Описание
    caption = models.TextField(
        blank=True,
        verbose_name="Описание"
    )

    # Технические поля
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Время загрузки"
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name="Удален"
    )

    # Статистика
    views_count = models.IntegerField(
        default=0,
        verbose_name="Количество просмотров"
    )
    downloads_count = models.IntegerField(
        default=0,
        verbose_name="Количество скачиваний"
    )

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Медиафайл'
        verbose_name_plural = 'Медиафайлы'
        indexes = [
            models.Index(fields=['chat', 'uploaded_at']),
            models.Index(fields=['file_type', 'uploaded_at']),
            models.Index(fields=['sender', 'uploaded_at']),
        ]

    def __str__(self):
        return f"{self.sender.username}: {self.file_name} ({self.get_file_size_display()})"

    def get_file_size_display(self):
        """Человекочитаемый размер файла"""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        elif self.file_size < 1024 * 1024 * 1024:
            return f"{self.file_size / (1024 * 1024):.1f} MB"
        else:
            return f"{self.file_size / (1024 * 1024 * 1024):.1f} GB"

    def file_extension(self):
        """Возвращает расширение файла"""
        return os.path.splitext(self.file_name)[1].lower()

    def is_image(self):
        return self.file_type == 'image'

    def is_video(self):
        return self.file_type == 'video'

    def is_audio(self):
        return self.file_type == 'audio'

    def is_document(self):
        return self.file_type == 'document'

    def is_voice(self):
        return self.file_type == 'voice'

    def get_absolute_url(self):
        """Абсолютный URL к файлу"""
        return self.file.url

    def get_thumbnail_url(self):
        """URL миниатюры или заглушки"""
        if self.thumbnail:
            return self.thumbnail.url
        elif self.is_image():
            return self.file.url  # Для изображений миниатюра = само изображение
        elif self.is_video():
            # Заглушка для видео
            return '/static/images/video-thumbnail.png'
        elif self.is_document():
            # Иконка для документов
            ext = self.file_extension()
            if ext in ['.pdf']:
                return '/static/images/pdf-icon.png'
            elif ext in ['.doc', '.docx']:
                return '/static/images/word-icon.png'
            else:
                return '/static/images/file-icon.png'
        elif self.is_voice():
            return '/static/images/voice-icon.png'

        return '/static/images/file-icon.png'

    def increment_views(self):
        """Увеличивает счетчик просмотров"""
        self.views_count += 1
        self.save(update_fields=['views_count'])

    def increment_downloads(self):
        """Увеличивает счетчик скачиваний"""
        self.downloads_count += 1
        self.save(update_fields=['downloads_count'])

    def soft_delete(self):
        """Мягкое удаление файла"""
        self.is_deleted = True
        self.save(update_fields=['is_deleted'])

    @property
    def can_preview(self):
        """Можно ли показать превью файла"""
        return self.is_image() or self.is_video()

    @property
    def can_play(self):
        """Можно ли воспроизвести файл"""
        return self.is_video() or self.is_audio() or self.is_voice()


class ChatRoom(models.Model):
    """
    Обновленная модель чата с медиа-статистикой
    """
    name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Название чата"
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='chatrooms'
    )
    is_group = models.BooleanField(
        default=False,
        verbose_name="Групповой чат"
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    # Статистика медиа
    total_media_files = models.IntegerField(
        default=0,
        verbose_name="Всего медиафайлов"
    )
    last_media_upload = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Последняя загрузка медиа"
    )

    def __str__(self):
        if self.name:
            return self.name
        participants = self.participants.all()
        if len(participants) == 2:
            return f"Чат между {participants[0]} и {participants[1]}"
        return f"Групповой чат {self.id}"

    def update_media_stats(self):
        """Обновляет статистику медиафайлов в чате"""
        self.total_media_files = self.media_files.filter(is_deleted=False).count()
        last_media = self.media_files.filter(is_deleted=False).order_by('-uploaded_at').first()
        if last_media:
            self.last_media_upload = last_media.uploaded_at
        self.save()

    class Meta:
        verbose_name = "Чат"
        verbose_name_plural = "Чаты"


class Message(models.Model):
    """
    Обновленная модель сообщения с поддержкой медиафайлов
    """
    # Связи
    chat = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )

    # Текст сообщения (может быть пустым для медиа)
    content = models.TextField(
        blank=True,
        verbose_name="Текст сообщения"
    )

    # Связь с медиафайлом (опционально)
    media_file = models.ForeignKey(
        MediaFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages'
    )

    # Технические поля
    timestamp = models.DateTimeField(
        auto_now_add=True
    )
    read_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='read_messages',
        blank=True
    )
    is_read = models.BooleanField(
        default=False,
        verbose_name="Прочитано"
    )
    is_edited = models.BooleanField(
        default=False,
        verbose_name="Редактировано"
    )
    edited_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время редактирования"
    )

    # Тип сообщения для быстрого фильтра
    MESSAGE_TYPES = [
        ('text', 'Текстовое'),
        ('image', 'Изображение'),
        ('video', 'Видео'),
        ('audio', 'Аудио'),
        ('document', 'Документ'),
        ('voice', 'Голосовое'),
    ]
    message_type = models.CharField(
        max_length=10,
        choices=MESSAGE_TYPES,
        default='text',
        verbose_name="Тип сообщения"
    )

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['chat', 'timestamp']),
            models.Index(fields=['sender', 'timestamp']),
            models.Index(fields=['message_type', 'timestamp']),
        ]

    def __str__(self):
        if self.media_file:
            return f"{self.sender}: [{self.message_type}] {self.media_file.file_name}"
        return f"{self.sender}: {self.content[:50]}"

    def save(self, *args, **kwargs):
        """Переопределяем сохранение для автоматического определения типа"""
        if self.media_file:
            self.message_type = self.media_file.file_type
        elif not self.content.strip():
            raise ValueError("Сообщение должно содержать текст или медиафайл")
        else:
            self.message_type = 'text'

        super().save(*args, **kwargs)

        # Обновляем статистику чата если есть медиа
        if self.media_file:
            self.chat.update_media_stats()

    def has_media(self):
        """Есть ли у сообщения медиафайл"""
        return self.media_file is not None

    def mark_as_read(self, user):
        """Пометить сообщение как прочитанное"""
        if user not in self.read_by.all():
            self.read_by.add(user)
            self.is_read = True
            self.save()

    def edit_message(self, new_content):
        """Редактировать сообщение"""
        if not self.has_media():  # Текстовые сообщения можно редактировать
            self.content = new_content
            self.is_edited = True
            self.edited_at = timezone.now()
            self.save()
            return True
        return False


class Contact(models.Model):
    """Модель контактов (без изменений)"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contacts')
    contact = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='added_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'contact']
        verbose_name = "Контакт"
        verbose_name_plural = "Контакты"

    def __str__(self):
        return f"{self.user} -> {self.contact}"