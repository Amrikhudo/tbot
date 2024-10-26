import telebot
from telebot import types
import threading
import time
from datetime import datetime
import json
import os
import sqlite3
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
import logging

# Настройка логирования
logging.basicConfig(filename='bot_log.txt', level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


TOKEN = '6722867524:AAHTrbPaoI_5FfCx3gRfvi7LmUY9gyHu2FY'
ADMIN_ID = 5029226185
bot = telebot.TeleBot(TOKEN)

# Инициализация базы данных
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц, если они не существуют
cursor.execute('''CREATE TABLE IF NOT EXISTS events
                  (id INTEGER PRIMARY KEY, name TEXT, date TEXT, description TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS news
                  (id INTEGER PRIMARY KEY, title TEXT, description TEXT, photo TEXT, likes INTEGER, dislikes INTEGER, date TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_reactions
                  (user_id INTEGER, news_id INTEGER, reaction TEXT, PRIMARY KEY (user_id, news_id))''')
conn.commit()

# Глобальные переменные
user_questions = {}
admin_reply_expected = False
current_question_id = None
user_ids = set()


# Функция для загрузки пользователей из файла
def load_users():
    global user_ids
    try:
        with open('users.json', 'r') as f:
            user_ids = set(json.load(f))
    except FileNotFoundError:
        user_ids = set()

def save_event(event):
    cursor.execute('INSERT INTO events (name, date, description) VALUES (?, ?, ?)',
                   (event['name'], event['date'].strftime('%Y-%m-%d'), event['description']))
    conn.commit()

def load_events():
    cursor.execute('SELECT * FROM events')
    events = []
    for row in cursor.fetchall():
        event = {
            'id': row[0],
            'name': row[1],
            'date': datetime.strptime(row[2], '%Y-%m-%d'),
            'description': row[3]
        }
        events.append(event)
    return events

def save_news(news_item):
    cursor.execute('INSERT INTO news (title, description, photo, likes, dislikes, date) VALUES (?, ?, ?, ?, ?, ?)',
                   (news_item['title'], news_item['description'], news_item['photo'], news_item['likes'], news_item['dislikes'], news_item['date'].strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()

def load_news():
    cursor.execute('SELECT * FROM news')
    news = []
    for row in cursor.fetchall():
        news_item = {
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'photo': row[3],
            'likes': row[4],
            'dislikes': row[5],
            'date': datetime.strptime(row[6], '%Y-%m-%d %H:%M:%S')
        }
        news.append(news_item)
    return news

# Функция для сохранения пользователей в файл
def save_users():
    with open('users.json', 'w') as f:
        json.dump(list(user_ids), f)


# Загрузка вопросов
def load_questions():
    global user_questions
    if os.path.exists('user_questions.json'):
        with open('user_questions.json', 'r') as f:
            user_questions = json.load(f)
    return user_questions

# Сохранение вопросов
def save_questions():
    global user_questions
    with open('user_questions.json', 'w') as f:
        json.dump(user_questions, f)

def main_menu_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("📅 Мероприятия"), types.KeyboardButton("📰 Новости"))
    markup.row(types.KeyboardButton("❓ Задать вопрос"), types.KeyboardButton("🆘 Помощь"))
    markup.row(types.KeyboardButton("👤 Обо мне"))
    return markup

# Про пользователя
def get_user_info(user):
    user_info = f"👤 Новый пользователь!\n\n"
    user_info += f"ID: {user.id}\n"
    user_info += f"Имя: {user.first_name}\n"
    if user.last_name:
        user_info += f"Фамилия: {user.last_name}\n"
    if user.username:
        user_info += f"Username: @{user.username}\n"
    user_info += f"Язык: {user.language_code}\n"
    user_info += f"Бот: {'Да' if user.is_bot else 'Нет'}\n"
    return user_info

@bot.message_handler(commands=['start'])
def start(message):
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    
    if user_id not in user_ids:
        user_ids.add(user_id)
        save_users()
        
        # Отправка информации о новом пользователе администратору
        user_info = get_user_info(message.from_user)
        bot.send_message(ADMIN_ID, user_info)
    
    bot.send_message(
        message.chat.id,
        f'Привет, {user_name}! 👋 Я бот Амрихудо. Выберите опцию:',
        reply_markup=main_menu_markup()
    )


@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        '🆘 Вот что я могу:\n\n'
        '📅 Мероприятия - Посмотреть список мероприятий\n'
        '📰 Новости - Последние новости\n'
        '❓ Задать вопрос - Задать вопрос администратору\n'
        '🆘 Помощь - Получить помощь по использованию бота\n'
    )
    bot.send_message(message.chat.id, help_text, reply_markup=main_menu_markup())

# Функция для отправки уведомлений всем пользователям
def notify_all_users(message):
    for user_id in user_ids:
        try:
            bot.send_message(user_id, message)
        except Exception as e:
            print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")


@bot.message_handler(commands=['users'])
def send_user_list(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав для выполнения этой команды.")
        return
    
    user_list = "📊 Список пользователей:\n\n"
    for user_id in user_ids:
        try:
            user = bot.get_chat_member(user_id, user_id).user
            user_info = get_user_info(user)
            user_list += user_info + "\n---\n"
        except Exception as e:
            user_list += f"Ошибка получения информации о пользователе {user_id}: {str(e)}\n---\n"
    
    # Разделим сообщение на части, если оно слишком длинное
    max_length = 4096  # Максимальная длина сообщения в Telegram
    for i in range(0, len(user_list), max_length):
        bot.send_message(message.chat.id, user_list[i:i+max_length])


def ask_question(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔙 Отмена"))
    bot.send_message(message.chat.id, "Пожалуйста, напишите ваш вопрос или нажмите '🔙 Отмена' для возврата в главное меню.", reply_markup=markup)
    bot.register_next_step_handler(message, handle_user_question)

def cancel_action(message):
    bot.send_message(message.chat.id, "Действие отменено. Возвращаемся в главное меню.", reply_markup=main_menu_markup())

def add_cancel_option(markup):
    return markup.add(types.KeyboardButton("🔙 Отмена"))

@bot.message_handler(commands=['faq'])
def faq_command(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Задать вопрос", callback_data='ask_question'))
    bot.send_message(message.chat.id, "Здесь будут часто задаваемые вопросы. Если у вас есть вопрос, нажмите кнопку ниже, чтобы задать его.", reply_markup=markup)

@bot.message_handler(commands=['events'])
def events_command(message):
    show_events(message)

@bot.message_handler(commands=['news'])
def news_command(message):
    show_news(message)

@bot.message_handler(func=lambda message: message.text == "👤 Обо мне")
def about_me(message):
    about_text = """
    🤔 Кто же этот загадочный Амрихудо? Давайте разберёмся!

    🎂 Родился в 2008 году в солнечном Таджикистане. Да-да, я ещё совсем молодой, но уже успел пожить в трёх городах! Калуга, Санкт-Петербург...

    💻 Думаете, я только и делаю, что кодю? Ну, почти... 
    Начал программировать ещё в школе. Представляете, вместо того, чтобы гонять мяч, я гонял баги в коде! 🐛

    🏆 В 2023 году занял первое место в городском конкурсе IT-проектов. Мама гордится, папа в шоке, а я просто делаю то, что люблю!

    🤓 Языки, которые я знаю: HTML, CSS, JavaScript, Python. 
    Языки, которые я учу: Java, C++. 
    Язык, на котором я мечтаю: на языке будущего! 🔮

    🥋 А вы думали, я только с компьютером дружу? А вот и нет! 
    С 5 лет занимаюсь борьбой. Начинал с дзюдо, а сейчас покоряю самбо. 
    Кто сказал, что программисты не спортивные?

    🤹‍♂️ В моей жизни есть только две вещи: спорт и программирование. 
    Ну, ещё еда и сон... Иногда. 😅

    🌟 Моя цель? Стать супер-пупер full-stack разработчиком и создавать крутые штуки, которые изменят мир! Или хотя бы сделают его чуточку веселее.

    🔍 Хотите узнать ещё больше обо мне? 
    Загляните на мой сайт: amrikhudo.ru 
    Там есть все мои секреты! Ну, кроме пароля от WiFi, конечно.

    """
    bot.send_message(message.chat.id, about_text, reply_markup=main_menu_markup())




# Функция для загрузки вопросов из JSON файла
user_questions = {}

# Загрузка вопросов
def load_questions():
    global user_questions
    if os.path.exists('user_questions.json'):
        with open('user_questions.json', 'r') as f:
            user_questions = json.load(f)
    return user_questions

# Сохранение вопросов
def save_questions():
    global user_questions
    with open('user_questions.json', 'w') as f:
        json.dump(user_questions, f)

def handle_user_question(message):
    if message.text == "🔙 Отмена":
        cancel_action(message)
        return

    user_id = message.from_user.id
    question = message.text
    question_id = str(message.message_id)

    user_questions[question_id] = {
        'user_id': user_id,
        'question': question
    }

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Ответить на вопрос", callback_data=f'answer_{question_id}'))
    bot.send_message(ADMIN_ID, f"Новый вопрос от пользователя {message.from_user.first_name}:\n{question}", reply_markup=markup)

    bot.reply_to(message, "✅ Ваш вопрос отправлен администратору. Мы ответим вам в ближайшее время.", reply_markup=main_menu_markup())
    save_questions()

def process_admin_reply(message, question_id):
    global admin_reply_expected, user_questions
    
    user_questions = load_questions()  # Загружаем актуальные вопросы перед обработкой
    
    if question_id in user_questions:
        user_id = user_questions[question_id]['user_id']
        question = user_questions[question_id]['question']
        answer = message.text

        bot.send_message(user_id, f"Ответ на ваш вопрос:\nВопрос: {question}\nОтвет: {answer}")

        user_questions[question_id]['status'] = 'answered'
        user_questions[question_id]['answer'] = answer
        save_questions()

        bot.reply_to(message, "✅ Ответ отправлен пользователю.")
    else:
        bot.reply_to(message, "❌ Ошибка: вопрос не найден.")
    
    admin_reply_expected = False

# Add new function to handle news deletion
def delete_news(news_id):
    cursor.execute('DELETE FROM news WHERE id = ?', (news_id,))
    conn.commit()

def delete_event(event_id):
    cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
    conn.commit()

def update_news_reaction(news_id, user_id, reaction):
    cursor.execute('INSERT OR REPLACE INTO user_reactions (user_id, news_id, reaction) VALUES (?, ?, ?)',
                   (user_id, news_id, reaction))
    conn.commit()

def get_user_reaction(news_id, user_id):
    cursor.execute('SELECT reaction FROM user_reactions WHERE user_id = ? AND news_id = ?', (user_id, news_id))
    result = cursor.fetchone()
    return result[0] if result else None

# Загрузка данных при запуске
events = load_events()
news = load_news()

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    global admin_reply_expected, current_question_id
    
    if call.data == 'faq':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Задать вопрос", callback_data='ask_question'))
        bot.send_message(call.message.chat.id, "Здесь будут часто задаваемые вопросы. Если у вас есть вопрос, нажмите кнопку ниже, чтобы задать его.", reply_markup=markup)
    elif call.data == 'ask_question':
        bot.send_message(call.message.chat.id, "Пожалуйста, напишите ваш вопрос.")
        bot.register_next_step_handler(call.message, handle_user_question)
    elif call.data == 'events':
        show_events(call.message)
    elif call.data == 'news':
        show_news(call.message)
    elif call.data == 'help':
        help_command(call.message)
    elif call.data == 'delete_news':
        if call.from_user.id == ADMIN_ID:
            show_news_for_deletion(call.message)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав для удаления новостей.")
    elif call.data.startswith('delete_news_'):
        if call.from_user.id == ADMIN_ID:
            news_id = int(call.data.split('_')[2])
            delete_news(news_id)
            bot.answer_callback_query(call.id, "Новость успешно удалена.")
            show_news(call.message)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав для удаления новостей.")
    elif call.data.startswith('delete_event_'):
        if call.from_user.id == ADMIN_ID:
            event_id = int(call.data.split('_')[2])
            delete_event(event_id)
            bot.answer_callback_query(call.id, "Мероприятие успешно удалено.")
            show_events(call.message)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав для удаления мероприятий.")
    elif call.data.startswith('answer_'):
        question_id = call.data.split('_')[1]
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"Пожалуйста, напишите ответ на вопрос {question_id}:")
        bot.register_next_step_handler(call.message, process_admin_reply, question_id)
    elif call.data.startswith('event_'):
        event_id = int(call.data.split('_')[1])
        show_event_details(call.message, event_id)
    elif call.data.startswith('news_'):
        news_id = int(call.data.split('_')[1])
        show_news_details(call.message, news_id)
    elif call.data.startswith('like_'):
        news_id = int(call.data.split('_')[1])
        handle_like(call, news_id)
    elif call.data.startswith('dislike_'):
        news_id = int(call.data.split('_')[1])
        handle_dislike(call, news_id)
    elif call.data == 'back_to_main':
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text="Выберите опцию:", 
                              reply_markup=main_menu_markup())
        
def show_news_for_deletion(message):
    news = load_news()
    if not news:
        bot.send_message(message.chat.id, "📰 На данный момент нет новостей для удаления.", reply_markup=main_menu_markup())
        return

    markup = types.InlineKeyboardMarkup()
    for news_item in news:
        markup.add(types.InlineKeyboardButton(f"🗑️ {news_item['title']}", callback_data=f'delete_news_{news_item["id"]}'))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data='news'))
    
    bot.send_message(message.chat.id, "Выберите новость для удаления:", reply_markup=markup)


