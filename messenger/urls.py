from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_list, name='chat_list'),
    path('chat/<int:chat_id>/', views.chat_detail, name='chat_detail'),
    path('start-chat/<int:user_id>/', views.start_chat, name='start_chat'),
    path('create-group/', views.create_group_chat, name='create_group'),
    path('add-contact/<int:user_id>/', views.add_contact, name='add_contact'),
    path('search/', views.search_users, name='search_users'),
    path('unread-count/', views.get_unread_count, name='unread_count'),
]