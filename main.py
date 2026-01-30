import telebot
from telebot import types
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import BOT_TOKEN, GROUP_ID, DB_URL
from models import Base, User, Storage, Request

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
        del user_data[chat_id]

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
        btn_text = f"{item.item_name} | Остаток: {item.quantity}"
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

# --- Handlers: Start и Регистрация ---

@bot.message_handler(commands=['start'])
def cmd_start(message):
    session = get_db_session()
    user = get_user(session, message.chat.id)
    session.close()

    if user:
        bot.send_message(
            message.chat.id, 
            f"Привет, {user.first_name}! Выбери категорию:", 
            reply_markup=kb_categories(get_db_session())
        )
    else:
        user_data[message.chat.id] = {'state': STATES['REG_IT'], 'temp': {}}
        bot.send_message(message.chat.id, "Вы не зарегистрированы.\nВведите ваш IT-код (например, IT293):")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        return

    state = user_data[chat_id].get('state')
    text = message.text.strip()

    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

    session = get_db_session()

    if state == STATES['REG_IT']:
        user_data[chat_id]['temp']['it_code'] = text
        user_data[chat_id]['state'] = STATES['REG_NAME']
        msg = bot.send_message(chat_id, "Введите Имя и Фамилию:")
        user_data[chat_id]['last_msg_id'] = msg.message_id 

    elif state == STATES['REG_NAME']:
        it_code = user_data[chat_id]['temp']['it_code']
        parts = text.split(maxsplit=1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""

        new_user = User(
            user_id=chat_id,
            it_code=it_code,
            first_name=first_name,
            last_name=last_name
        )
        session.add(new_user)
        try:
            session.commit()
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=user_data[chat_id]['last_msg_id'],
                text="✅ Регистрация успешна! Выберите категорию:",
                reply_markup=kb_categories(session)
            )
            user_data[chat_id] = {} 
        except Exception as e:
            bot.send_message(chat_id, "Ошибка регистрации. Возможно, такой IT-код уже есть.")
            session.rollback()
        
    elif state == STATES['WAIT_QTY']:
        if not text.isdigit():
            bot.send_message(chat_id, "❌ Пожалуйста, введите число.")
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
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=user_data[chat_id]['msg_id'],
            text=f"Товар: {item.item_name}\nКоличество: {qty}\n\n📝 Напишите комментарий (цель использования):"
        )

    elif state == STATES['WAIT_COMMENT']:
        user_data[chat_id]['temp']['comment'] = text
        temp = user_data[chat_id]['temp']
        item = session.query(Storage).get(temp['item_id'])
        
        summary_text = (
            f"📋 **Проверка данных**:\n"
            f"Товар: {item.item_name}\n"
            f"Кол-во: {temp['qty']}\n"
            f"Коммент: {temp['comment']}"
        )
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=user_data[chat_id]['msg_id'],
            text=summary_text,
            parse_mode="Markdown",
            reply_markup=kb_confirm()
        )
        user_data[chat_id]['state'] = None 

    session.close()

# --- Handlers: Callbacks (Кнопки) ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    session = get_db_session()

    if data.startswith("cat_"):
        category = data.split("cat_")[1]
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"📂 Категория: {category}",
            reply_markup=kb_items(session, category)
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
            'msg_id': call.message.message_id, 
            'temp': {'item_id': item_id}
        }
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"Выбрано: {item.item_name}\nДоступно: {item.quantity}\n\n🔢 Введите количество в чат:"
        )

    elif data == "confirm_order":
        if chat_id not in user_data or 'temp' not in user_data[chat_id]:
            bot.answer_callback_query(call.id, "Сессия истекла. Начните заново /start")
            return

        temp = user_data[chat_id]['temp']
        item_id = temp['item_id']
        qty = temp['qty']
        comment = temp['comment']
        
        try:
            item = session.query(Storage).with_for_update().get(item_id) 
            user = session.query(User).filter_by(user_id=chat_id).first()

            if item.quantity >= qty:
                item.quantity -= qty
                
                new_req = Request(
                    user_pk=user.id,
                    item_id=item_id,
                    req_count=qty,
                    comment=comment,
                    is_approved=True 
                )
                session.add(new_req)
                session.commit()

                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text="✅ Заявка успешно оформлена! Товар списан."
                )

                report = (
                    f"📦 **Новая выдача**\n"
                    f"👤 Сотрудник: {user.it_code} ({user.first_name} {user.last_name})\n"
                    f"🛠 Товар: {item.item_name}\n"
                    f"🔢 Кол-во: {qty}\n"
                    f"💬 Комментарий: {comment}"
                )
                bot.send_message(GROUP_ID, report, parse_mode="Markdown")
            else:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text="❌ Ошибка! Пока вы заполняли, товар закончился."
                )
        except Exception as e:
            session.rollback()
            bot.send_message(chat_id, f"Произошла ошибка базы данных: {e}")
        finally:
            clear_state(chat_id)

    elif data == "cancel_order":
        clear_state(chat_id)
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="❌ Заявка отменена. Вернуться в начало: /start"
        )

    session.close()

if __name__ == "__main__":
    print("---")
    print("Бот Оперативный ITSG запущен и готов к работе...")
    print("---")
    bot.infinity_polling()