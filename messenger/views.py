from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Max
from django.contrib.auth import get_user_model
from .models import ChatRoom, Message, Contact
from accounts.models import CustomUser

User = get_user_model()


@login_required
def chat_list(request):
    # Получаем чаты пользователя, отсортированные по последнему сообщению
    chats = ChatRoom.objects.filter(participants=request.user).annotate(
        last_message_time=Max('messages__timestamp')
    ).order_by('-last_message_time', '-updated_at')

    return render(request, 'messenger/chat_list.html', {'chats': chats})


@login_required
def chat_detail(request, chat_id):
    chat = get_object_or_404(ChatRoom, id=chat_id, participants=request.user)
    messages = chat.messages.all().order_by('timestamp')

    return render(request, 'messenger/chat_detail.html', {
        'chat': chat,
        'messages': messages,
    })


@login_required
def start_chat(request, user_id):
    other_user = get_object_or_404(User, id=user_id)

    # Ищем существующий чат между пользователями
    chat = ChatRoom.objects.filter(
        participants=request.user
    ).filter(
        participants=other_user
    ).filter(is_group=False).first()

    # Если чат не существует, создаем новый
    if not chat:
        chat = ChatRoom.objects.create(is_group=False)
        chat.participants.add(request.user, other_user)

    return redirect('chat_detail', chat_id=chat.id)


@login_required
def create_group_chat(request):
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
    contact_user = get_object_or_404(User, id=user_id)
    Contact.objects.get_or_create(
        user=request.user,
        contact=contact_user
    )
    return redirect('user_list')


@login_required
def search_users(request):
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
    unread_count = Message.objects.filter(
        chat__participants=request.user
    ).exclude(
        read_by=request.user
    ).exclude(
        sender=request.user
    ).count()

    return JsonResponse({'unread_count': unread_count})