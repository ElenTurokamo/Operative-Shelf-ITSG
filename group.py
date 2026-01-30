# group.py
from telebot import types
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DB_URL
from models import Storage, Request, User

# Создаем подключение здесь, чтобы избежать ошибок импорта
engine = create_engine(DB_URL, pool_recycle=3600)
Session = sessionmaker(bind=engine)

def get_db_session():
    return Session()

# Состояния для добавления товара (Admin FSM)
ADMIN_STATES = {}
(
    ADM_WAIT_CAT,    # 0: Ждем выбора категории (через кнопки)
    ADM_WAIT_NAME,   # 1: Ждем выбора названия (через кнопки)
    ADM_WAIT_QTY,    # 2: Ждем ввода количества (цифрами)
    ADM_NEW_CAT_TXT, # 3: Ввод новой категории вручную (текст)
    ADM_NEW_NAME_TXT # 4: Ввод нового названия вручную (текст)
) = range(5)

# --- КЛАВИАТУРЫ ---

def kb_admin_categories(session):
    markup = types.InlineKeyboardMarkup(row_width=2)
    categories = session.query(Storage.category).distinct().all()
    # Кнопки существующих категорий
    btns = [types.InlineKeyboardButton(cat[0], callback_data=f"adm_cat_exist:{cat[0]}") for cat in categories]
    markup.add(*btns)
    # Кнопка новой категории
    markup.add(types.InlineKeyboardButton("➕ Новая категория", callback_data="adm_cat_new"))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="adm_cancel"))
    return markup

def kb_admin_items(session, category):
    markup = types.InlineKeyboardMarkup(row_width=1)
    items = session.query(Storage).filter_by(category=category).all()
    
    for item in items:
        markup.add(types.InlineKeyboardButton(f"{item.item_name} (Сейчас: {item.quantity})", callback_data=f"adm_item_exist:{item.id}"))
    
    markup.add(types.InlineKeyboardButton("➕ Новый товар", callback_data="adm_item_new"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="adm_back_cat"))
    return markup

# --- ЛОГИКА АДМИНИСТРАТОРА (ДОБАВЛЕНИЕ) ---

