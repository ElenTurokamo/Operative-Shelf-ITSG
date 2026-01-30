import telebot
from telebot import types
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import BOT_TOKEN, GROUP_ID, DB_URL
from models import Base, User, Storage, Request
from group import start_add_process, handle_admin_callback, handle_admin_text

bot = telebot.TeleBot(BOT_TOKEN)

engine = create_engine(DB_URL, pool_recycle=3600)
Session = sessionmaker(bind=engine)

user_data = {}

STATES = {
    'REG_IT': 1,
    'REG_NAME': 2,
    'WAIT_QTY': 3,
    'WAIT_COMMENT': 4
}

def get_db_session():
    return Session()

def get_user(session, user_id):
    return session.query(User).filter_by(user_id=user_id).first()

def clear_state(chat_id):
    if chat_id in user_data:
        if 'state' in user_data[chat_id]:
            del user_data[chat_id]['state']
        if 'temp' in user_data[chat_id]:
            del user_data[chat_id]['temp']

# --- ХЕЛПЕР: Сохранение ID сообщения в БД ---
def save_last_msg_id(chat_id, message_id):
    session = get_db_session()
    try:
        user = session.query(User).filter_by(user_id=chat_id).first()
        if user:
            user.last_msg_id = message_id
            session.commit()
    except Exception as e:
        print(f"Error saving msg_id: {e}")
    finally:
        session.close()

# --- ХЕЛПЕР: Восстановление интерфейса (С УДАЛЕНИЕМ) ---
def restore_user_interface(chat_id, session):
    """
    1. Удаляет старое сообщение (если есть).
    2. Отправляет новое актуальное состояние вниз.
    """
    user_state = user_data.get(chat_id, {}).get('state')
    temp = user_data.get(chat_id, {}).get('temp', {})
    
    # --- 1. ЛОГИКА УДАЛЕНИЯ СТАРОГО СООБЩЕНИЯ ---
    user = session.query(User).filter_by(user_id=chat_id).first()
    if user and user.last_msg_id:
        try:
            bot.delete_message(chat_id, user.last_msg_id)
        except Exception:
            # Сообщение могло быть уже удалено или слишком старым
            pass
    # ---------------------------------------------

    text_to_send = ""
    markup_to_send = None

    # Сценарий 1: Пользователь вводил количество (восстанавливаем ввод)
    if user_state == STATES['WAIT_QTY']:
        item = session.query(Storage).get(temp.get('item_id'))
        if item:
            text_to_send = f"🔽 Продолжаем оформление:\n\nВыбрано: **{item.item_name}**\nДоступно: {item.quantity}\n\n🔢 Введите количество в чат:"
        else:
            # Если товар удален, сбрасываем в меню
            text_to_send = "Товар больше недоступен. Выберите категорию:"
            markup_to_send = kb_categories(session)
            user_data[chat_id] = {}

    # Сценарий 2: Пользователь писал комментарий (восстанавливаем ввод)
    elif user_state == STATES['WAIT_COMMENT']:
        item = session.query(Storage).get(temp.get('item_id'))
        qty = temp.get('qty')
        if item:
            text_to_send = f"🔽 Продолжаем оформление:\n\nТовар: **{item.item_name}**\nКоличество: {qty}\n\n📝 Напишите комментарий (цель использования):"

    # Сценарий 3: Пользователь просто в меню (или заказ завершен)
    else:
        text_to_send = "Что-нибудь ещё? Выберите категорию:"
        markup_to_send = kb_categories(session)

    # --- 2. ОТПРАВКА НОВОГО СООБЩЕНИЯ ---
    try:
        msg = bot.send_message(chat_id, text_to_send, reply_markup=markup_to_send, parse_mode="Markdown")
        
        # Обновляем ID последнего сообщения в базе
        if user:
            user.last_msg_id = msg.message_id
            session.commit()
    except Exception as e:
        print(f"Error restoring UI: {e}")

# --- Клавиатуры ---
def kb_categories(session):
    markup = types.InlineKeyboardMarkup(row_width=2)
    categories = session.query(Storage.category).distinct().all()
    buttons = [types.InlineKeyboardButton(cat[0], callback_data=f"cat_{cat[0]}") for cat in categories]
    markup.add(*buttons)
    return markup

def kb_items(session, category):
    markup = types.InlineKeyboardMarkup(row_width=1)
    items = session.query(Storage).filter_by(category=category).all()
    for item in items:
        name = item.item_name
        if len(name) > 20: name = name[:20] + ".."
        btn_text = f"{name} (📦 {item.quantity})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"prod_{item.id}"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_main"))
    return markup

def kb_confirm():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_order"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_order")
    )
    return markup

# --- Handlers ---

