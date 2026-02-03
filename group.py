from telebot import types
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DB_URL, GROUP_ID
from models import Storage, Request, User
from decimal import Decimal, InvalidOperation

# Создаем подключение
engine = create_engine(DB_URL, pool_recycle=3600)
Session = sessionmaker(bind=engine)

def get_db_session():
    return Session()

# --- СОСТОЯНИЯ (FSM) ---
ADMIN_STATES = {}
(
    ADM_WAIT_CAT,        # 0
    ADM_WAIT_NAME,       # 1
    ADM_WAIT_QTY,        # 2
    ADM_NEW_CAT_TXT,     # 3
    ADM_NEW_NAME_TXT,    # 4
    ADM_WAIT_COST,       # 5 
    
    ADM_EDIT_MENU,       # 6
    ADM_EDIT_CAT_TXT,    # 7
    ADM_EDIT_NAME_TXT,   # 8
    ADM_EDIT_COST_TXT,   # 9
    ADM_CONFIRM_DEL      # 10 - Подтверждение удаления
) = range(11)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def parse_cost_price(text: str) -> Decimal:
    """Парсинг цены из текста"""
    t = text.strip().replace(" ", "").replace(",", ".")
    try:
        val = Decimal(t)
        if val < 0:
            raise InvalidOperation("negative")
        return val.quantize(Decimal("0.01"))
    except:
        raise ValueError

def cleanup_last_msg(bot, user_id, chat_id):
    """Удаляет последнее сообщение меню"""
    if user_id in ADMIN_STATES and 'last_msg_id' in ADMIN_STATES[user_id]:
        try:
            bot.delete_message(chat_id, ADMIN_STATES[user_id]['last_msg_id'])
        except:
            pass

def reopen_admin_menu(bot, user_id, chat_id, text_prefix=""):
    """
    Переотправляет главное меню.
    Инициализирует состояние, если оно потеряно после перезагрузки.
    """
    session = get_db_session()
    
    current_data = ADMIN_STATES.get(user_id, {})
    mode = current_data.get('mode', 'add')
    
    ADMIN_STATES[user_id] = {
        'state': ADM_WAIT_CAT,
        'mode': mode,
        'data': {} 
    }
    header = "📦 Пополнение склада (/add)" if mode == 'add' else "🛠 Редактор товаров (/edit)"
    
    cleanup_last_msg(bot, user_id, chat_id)
    
    if text_prefix:
        try:
            bot.send_message(chat_id, text_prefix)
        except: 
            pass

    try:
        msg = bot.send_message(
            chat_id, 
            f"{header}\nВыберите категорию:", 
            reply_markup=kb_admin_categories(session)
        )
        ADMIN_STATES[user_id]['last_msg_id'] = msg.message_id
    except Exception as e:
        try:
            msg = bot.send_message(chat_id, f"{header}\nВыберите категорию:", reply_markup=kb_admin_categories(session))
            ADMIN_STATES[user_id]['last_msg_id'] = msg.message_id
        except: pass
        
    session.close()

# --- КЛАВИАТУРЫ ---

def kb_admin_categories(session):
    markup = types.InlineKeyboardMarkup(row_width=2)
    categories = session.query(Storage.category).distinct().all()
    # Фильтруем пустые
    btns = [types.InlineKeyboardButton(cat[0], callback_data=f"adm_cat_exist:{cat[0]}") for cat in categories if cat[0]]
    markup.add(*btns)
    
    markup.add(types.InlineKeyboardButton("➕ Новая категория", callback_data="adm_cat_new"))
    markup.add(types.InlineKeyboardButton("Отмена", callback_data="adm_cancel"))
    return markup

def kb_admin_items(session, category, mode='add'):
    markup = types.InlineKeyboardMarkup(row_width=1)
    items = session.query(Storage).filter_by(category=category).all()
    
    for item in items:
        if mode == 'add':
            btn_text = f"{item.item_name} (📦 {item.quantity})"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"adm_item_exist:{item.id}"))
        else:
            btn_text = f"✏️ {item.item_name} ({item.cost_price})"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"adm_item_edit:{item.id}"))
    
    if mode == 'add':
        markup.add(types.InlineKeyboardButton("➕ Новый товар", callback_data="adm_item_new"))
    else:
        markup.add(types.InlineKeyboardButton("🏷 Переим. категорию", callback_data=f"adm_cat_ren:{category}"))
        markup.add(types.InlineKeyboardButton("🗑 Удалить категорию", callback_data=f"adm_cat_del:{category}"))

    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="adm_back_cat"))
    return markup

def kb_edit_item_menu(item_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📝 Изменить название", callback_data=f"edt_name:{item_id}"))
    markup.add(types.InlineKeyboardButton("💰 Изменить себестоимость", callback_data=f"edt_cost:{item_id}"))
    markup.add(types.InlineKeyboardButton("🗑 Удалить товар", callback_data=f"edt_del:{item_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Назад к списку", callback_data=f"edt_back:{item_id}"))
    return markup

def kb_cancel_no_emoji():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Отмена", callback_data="adm_cancel"))
    return markup

def kb_confirm_delete(target_type, target_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🗑 Да, удалить", callback_data=f"conf_del:{target_type}:{target_id}"),
        types.InlineKeyboardButton("Нет, отмена", callback_data="adm_cancel")
    )
    return markup

# --- ЛОГИКА АДМИНИСТРАТОРА (СТАРТ) ---

def start_add_process(bot, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    ADMIN_STATES[user_id] = {'state': ADM_WAIT_CAT, 'mode': 'add', 'data': {}}
    reopen_admin_menu(bot, user_id, chat_id)

def start_edit_process(bot, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    ADMIN_STATES[user_id] = {'state': ADM_WAIT_CAT, 'mode': 'edit', 'data': {}}
    reopen_admin_menu(bot, user_id, chat_id)

# --- ОБРАБОТЧИК CALLBACK (КНОПКИ) ---

def handle_admin_callback(bot, call):
    user_id = call.from_user.id
    data = call.data
    chat_id = call.message.chat.id
    session = get_db_session()

    try:
        # 1. ОТМЕНА / НАЗАД
        if data == "adm_cancel":
            reopen_admin_menu(bot, user_id, chat_id, text_prefix="❌ Действие отменено.")
            return

        if data == "adm_back_cat":
            if user_id not in ADMIN_STATES: ADMIN_STATES[user_id] = {'mode': 'add', 'data': {}}
            ADMIN_STATES[user_id]['state'] = ADM_WAIT_CAT
            
            mode = ADMIN_STATES[user_id].get('mode', 'add')
            header = "📦 Пополнение склада:" if mode == 'add' else "🛠 Редактор товаров:"
            
            bot.edit_message_text(
                f"{header}\nВыберите категорию:", 
                chat_id, call.message.message_id, 
                reply_markup=kb_admin_categories(session),
                parse_mode="Markdown"
            )
            return

        # 2. НАВИГАЦИЯ
        if data == "adm_cat_new":
            if user_id not in ADMIN_STATES: ADMIN_STATES[user_id] = {'mode': 'add', 'data': {}}
            ADMIN_STATES[user_id]['state'] = ADM_NEW_CAT_TXT
            bot.edit_message_text("✍ Введите название НОВОЙ категории:", chat_id, call.message.message_id, reply_markup=kb_cancel_no_emoji())
            return

        if data.startswith("adm_cat_exist:"):
            if user_id not in ADMIN_STATES: ADMIN_STATES[user_id] = {'mode': 'add', 'data': {}}
            category = data.split(":", 1)[1]
            ADMIN_STATES[user_id]['state'] = ADM_WAIT_NAME
            ADMIN_STATES[user_id]['data']['category'] = category
            
            mode = ADMIN_STATES[user_id].get('mode', 'add')
            txt = f"\n📂 Категория: {category}\n" + ("Добавление кол-ва:" if mode == 'add' else "Редактирование:")
            
            bot.edit_message_text(txt, chat_id, call.message.message_id, reply_markup=kb_admin_items(session, category, mode))
            return

        # 3. ADD MODE
        if data == "adm_item_new":
            ADMIN_STATES[user_id]['state'] = ADM_NEW_NAME_TXT
            bot.edit_message_text("✍ Введите название НОВОГО товара:", chat_id, call.message.message_id, reply_markup=kb_cancel_no_emoji())
            return

        if data.startswith("adm_item_exist:"):
            if user_id not in ADMIN_STATES: ADMIN_STATES[user_id] = {'mode': 'add', 'data': {}}
            item_id = int(data.split(":")[1])
            item = session.query(Storage).get(item_id)
            
            ADMIN_STATES[user_id]['state'] = ADM_WAIT_QTY
            if item:
                ADMIN_STATES[user_id]['data'].update({'item_name': item.item_name, 'exist_id': item_id, 'category': item.category})
                bot.edit_message_text(
                    f"📦 {item.item_name}\nОстаток: {item.quantity}\nСебестоимость: {item.cost_price}₸\n\n▸ Введите кол-во для добавления:", 
                    chat_id, call.message.message_id, 
                    reply_markup=kb_cancel_no_emoji()
                )
            else:
                bot.answer_callback_query(call.id, "Товар не найден")
            return

        # 4. EDIT MODE
        if data.startswith("adm_item_edit:"):
            if user_id not in ADMIN_STATES: ADMIN_STATES[user_id] = {'mode': 'edit', 'data': {}}
            item_id = int(data.split(":")[1])
            item = session.query(Storage).get(item_id)
            
            ADMIN_STATES[user_id]['state'] = ADM_EDIT_MENU
            if item:
                ADMIN_STATES[user_id]['data'].update({'edit_id': item_id, 'category': item.category})
                bot.edit_message_text(
                    f"🛠 {item.item_name}\nСебестоимость: {item.cost_price}₸", 
                    chat_id, call.message.message_id, 
                    reply_markup=kb_edit_item_menu(item_id)
                )
            return

        if data.startswith("edt_back:"):
            if user_id not in ADMIN_STATES: ADMIN_STATES[user_id] = {'mode': 'edit', 'data': {}}
            item_id = int(data.split(":")[1])
            item = session.query(Storage).get(item_id)
            
            ADMIN_STATES[user_id]['state'] = ADM_WAIT_NAME
            if item:
                ADMIN_STATES[user_id]['data']['category'] = item.category
                bot.edit_message_text(f"📂 Категория: {item.category}", chat_id, call.message.message_id, reply_markup=kb_admin_items(session, item.category, mode='edit'))
            return

        if data.startswith("edt_name:"):
            ADMIN_STATES[user_id]['state'] = ADM_EDIT_NAME_TXT
            bot.edit_message_text("✍ Введите НОВОЕ название:", chat_id, call.message.message_id, reply_markup=kb_cancel_no_emoji())
            return

        if data.startswith("edt_cost:"):
            ADMIN_STATES[user_id]['state'] = ADM_EDIT_COST_TXT
            bot.edit_message_text("💰 Введите НОВУЮ себестоимость:", chat_id, call.message.message_id, reply_markup=kb_cancel_no_emoji())
            return

        if data.startswith("adm_cat_ren:"):
            cat_name = data.split(":", 1)[1]
            ADMIN_STATES[user_id]['state'] = ADM_EDIT_CAT_TXT
            ADMIN_STATES[user_id]['data']['old_cat_name'] = cat_name
            bot.edit_message_text(f"✍ Категория: {cat_name}\nВведите НОВОЕ название:", chat_id, call.message.message_id, reply_markup=kb_cancel_no_emoji())
            return

        # 5. УДАЛЕНИЕ (Подтверждение)
        if data.startswith("edt_del:"):
            item_id = int(data.split(":")[1])
            item = session.query(Storage).get(item_id)
            ADMIN_STATES[user_id]['state'] = ADM_CONFIRM_DEL
            
            # УБРАЛИ parse_mode="Markdown" и звездочки
            bot.edit_message_text(
                f"⚠️ Удалить товар '{item.item_name}'?", 
                chat_id, call.message.message_id, 
                reply_markup=kb_confirm_delete('item', item_id)
            )
            return

        if data.startswith("adm_cat_del:"):
            cat_name = data.split(":", 1)[1]
            ADMIN_STATES[user_id]['state'] = ADM_CONFIRM_DEL
            count = session.query(Storage).filter_by(category=cat_name).count()
            
            # УБРАЛИ parse_mode="Markdown" и звездочки
            bot.edit_message_text(
                f"⛔️ Удалить категорию '{cat_name}' и ВСЕ её товары ({count} шт)?", 
                chat_id, call.message.message_id, 
                reply_markup=kb_confirm_delete('cat', cat_name)
            )
            return

        # 6. УДАЛЕНИЕ (Логика с ручной очисткой связей)
        if data.startswith("conf_del:"):
            _, target_type, target_id = data.split(":", 2)
            msg_result = ""
            
            try:
                if target_type == 'item':
                    # Удаление товара: сначала удаляем все заявки на него
                    item = session.query(Storage).get(int(target_id))
                    if item:
                        name = item.item_name
                        # Удаляем заявки
                        session.query(Request).filter(Request.item_id == item.id).delete(synchronize_session=False)
                        # Удаляем товар
                        session.delete(item)
                        session.commit()
                        msg_result = f"🗑 Товар '{name}' удален."
                    else:
                        msg_result = "Ошибка: товар не найден."

                elif target_type == 'cat':
                    # Удаление категории: находим товары -> удаляем заявки -> удаляем товары
                    items = session.query(Storage).filter_by(category=target_id).all()
                    deleted_count = 0
                    
                    for itm in items:
                        # Удаляем заявки для текущего товара
                        session.query(Request).filter(Request.item_id == itm.id).delete(synchronize_session=False)
                        # Удаляем сам товар
                        session.delete(itm)
                        deleted_count += 1
                        
                    session.commit()
                    msg_result = f"🗑 Категория '{target_id}' удалена ({deleted_count} товаров)."
            
            except Exception as e:
                session.rollback()
                msg_result = f"Ошибка удаления: {e}"
                print(f"Delete Error: {e}")

            reopen_admin_menu(bot, user_id, chat_id, text_prefix=msg_result)
            return

        # ЗАЯВКИ
        if data.startswith("req_appr:") or data.startswith("req_rej:"):
            # Старая логика заявок (оставляем без изменений)
            pass

    except Exception as e:
        print(f"Callback Error: {e}")
        try: bot.answer_callback_query(call.id, "Ошибка сессии")
        except: pass
    finally:
        session.close()

# --- ОБРАБОТЧИК ТЕКСТА ---

def handle_admin_text(bot, message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    
    if user_id not in ADMIN_STATES: return False
    
    state = ADMIN_STATES[user_id].get('state')
    data = ADMIN_STATES[user_id].get('data', {})
    
    try: bot.delete_message(chat_id, message.message_id)
    except: pass
    
    session = get_db_session()
    
    try:
        if state == ADM_NEW_CAT_TXT:
            ADMIN_STATES[user_id]['data']['category'] = text
            ADMIN_STATES[user_id]['state'] = ADM_NEW_NAME_TXT
            bot.edit_message_text(f"Категория: {text}\n✍ Название первого товара:", chat_id, ADMIN_STATES[user_id]['last_msg_id'], reply_markup=kb_cancel_no_emoji())
            return True
        
        elif state == ADM_NEW_NAME_TXT:
            ADMIN_STATES[user_id]['data']['item_name'] = text
            ADMIN_STATES[user_id]['state'] = ADM_WAIT_COST
            bot.edit_message_text(f"Товар: {text}\n💰 Себестоимость:", chat_id, ADMIN_STATES[user_id]['last_msg_id'], reply_markup=kb_cancel_no_emoji())
            return True
        
        elif state == ADM_WAIT_COST:
            try:
                cost = parse_cost_price(text)
                ADMIN_STATES[user_id]['data']['cost_price'] = cost
                ADMIN_STATES[user_id]['state'] = ADM_WAIT_QTY
                bot.edit_message_text(f"Себестоимость: {cost}\n🔢 Введите кол-во:", chat_id, ADMIN_STATES[user_id]['last_msg_id'], reply_markup=kb_cancel_no_emoji())
                return True
            except:
                bot.send_message(chat_id, "Ошибка цены. Попробуйте еще раз.")
                return True

        elif state == ADM_WAIT_QTY:
            if not text.isdigit():
                bot.send_message(chat_id, "Введите число!")
                return True
            qty = int(text)
            exist_id = data.get('exist_id')
            category = data.get('category')
            
            if exist_id:
                item = session.query(Storage).get(exist_id)
                if item:
                    item.quantity += qty
                    msg = f"✅ Товар обновлен! Остаток: {item.quantity}"
            else:
                name = data.get('item_name')
                cost = data.get('cost_price')
                exist = session.query(Storage).filter_by(item_name=name).first()
                if exist:
                    exist.quantity += qty
                    msg = f"✅ Товар пополнен! Остаток: {exist.quantity}"
                else:
                    new_item = Storage(category=category, item_name=name, quantity=qty, cost_price=cost)
                    session.add(new_item)
                    msg = f"✅ Товар создан! Остаток: {qty}"
            
            session.commit()
            reopen_admin_menu(bot, user_id, chat_id, text_prefix=msg)
            return True

        elif state == ADM_EDIT_NAME_TXT:
            item = session.query(Storage).get(data.get('edit_id'))
            if item:
                item.item_name = text
                session.commit()
                reopen_admin_menu(bot, user_id, chat_id, text_prefix=f"✅ Переименовано: {text}")
            return True

        elif state == ADM_EDIT_COST_TXT:
            try:
                cost = parse_cost_price(text)
                item = session.query(Storage).get(data.get('edit_id'))
                if item:
                    item.cost_price = cost
                    session.commit()
                    reopen_admin_menu(bot, user_id, chat_id, text_prefix=f"✅ Цена обновлена: {cost}")
                return True
            except: return True

        elif state == ADM_EDIT_CAT_TXT:
            old = data.get('old_cat_name')
            session.query(Storage).filter(Storage.category == old).update({Storage.category: text}, synchronize_session=False)
            session.commit()
            reopen_admin_menu(bot, user_id, chat_id, text_prefix=f"✅ Категория: {text}")
            return True

    finally:
        session.close()
    
    return False