def start_add_process(bot, message):
    """Запуск процесса добавления товара"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    session = get_db_session()
    
    ADMIN_STATES[user_id] = {'state': ADM_WAIT_CAT, 'data': {}}
    
    bot.send_message(
        chat_id, 
        "🛠 **Добавление товара**\nВыберите категорию или создайте новую:", 
        reply_markup=kb_admin_categories(session),
        parse_mode="Markdown"
    )
    session.close()

def handle_admin_callback(bot, call):
    """Обработчик всех кнопок в группе (Добавление и Заявки)"""
    user_id = call.from_user.id
    data = call.data
    chat_id = call.message.chat.id
    session = get_db_session()

    # --- 1. ЛОГИКА ДОБАВЛЕНИЯ ТОВАРА ---
    
    if data == "adm_cancel":
        if user_id in ADMIN_STATES:
            del ADMIN_STATES[user_id]
        bot.delete_message(chat_id, call.message.message_id)
        session.close()
        return

    if data == "adm_cat_new":
        ADMIN_STATES[user_id] = {'state': ADM_NEW_CAT_TXT, 'data': {}}
        bot.edit_message_text("✍ Введите название НОВОЙ категории:", chat_id, call.message.message_id)
        session.close()
        return

    if data.startswith("adm_cat_exist:"):
        category = data.split(":", 1)[1]
        ADMIN_STATES[user_id] = {'state': ADM_WAIT_NAME, 'data': {'category': category}}
        bot.edit_message_text(
            f"📂 Категория: {category}\nВыберите товар или создайте новый:", 
            chat_id, 
            call.message.message_id, 
            reply_markup=kb_admin_items(session, category)
        )
        session.close()
        return

    if data == "adm_back_cat":
        bot.edit_message_text("Выберите категорию:", chat_id, call.message.message_id, reply_markup=kb_admin_categories(session))
        session.close()
        return

    if data == "adm_item_new":
        # Если нажали "Новый товар" в существующей категории
        ADMIN_STATES[user_id]['state'] = ADM_NEW_NAME_TXT
        bot.edit_message_text("✍ Введите название НОВОГО товара:", chat_id, call.message.message_id)
        session.close()
        return

    if data.startswith("adm_item_exist:"):
        item_id = int(data.split(":")[1])
        item = session.query(Storage).get(item_id)
        ADMIN_STATES[user_id]['state'] = ADM_WAIT_QTY
        ADMIN_STATES[user_id]['data']['item_name'] = item.item_name
        # Сохраняем ID, чтобы обновить существующий
        ADMIN_STATES[user_id]['data']['exist_id'] = item_id 
        
        bot.edit_message_text(
            f"📦 Товар: {item.item_name}\n▸ Введите количество для добавления (цифрой):", 
            chat_id, 
            call.message.message_id
        )
        session.close()
        return

    # --- 2. ЛОГИКА ОБРАБОТКИ ЗАЯВОК (APPROVE/REJECT) ---

    if data.startswith("req_appr:") or data.startswith("req_rej:"):
        action, req_id = data.split(":")
        req_id = int(req_id)
        
        req = session.query(Request).get(req_id)
        
        if not req:
             bot.answer_callback_query(call.id, "Заявка не найдена.")
             session.close()
             return

        item = session.query(Storage).get(req.item_id)
        user = session.query(User).get(req.user_pk)
        
        # Проверяем статус по новой колонке
        if req.status != 'pending':
            bot.answer_callback_query(call.id, "Заявка уже обработана.")
            session.close()
            return

        if action == "req_appr":
            if item.quantity >= req.req_count:
                item.quantity -= req.req_count
                req.status = 'approved'
                req.is_approved = True # Для обратной совместимости
                session.commit()
                
                new_text = call.message.text + f"\n\n✅ ОДОБРЕНО администратором {call.from_user.first_name}"
                bot.edit_message_text(new_text, chat_id, call.message.message_id, reply_markup=None)
                
                try:
                    bot.send_message(user.user_id, f"✅ Ваша заявка на {item.item_name} одобрена! Можете забирать.")
                except:
                    pass
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка! Недостаточно товара на складе для подтверждения.")
        
        elif action == "req_rej":
            req.status = 'rejected'
            req.is_approved = False
            session.commit()
            
            new_text = call.message.text + f"\n\n⛔ ОТКЛОНЕНО администратором {call.from_user.first_name}"
            bot.edit_message_text(new_text, chat_id, call.message.message_id, reply_markup=None)
            
            try:
                bot.send_message(user.user_id, f"⛔ Ваша заявка на {item.item_name} была отклонена.")
            except:
                pass

    session.close()

def handle_admin_text(bot, message):
    """Обработка текста от админа (ввод названий, количеств)"""
    user_id = message.from_user.id
    
    # Если пользователя нет в состояниях админа, выходим
    if user_id not in ADMIN_STATES:
        return False
    
    state_info = ADMIN_STATES[user_id]
    state = state_info['state']
    data = state_info['data']
    text = message.text.strip()
    chat_id = message.chat.id
    
    session = get_db_session()

    # --- ИСПРАВЛЕННАЯ ЛОГИКА ---
    if state == ADM_NEW_CAT_TXT:
        ADMIN_STATES[user_id]['data']['category'] = text
        # ВАЖНО: Переключаем на состояние ВВОДА ТЕКСТА (ADM_NEW_NAME_TXT), а не выбора (ADM_WAIT_NAME)
        ADMIN_STATES[user_id]['state'] = ADM_NEW_NAME_TXT
        bot.send_message(chat_id, f"Категория: {text}\n✍ Введите название товара:")
        session.close()
        return True # Возвращаем True, чтобы main.py не обрабатывал это сообщение
    
    elif state == ADM_NEW_NAME_TXT:
        ADMIN_STATES[user_id]['data']['item_name'] = text
        ADMIN_STATES[user_id]['state'] = ADM_WAIT_QTY
        bot.send_message(chat_id, f"Товар: {text}\n🔢 Введите количество:")
        session.close()
        return True

    elif state == ADM_WAIT_QTY:
        if not text.isdigit():
            bot.send_message(chat_id, "❌ Введите число!")
            session.close()
            return True
        
        qty = int(text)
        category = data.get('category')
        item_name = data.get('item_name')
        exist_id = data.get('exist_id')
        
        if exist_id:
            # Обновляем существующий
            item = session.query(Storage).get(exist_id)
            item.quantity += qty
            action_text = "обновлен"
        else:
            # Создаем новый
            item = Storage(category=category, item_name=item_name, quantity=qty)
            session.add(item)
            action_text = "создан"
        
        session.commit()
        
        bot.send_message(chat_id, f"✅ Товар успешно {action_text}!\n{item.item_name} — {item.quantity} шт.")
        del ADMIN_STATES[user_id]
        session.close()
        return True
    
    session.close()
    return False