@bot.message_handler(commands=['start'])
def cmd_start(message):
    session = get_db_session()
    user = get_user(session, message.chat.id)
    
    if user:
        # Если есть старое сообщение, удаляем его перед отправкой нового
        if user.last_msg_id:
            try:
                bot.delete_message(message.chat.id, user.last_msg_id)
            except: pass

        msg = bot.send_message(
            message.chat.id, 
            f"Привет, {user.first_name}! Выбери категорию:", 
            reply_markup=kb_categories(session)
        )
        user.last_msg_id = msg.message_id
        session.commit()
    else:
        user_data[message.chat.id] = {'state': STATES['REG_IT'], 'temp': {}}
        bot.send_message(message.chat.id, "Вы не зарегистрированы.\nВведите ваш IT-код (например, IT293):")
    
    session.close()

@bot.message_handler(commands=['add', 'add_item'])
def cmd_add_item(message):
    if str(message.chat.id) != str(GROUP_ID):
        bot.reply_to(message, "Команда доступна только в админ-группе.")
        return
    start_add_process(bot, message)
    
@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    if handle_admin_text(bot, message):
        return
    
    if str(chat_id) == str(GROUP_ID):
        return

    if chat_id not in user_data:
        return

    state = user_data[chat_id].get('state')
    text = message.text.strip()
    session = get_db_session()

    # Удаляем сообщение пользователя, чтобы не засорять чат (опционально)
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

    # --- РЕГИСТРАЦИЯ ---
    if state == STATES['REG_IT']:
        user_data[chat_id]['temp']['it_code'] = text
        user_data[chat_id]['state'] = STATES['REG_NAME']
        msg = bot.send_message(chat_id, "Введите Имя и Фамилию:")
        
    elif state == STATES['REG_NAME']:
        it_code = user_data[chat_id]['temp']['it_code']
        parts = text.split(maxsplit=1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""

        new_user = User(user_id=chat_id, it_code=it_code, first_name=first_name, last_name=last_name)
        session.add(new_user)
        try:
            session.commit()
            msg = bot.send_message(chat_id, "✅ Регистрация успешна!", reply_markup=kb_categories(session))
            new_user.last_msg_id = msg.message_id
            session.commit()
            user_data[chat_id] = {} 
        except Exception as e:
            bot.send_message(chat_id, "Ошибка регистрации. /start")
            session.rollback()

    # --- ЗАКАЗ ТОВАРА ---
    elif state == STATES['WAIT_QTY']:
        if not text.isdigit():
            # Тут можно отправить временное сообщение и удалить его
            return

        qty = int(text)
        item_id = user_data[chat_id]['temp']['item_id']
        item = session.query(Storage).get(item_id)

        if item.quantity < qty:
            bot.send_message(chat_id, f"❌ Недостаточно товара. Доступно: {item.quantity}")
            session.close()
            return

        user_data[chat_id]['temp']['qty'] = qty
        user_data[chat_id]['state'] = STATES['WAIT_COMMENT']
        
        # Обновляем старое сообщение (меню) на просьбу коммента
        user = session.query(User).filter_by(user_id=chat_id).first()
        last_id = user.last_msg_id if user else None

        if last_id:
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_id,
                    text=f"Товар: **{item.item_name}**\nКоличество: {qty}\n\n📝 Напишите комментарий (цель использования):",
                    parse_mode="Markdown"
                )
            except:
                # Если редактировать не вышло (например, старое удалено), шлем новое
                msg = bot.send_message(chat_id, f"Товар: {item.item_name}\nКоличество: {qty}\n\n📝 Напишите комментарий:")
                save_last_msg_id(chat_id, msg.message_id)

    elif state == STATES['WAIT_COMMENT']:
        user_data[chat_id]['temp']['comment'] = text
        temp = user_data[chat_id]['temp']
        item = session.query(Storage).get(temp['item_id'])
        
        summary = f"📋 **Проверка**:\nТовар: {item.item_name}\nКол-во: {temp['qty']}\nКоммент: {temp['comment']}"
        
        user = session.query(User).filter_by(user_id=chat_id).first()
        last_id = user.last_msg_id

        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_id,
                text=summary,
                parse_mode="Markdown",
                reply_markup=kb_confirm()
            )
        except:
            msg = bot.send_message(chat_id, summary, parse_mode="Markdown", reply_markup=kb_confirm())
            save_last_msg_id(chat_id, msg.message_id)

        user_data[chat_id]['state'] = None 

    session.close()

