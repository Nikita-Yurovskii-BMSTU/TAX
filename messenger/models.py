from django.db import models
from django.conf import settings
from django.utils import timezone


class ChatRoom(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Название чата")
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='chatrooms')
    is_group = models.BooleanField(default=False, verbose_name="Групповой чат")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.name:
            return self.name
        participants = self.participants.all()
        if len(participants) == 2:
            return f"Чат между {participants[0]} и {participants[1]}"
        return f"Групповой чат {self.id}"

    class Meta:
        verbose_name = "Чат"
        verbose_name_plural = "Чаты"


class Message(models.Model):
    chat = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField(verbose_name="Сообщение")
    timestamp = models.DateTimeField(auto_now_add=True)
    read_by = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='read_messages', blank=True)
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")

    def __str__(self):
        return f"{self.sender}: {self.content[:50]}"

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        ordering = ['timestamp']


class Contact(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contacts')
    contact = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='added_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'contact']
        verbose_name = "Контакт"
        verbose_name_plural = "Контакты"