@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and admin_reply_expected)
def handle_admin_answer(message):
    global admin_reply_expected, current_question_id, user_questions
    
    if current_question_id in user_questions:
        user_id = user_questions[current_question_id]['user_id']
        question = user_questions[current_question_id]['question']
        answer = message.text
        
        # Отправляем ответ пользователю
        bot.send_message(user_id, f"Ответ на ваш вопрос:\nВопрос: {question}\nОтвет: {answer}")
        
        # Обновляем статус вопроса
        user_questions[current_question_id]['status'] = 'answered'
        user_questions[current_question_id]['answer'] = answer
        save_questions()
        
        # Подтверждение админу
        bot.reply_to(message, "✅ Ответ отправлен пользователю.", reply_markup=main_menu_markup())
    else:
        bot.reply_to(message, "❌ Вопрос не найден.", reply_markup=main_menu_markup())
    
    admin_reply_expected = False
    current_question_id = None
    

def cancel_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔙 Отмена"))
    return markup

def process_cancel(message):
    if message.text == "🔙 Отмена":
        bot.send_message(message.chat.id, "Действие отменено. Возвращаемся в главное меню.", reply_markup=main_menu_markup())
        return True
    return False

    # News functions
@bot.message_handler(commands=['addnews'])
def add_news(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав для добавления новостей.")
        return
    bot.reply_to(message, "📝 Введите заголовок новости или нажмите '🔙 Отмена':", reply_markup=cancel_markup())
    bot.register_next_step_handler(message, process_news_title)

def process_news_title(message):
    if process_cancel(message):
        return
    news_item = {'title': message.text, 'likes': 0, 'dislikes': 0, 'date': datetime.now()}
    bot.reply_to(message, "📸 Отправьте фото для новости или нажмите '🔙 Отмена':", reply_markup=cancel_markup())
    bot.register_next_step_handler(message, process_news_photo, news_item)

def process_news_photo(message, news_item):
    if process_cancel(message):
        return
    if message.photo:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        photo_dir = os.path.join('news_photos', os.path.dirname(file_info.file_path))
        os.makedirs(photo_dir, exist_ok=True)
        src = os.path.join('news_photos', file_info.file_path)
        
        with open(src, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        news_item['photo'] = src
        bot.reply_to(message, "📝 Теперь введите описание новости или нажмите '🔙 Отмена':", reply_markup=cancel_markup())
        bot.register_next_step_handler(message, process_news_description, news_item)
    else:
        bot.reply_to(message, "❌ Пожалуйста, отправьте фото или нажмите '🔙 Отмена'.", reply_markup=cancel_markup())
        bot.register_next_step_handler(message, process_news_photo, news_item)

def process_news_description(message, news_item):
    if process_cancel(message):
        return
    news_item['description'] = message.text
    save_news(news_item)  # Используйте эту функцию вместо news.append(news_item)
    bot.reply_to(message, "✅ Новость успешно добавлена!", reply_markup=main_menu_markup())
    
    # Отправляем уведомление всем пользователям
    notification = f"📣 НОВАЯ НОВОСТЬ! 📣\n\n📌 {news_item['title']}\n\nУзнайте подробности в разделе Новости!"
    notify_all_users(notification)

def show_news(message):
    news = load_news()  # Загружаем актуальные данные из базы
    if not news:
        bot.send_message(message.chat.id, "📰 На данный момент нет новостей.", reply_markup=main_menu_markup())
        return

    markup = types.InlineKeyboardMarkup()
    for news_item in news:
        markup.add(types.InlineKeyboardButton(f"📌 {news_item['title']}", callback_data=f'news_{news_item["id"]}'))
    
    if message.from_user.id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("🗑️ Удалить новость", callback_data='delete_news'))
    
    bot.send_message(message.chat.id, "📰 Список новостей:", reply_markup=markup)

def show_news_details(message, news_id):
    news = load_news()
    news_item = next((item for item in news if item['id'] == news_id), None)
    if news_item:
        with open(news_item['photo'], 'rb') as photo:
            caption = f"📌 {news_item['title']}\n\n"
            caption += f"📝 {news_item['description']}\n\n"
            caption += f"👍 {news_item['likes']} 👎 {news_item['dislikes']}\n"
            caption += f"🕒 {news_item['date'].strftime('%d.%m.%Y %H:%M')}"
            
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("👍", callback_data=f'like_{news_id}'),
                types.InlineKeyboardButton("👎", callback_data=f'dislike_{news_id}')
            )
            markup.add(types.InlineKeyboardButton("🔙 Назад к списку", callback_data='news'))
            
            if message.from_user.id == ADMIN_ID:
                markup.add(types.InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_news_{news_id}'))
            
            bot.send_photo(message.chat.id, photo, caption=caption, reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ Новость не найдена.", reply_markup=main_menu_markup())

def handle_like(call, news_id):
    user_id = call.from_user.id
    current_reaction = get_user_reaction(news_id, user_id)
    
    if current_reaction == 'like':
        bot.answer_callback_query(call.id, "Вы уже поставили лайк этой новости!")
    elif current_reaction == 'dislike':
        update_news_reaction(news_id, user_id, 'like')
        cursor.execute('UPDATE news SET likes = likes + 1, dislikes = dislikes - 1 WHERE id = ?', (news_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "Ваш дизлайк изменен на лайк!")
    else:
        update_news_reaction(news_id, user_id, 'like')
        cursor.execute('UPDATE news SET likes = likes + 1 WHERE id = ?', (news_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "Спасибо за ваш лайк!")
    
    show_news_details(call.message, news_id)

def handle_dislike(call, news_id):
    user_id = call.from_user.id
    current_reaction = get_user_reaction(news_id, user_id)
    
    if current_reaction == 'dislike':
        bot.answer_callback_query(call.id, "Вы уже поставили дизлайк этой новости!")
    elif current_reaction == 'like':
        update_news_reaction(news_id, user_id, 'dislike')
        cursor.execute('UPDATE news SET likes = likes - 1, dislikes = dislikes + 1 WHERE id = ?', (news_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "Ваш лайк изменен на дизлайк!")
    else:
        update_news_reaction(news_id, user_id, 'dislike')
        cursor.execute('UPDATE news SET dislikes = dislikes + 1 WHERE id = ?', (news_id,))
        conn.commit()
        bot.answer_callback_query(call.id, "Спасибо за ваш дизлайк!")
    
    show_news_details(call.message, news_id)
    
@bot.message_handler(commands=['addevent'])
def add_event(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав для добавления мероприятий.")
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔙 Отмена"))
    bot.reply_to(message, "📝 Введите название мероприятия или нажмите '🔙 Отмена':", reply_markup=markup)
    bot.register_next_step_handler(message, process_event_name)


def process_event_name(message):
    if message.text == "🔙 Отмена":
        cancel_action(message)
        return
    event = {'name': message.text}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔙 Отмена"))
    bot.reply_to(message, "📅 Введите дату мероприятия (в формате ДД.ММ.ГГГГ) или нажмите '🔙 Отмена':", reply_markup=markup)
    bot.register_next_step_handler(message, process_event_date, event)

def process_event_date(message, event):
    if message.text == "🔙 Отмена":
        cancel_action(message)
        return
    try:
        event['date'] = datetime.strptime(message.text, '%d.%m.%Y')
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("🔙 Отмена"))
        bot.reply_to(message, "📝 Введите описание мероприятия или нажмите '🔙 Отмена':", reply_markup=markup)
        bot.register_next_step_handler(message, process_event_description, event)
    except ValueError:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("🔙 Отмена"))
        bot.reply_to(message, "❌ Неверный формат даты. Пожалуйста, используйте формат ДД.ММ.ГГГГ или нажмите '🔙 Отмена':", reply_markup=markup)
        bot.register_next_step_handler(message, process_event_date, event)

# Функция для проверки приближающихся мероприятий и отправки уведомлений
def check_upcoming_events():
    sent_notifications = {}
    
    while True:
        current_date = datetime.now().date()
        events = load_events()
        
        for event in events:
            event_id = event['id']
            event_date = event['date'].date()
            days_until_event = (event_date - current_date).days
            
            if event_id not in sent_notifications:
                sent_notifications[event_id] = set()
            
            notifications = [
                (30, '1month', f"🗓️ До мероприятия '{event['name']}' остался 1 месяц!"),
                (10, '10days', f"🗓️ До мероприятия '{event['name']}' осталось 10 дней!"),
                (5, '5days', f"🗓️ До мероприятия '{event['name']}' осталось 5 дней!"),
                (3, '3days', f"🗓️ До мероприятия '{event['name']}' осталось 3 дня!"),
                (2, '2days', f"🗓️ До мероприятия '{event['name']}' осталось 2 дня!"),
                (1, '1day', f"⏰ Мероприятие '{event['name']}' состоится завтра!"),
                (0, 'today', f"🎉 Мероприятие '{event['name']}' проходит сегодня!")
            ]
            
            for days, notification_type, message in notifications:
                if (days_until_event == days and 
                    notification_type not in sent_notifications[event_id]):
                    notify_all_users(message)
                    sent_notifications[event_id].add(notification_type)
            
            if days_until_event < 0:
                if event_id in sent_notifications:
                    del sent_notifications[event_id]
        
        time.sleep(3600)

# Модифицируем функцию process_event_description
def process_event_description(message, event):
    if message.text == "🔙 Отмена":
        cancel_action(message)
        return
    event['description'] = message.text
    save_event(event)  # Используйте эту функцию вместо events.append(event)
    bot.reply_to(message, "✅ Мероприятие успешно добавлено!", reply_markup=main_menu_markup())
    
    # Отправляем уведомление всем пользователям о новом мероприятии
    event_date = event['date'].strftime('%d.%m.%Y')
    days_until_event = (event['date'].date() - datetime.now().date()).days
    notification = f"🎉 НОВОЕ МЕРОПРИЯТИЕ! 🎉\n\n📌 {event['name']}\n📅 {event_date}\n\nДо мероприятия осталось {days_until_event} дней!"
    notify_all_users(notification)

def cancel_action(message):
    bot.send_message(message.chat.id, "Действие отменено. Возвращаемся в главное меню.", reply_markup=main_menu_markup())

@bot.message_handler(commands=['events'])

def show_events(message):
    events = load_events()  # Загружаем актуальные данные из базы
    if not events:
        bot.send_message(message.chat.id, "📅 На данный момент нет запланированных мероприятий.", reply_markup=main_menu_markup())
        return

    for i, event in enumerate(events):
        event_text = f"📌 {event['name']}\n📅 {event['date'].strftime('%d.%m.%Y')}\n📝 {event['description']}"
        markup = types.InlineKeyboardMarkup()
        if message.from_user.id == ADMIN_ID:
            markup.add(types.InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_event_{event["id"]}'))
        bot.send_message(message.chat.id, event_text, reply_markup=markup)

def show_event_details(message, event_id):
    if 0 <= event_id < len(events):
        event = events[event_id]
        details = f"📌 Название: {event['name']}\n"
        details += f"📅 Дата: {event['date'].strftime('%d.%m.%Y')}\n"
        details += f"📝 Описание: {event['description']}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к списку", callback_data='events'))
        bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=details, reply_markup=markup)
    else:
        bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text="❌ Мероприятие не найдено.", reply_markup=main_menu_markup())


# Добавляем команды в меню бота
bot.set_my_commands([
    types.BotCommand("/start", "Начать взаимодействие с ботом"),
    types.BotCommand("/help", "Получить помощь"),
    types.BotCommand("/events", "Список мероприятий"),
    types.BotCommand("/faq", "Часто задаваемые вопросы"),
    types.BotCommand("/news", "Последние новости"),
    types.BotCommand("/addevent", "Добавить мероприятие (для админа)"),
    types.BotCommand("/addnews", "Добавить новость (для админа)")
])

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if message.text == "📅 Мероприятия":
        show_events(message)
    elif message.text == "📰 Новости":
        show_news(message)
    elif message.text == "❓ Задать вопрос":
        ask_question(message)
    elif message.text == "🆘 Помощь":
        help_command(message)
    elif message.text == "👤 Обо мне":
        about_me(message)
    elif message.text == "🔙 Отмена":
        cancel_action(message)
    elif message.text == "/users" and message.from_user.id == ADMIN_ID:
        send_user_list(message)
    else:
        bot.reply_to(message, "Пожалуйста, выберите опцию из меню.", reply_markup=main_menu_markup())


# Увеличиваем тайм-аут для запросов
bot.request_timeout = 60

# Остальной код остается без изменений
# ...

def run_bot():
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except RequestException as e:
            logging.error(f"Network error occurred: {e}")
            time.sleep(15)
        except Exception as e:
            logging.error(f"Critical error occurred: {e}")
            time.sleep(60)

if __name__ == '__main__':
    load_questions()
    load_users()
    if not os.path.exists('news_photos'):
        os.makedirs('news_photos')
    
    # Запускаем поток для проверки приближающихся мероприятий
    reminder_thread = threading.Thread(target=check_upcoming_events)
    reminder_thread.daemon = True
    reminder_thread.start()
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()

    # Основной цикл для поддержания работы программы
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Bot stopped")
