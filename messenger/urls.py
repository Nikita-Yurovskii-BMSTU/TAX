from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    # ==================== ОСНОВНЫЕ URL ====================
    path('', views.chat_list, name='chat_list'),
    path('chat/<int:chat_id>/', views.chat_detail, name='chat_detail'),
    path('start-chat/<int:user_id>/', views.start_chat, name='start_chat'),
    path('create-group/', views.create_group_chat, name='create_group'),
    path('add-contact/<int:user_id>/', views.add_contact, name='add_contact'),
    path('search/', views.search_users, name='search_users'),
    path('unread-count/', views.get_unread_count, name='unread_count'),

    # ==================== MEDIA URLS ====================
    # Загрузка медиафайлов
    path('chat/<int:chat_id>/upload-media/',
         views.upload_media,
         name='upload_media'),

    # Загрузка голосовых сообщений
    path('chat/<int:chat_id>/upload-voice/',
         views.upload_voice_message,
         name='upload_voice'),

    # Получение медиафайлов чата (API)
    path('chat/<int:chat_id>/media/',
         views.get_chat_media,
         name='get_chat_media'),

    # Просмотр медиафайла
    path('media/<int:media_id>/view/',
         views.view_media,
         name='view_media'),

    # Скачивание медиафайла
    path('media/<int:media_id>/download/',
         views.download_media,
         name='download_media'),

    # Удаление медиафайла
    path('media/<int:media_id>/delete/',
         views.delete_media,
         name='delete_media'),

    # Галерея медиафайлов (HTML страница)
    path('chat/<int:chat_id>/gallery/',
         views.media_gallery,
         name='media_gallery'),
]

# Добавляем маршруты для медиафайлов в режиме DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)