# --- Callback Handler ---
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    handle_admin_callback(bot, call)

    chat_id = call.message.chat.id
    data = call.data
    session = get_db_session()

    # === АДМИНСКАЯ ЛОГИКА ===
    if data.startswith("req_"):
        action, req_id = data.split(":")
        req_id = int(req_id)
        
        req = session.query(Request).get(req_id)
        if not req or req.status != 'pending':
            bot.answer_callback_query(call.id, "Заявка не актуальна")
            session.close()
            return

        user = req.user
        item = req.item
        
        # Переменная для текста уведомления юзеру
        notification_text = ""

        if action == "req_appr":
            if item.quantity >= req.req_count:
                item.quantity -= req.req_count
                req.is_approved = True
                req.status = 'approved'
                
                notification_text = f"✅ Ваша заявка #{req.id} на **{item.item_name}** одобрена! Можете забирать."
                
                new_text = call.message.text + f"\n\n✅ ОДОБРЕНО администратором."
                try:
                    bot.edit_message_text(new_text, chat_id, call.message.message_id, reply_markup=None)
                except: pass
            else:
                bot.answer_callback_query(call.id, "Мало товара!")
                session.close()
                return

        elif action == "req_rej":
            req.is_approved = False
            req.status = 'rejected'
            
            notification_text = f"⛔ Ваша заявка #{req.id} на **{item.item_name}** отклонена."
            
            new_text = call.message.text + f"\n\n⛔ ОТКЛОНЕНО администратором."
            try:
                bot.edit_message_text(new_text, chat_id, call.message.message_id, reply_markup=None)
            except: pass

        session.commit()
        
        # --- UX МАГИЯ ---
        if notification_text:
            try:
                # 1. Отправляем уведомление (оно падает в историю)
                bot.send_message(user.user_id, notification_text, parse_mode="Markdown")
                # 2. Восстанавливаем интерфейс (удаляем старое меню, рисуем новое внизу)
                restore_user_interface(user.user_id, session)
            except Exception as e:
                print(f"Ошибка UX обновления: {e}")
        
        session.close()
        return

    # === ЛОГИКА ПОЛЬЗОВАТЕЛЯ ===
    
    # Сохраняем ID текущего сообщения как "последнее", т.к. пользователь нажал на него
    save_last_msg_id(chat_id, call.message.message_id)

    if data.startswith("cat_"):
        cat = data.split("cat_")[1]
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"📂 Категория: {cat}",
            reply_markup=kb_items(session, cat)
        )

    elif data == "back_main":
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="Выберите категорию:",
            reply_markup=kb_categories(session)
        )

    elif data.startswith("prod_"):
        item_id = int(data.split("prod_")[1])
        item = session.query(Storage).get(item_id)
        
        user_data[chat_id] = {
            'state': STATES['WAIT_QTY'],
            'temp': {'item_id': item_id}
        }
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"Выбрано: {item.item_name}\nДоступно: {item.quantity}\n\n🔢 Введите количество в чат:"
        )

    elif data == "confirm_order":
        if chat_id not in user_data or 'temp' not in user_data[chat_id]:
            bot.answer_callback_query(call.id, "Сессия истекла")
            return

        temp = user_data[chat_id]['temp']
        item_id = temp['item_id']
        qty = temp['qty']
        comment = temp['comment']
        
        item = session.query(Storage).get(item_id)
        user = session.query(User).filter_by(user_id=chat_id).first()

        new_req = Request(
            user_pk=user.id,
            item_id=item_id,
            req_count=qty,
            comment=comment,
            status='pending'
        )
        session.add(new_req)
        session.commit()

        # Показываем Успех + Меню категорий (редактируя текущее сообщение)
        success_text = f"✅ **Заявка #{new_req.id} отправлена!**\n\nНужно заказать что-то ещё? Выберите категорию:"
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=success_text,
            parse_mode="Markdown",
            reply_markup=kb_categories(session)
        )
        
        markup_admin = types.InlineKeyboardMarkup()
        markup_admin.add(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"req_appr:{new_req.id}"),
            types.InlineKeyboardButton("⛔ Отказать", callback_data=f"req_rej:{new_req.id}")
        )
        
        report = (
            f"📦 **НОВАЯ ЗАЯВКА** #{new_req.id}\n"
            f"▸ Сотрудник: {user.it_code} ({user.first_name} {user.last_name})\n"
            f"▸ Товар: {item.item_name}\n"
            f"▸ Запрос: {qty} шт.\n"
            f"▸ На складе: {item.quantity} шт.\n\n"
            f"💬 Цель: {comment}"
        )
        
        bot.send_message(GROUP_ID, report, parse_mode="Markdown", reply_markup=markup_admin)
        clear_state(chat_id)

    elif data == "cancel_order":
        clear_state(chat_id)
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="❌ Отменено.\nВыберите категорию:",
            reply_markup=kb_categories(session)
        )

    session.close()

if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling()