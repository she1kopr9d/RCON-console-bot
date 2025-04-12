import os
import logging
import json
from typing import List, Dict
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from mcrcon import MCRcon

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=os.getenv('BOT_TOKEN'))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Get admin IDs from environment variable
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]

# Create data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# File to store servers data
SERVERS_FILE = os.path.join(DATA_DIR, 'servers.json')

# States for adding a new server
class AddServer(StatesGroup):
    waiting_for_name = State()
    waiting_for_host = State()
    waiting_for_port = State()
    waiting_for_password = State()

# States for executing commands
class CommandState(StatesGroup):
    waiting_for_command = State()
    console_mode = State()

def load_servers() -> Dict:
    try:
        with open(SERVERS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_servers(servers: Dict):
    with open(SERVERS_FILE, 'w') as f:
        json.dump(servers, f, indent=4)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_user_servers(user_id: int) -> Dict:
    servers = load_servers()
    user_servers = servers.get(str(user_id), {})
    return user_servers

def save_user_servers(user_id: int, user_servers: Dict):
    servers = load_servers()
    servers[str(user_id)] = user_servers
    save_servers(servers)

async def execute_rcon_command(server: Dict, command: str) -> str:
    try:
        with MCRcon(server['host'], server['password'], port=server['port']) as mcr:
            response = mcr.command(command)
            return response
    except Exception as e:
        return f"Error executing command: {str(e)}"

def get_servers_keyboard(user_id: int) -> InlineKeyboardBuilder:
    user_servers = get_user_servers(user_id)
    builder = InlineKeyboardBuilder()
    
    for server_id, server in user_servers.items():
        builder.button(
            text=f"{server['name']} ({server['host']})",
            callback_data=f"select_server_{server_id}"
        )
    
    builder.button(text="➕ Добавить сервер", callback_data="add_server")
    builder.adjust(1)
    return builder

@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = get_servers_keyboard(message.from_user.id)
    await message.answer(
        "👋 Добро пожаловать в Minecraft RCON Bot!\n\n"
        "🤖 Этот бот позволяет управлять вашими Minecraft серверами через RCON.\n\n"
        "📋 Доступные функции:\n"
        "• Просмотр статуса сервера\n"
        "• Список онлайн игроков\n"
        "• Выполнение RCON команд\n"
        "• Управление несколькими серверами\n"
        "• Режим консоли для быстрого ввода команд\n\n"
        "🛠 Как использовать:\n"
        "1. Добавьте сервер через меню\n"
        "2. Выберите сервер из списка\n"
        "3. Выберите нужное действие\n\n"
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data.startswith("select_server_"))
async def select_server(callback: CallbackQuery):
    server_id = callback.data.split("_")[-1]
    user_servers = get_user_servers(callback.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await callback.answer("Сервер не найден.")
        return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Статус сервера", callback_data=f"server_status_{server_id}")
    builder.button(text="👥 Игроки онлайн", callback_data=f"server_players_{server_id}")
    builder.button(text="⚙️ Выполнить команду", callback_data=f"server_cmd_{server_id}")
    builder.button(text="📟 Открыть консоль", callback_data=f"open_console_{server_id}")
    builder.button(text="❌ Удалить сервер", callback_data=f"delete_server_{server_id}")
    builder.button(text="🔙 Назад", callback_data="back_to_servers")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"🎮 Сервер: {server['name']}\n"
        f"🌐 Адрес: {server['host']}\n"
        f"🔌 Порт: {server['port']}\n\n"
        "Выберите действие:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "back_to_servers")
async def back_to_servers(callback: CallbackQuery):
    keyboard = get_servers_keyboard(callback.from_user.id)
    await callback.message.edit_text(
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data.startswith("open_console_"))
async def open_console(callback: CallbackQuery, state: FSMContext):
    server_id = callback.data.split("_")[-1]
    user_servers = get_user_servers(callback.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await callback.answer("Сервер не найден.")
        return
    
    await state.set_state(CommandState.console_mode)
    await state.update_data(server_id=server_id)
    
    await callback.message.edit_text(
        f"📟 Консоль сервера {server['name']} открыта\n\n"
        "Теперь вы можете отправлять команды напрямую.\n"
        "Используйте /close для закрытия консоли."
    )

@dp.message(Command("close"))
async def close_console(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != CommandState.console_mode:
        return
    
    await state.clear()
    await message.answer("Консоль закрыта.")
    keyboard = get_servers_keyboard(message.from_user.id)
    await message.answer(
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

@dp.message(CommandState.console_mode)
async def handle_console_command(message: Message, state: FSMContext):
    data = await state.get_data()
    server_id = data.get('server_id')
    
    if not server_id:
        await message.answer("Ошибка: сервер не выбран.")
        return
    
    user_servers = get_user_servers(message.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await message.answer("Сервер не найден.")
        return
    
    response = await execute_rcon_command(server, message.text)
    await message.answer(f"Ответ сервера:\n{response}")

@dp.callback_query(F.data.startswith("delete_server_"))
async def delete_server(callback: CallbackQuery):
    server_id = callback.data.split("_")[-1]
    user_servers = get_user_servers(callback.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await callback.answer("Сервер не найден.")
        return
    
    del user_servers[server_id]
    save_user_servers(callback.from_user.id, user_servers)
    
    await callback.answer(f"Сервер '{server['name']}' удален.")
    keyboard = get_servers_keyboard(callback.from_user.id)
    await callback.message.edit_text(
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data.startswith("server_status_"))
async def server_status(callback: CallbackQuery):
    server_id = callback.data.split("_")[-1]
    user_servers = get_user_servers(callback.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await callback.answer("Сервер не найден.")
        return
    
    response = await execute_rcon_command(server, "list")
    await callback.message.edit_text(f"Статус сервера:\n{response}")

@dp.callback_query(F.data.startswith("server_players_"))
async def server_players(callback: CallbackQuery):
    server_id = callback.data.split("_")[-1]
    user_servers = get_user_servers(callback.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await callback.answer("Сервер не найден.")
        return
    
    response = await execute_rcon_command(server, "list")
    await callback.message.edit_text(f"Игроки онлайн:\n{response}")

@dp.callback_query(F.data.startswith("server_cmd_"))
async def server_cmd(callback: CallbackQuery, state: FSMContext):
    server_id = callback.data.split("_")[-1]
    user_servers = get_user_servers(callback.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await callback.answer("Сервер не найден.")
        return
    
    await state.set_state(CommandState.waiting_for_command)
    await state.update_data(server_id=server_id)
    
    await callback.message.edit_text(
        f"Введите команду для выполнения на сервере {server['name']}:\n"
        "Используйте /cancel для отмены."
    )

@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.")
    keyboard = get_servers_keyboard(message.from_user.id)
    await message.answer(
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

@dp.message(CommandState.waiting_for_command)
async def handle_command(message: Message, state: FSMContext):
    data = await state.get_data()
    server_id = data.get('server_id')
    
    if not server_id:
        await message.answer("Ошибка: сервер не выбран.")
        return
    
    user_servers = get_user_servers(message.from_user.id)
    server = user_servers.get(server_id)
    
    if not server:
        await message.answer("Сервер не найден.")
        return
    
    response = await execute_rcon_command(server, message.text)
    await message.answer(f"Ответ сервера:\n{response}")
    
    await state.clear()
    keyboard = get_servers_keyboard(message.from_user.id)
    await message.answer(
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data == "add_server")
async def add_server_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddServer.waiting_for_name)
    await callback.message.edit_text(
        "Введите название сервера:",
        reply_markup=InlineKeyboardBuilder().button(text="❌ Отмена", callback_data="cancel_add").as_markup()
    )

@dp.callback_query(F.data == "cancel_add")
async def cancel_add_server(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    keyboard = get_servers_keyboard(callback.from_user.id)
    await callback.message.edit_text(
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

@dp.message(AddServer.waiting_for_name)
async def process_server_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddServer.waiting_for_host)
    await message.answer("Введите IP-адрес или домен сервера:")

@dp.message(AddServer.waiting_for_host)
async def process_server_host(message: Message, state: FSMContext):
    await state.update_data(host=message.text)
    await state.set_state(AddServer.waiting_for_port)
    await message.answer("Введите порт RCON (обычно 25575):")

@dp.message(AddServer.waiting_for_port)
async def process_server_port(message: Message, state: FSMContext):
    try:
        port = int(message.text)
        await state.update_data(port=port)
        await state.set_state(AddServer.waiting_for_password)
        await message.answer("Введите пароль RCON:")
    except ValueError:
        await message.answer("Пожалуйста, введите корректный номер порта:")

@dp.message(AddServer.waiting_for_password)
async def process_server_password(message: Message, state: FSMContext):
    data = await state.get_data()
    user_servers = get_user_servers(message.from_user.id)
    
    # Generate a new server ID
    server_id = str(len(user_servers) + 1)
    
    # Add new server
    user_servers[server_id] = {
        'name': data['name'],
        'host': data['host'],
        'port': data['port'],
        'password': message.text
    }
    
    save_user_servers(message.from_user.id, user_servers)
    await state.clear()
    
    keyboard = get_servers_keyboard(message.from_user.id)
    await message.answer(
        f"✅ Сервер '{data['name']}' успешно добавлен!\n\n"
        "Выберите сервер для управления или добавьте новый:",
        reply_markup=keyboard.as_markup()
    )

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main()) 