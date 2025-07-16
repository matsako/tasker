import os
import json
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import openai

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PROMPT_PATH = os.getenv('PROMPT_PATH', 'prompt.txt')

openai.api_key = OPENAI_API_KEY

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

USER_DATA_FILE = 'user_data.json'

# --- Вспомогательные функции ---
def load_prompt():
    with open(PROMPT_PATH, 'r', encoding='utf-8') as f:
        return f.read()

def load_user_data():
    if not os.path.exists(USER_DATA_FILE):
        return {}
    with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_user_data(data):
    with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Состояния пользователя ---
user_states = {}

# --- Команды ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    data = load_user_data()
    if user_id not in data:
        data[user_id] = {
            'projects': [],
            'goals': [],
            'history': []
        }
        save_user_data(data)
        await message.answer("Привет! Давай настроим твои 4 проекта. Напиши их названия через запятую:")
        user_states[user_id] = 'awaiting_projects'
    else:
        await message.answer("С возвращением! Бот готов к работе. Используй /morning и /evening или жди напоминаний.")

@dp.message(lambda m: user_states.get(str(m.from_user.id)) == 'awaiting_projects')
async def set_projects(message: types.Message):
    user_id = str(message.from_user.id)
    projects = [p.strip() for p in message.text.split(',')][:4]
    if len(projects) < 4:
        await message.answer("Пожалуйста, укажи ровно 4 проекта через запятую.")
        return
    data = load_user_data()
    data[user_id]['projects'] = projects
    save_user_data(data)
    await message.answer("Теперь напиши главную цель для каждого проекта, тоже через запятую (в том же порядке):")
    user_states[user_id] = 'awaiting_goals'

@dp.message(lambda m: user_states.get(str(m.from_user.id)) == 'awaiting_goals')
async def set_goals(message: types.Message):
    user_id = str(message.from_user.id)
    goals = [g.strip() for g in message.text.split(',')][:4]
    if len(goals) < 4:
        await message.answer("Пожалуйста, укажи ровно 4 цели через запятую.")
        return
    data = load_user_data()
    data[user_id]['goals'] = goals
    save_user_data(data)
    await message.answer("Настройка завершена! Используй /morning и /evening или жди напоминаний.")
    user_states.pop(user_id, None)

# --- Утренний план ---
@dp.message(Command("morning"))
async def morning(message: types.Message):
    user_id = str(message.from_user.id)
    data = load_user_data()
    if user_id not in data or not data[user_id]['projects']:
        await message.answer("Сначала настрой проекты через /start.")
        return
    text = "Доброе утро! Опиши в свободной форме, что планируешь сделать сегодня по своим проектам. Можно писать как удобно — бот сам разберётся!"
    await message.answer(text)
    user_states[user_id] = 'awaiting_morning_tasks'

@dp.message(lambda m: user_states.get(str(m.from_user.id)) == 'awaiting_morning_tasks')
async def receive_morning_tasks(message: types.Message):
    user_id = str(message.from_user.id)
    tasks_text = message.text.strip()
    data = load_user_data()
    # Анализируем задачи через GPT
    prompt = load_prompt()
    user_projects = data[user_id]['projects']
    user_goals = data[user_id]['goals']
    gpt_input = f"Проекты: {user_projects}\nЦели: {user_goals}\nПланы на день (свободный текст): {tasks_text}\n\n{prompt}"
    gpt_response = await ask_gpt(gpt_input)
    # Сохраняем в историю
    data[user_id]['history'].append({'type': 'morning', 'tasks': tasks_text, 'gpt': gpt_response})
    save_user_data(data)
    await message.answer(f"Анализ и приоритеты на день:\n{gpt_response}")
    user_states.pop(user_id, None)

# --- Вечерний отчёт ---
@dp.message(Command("evening"))
async def evening(message: types.Message):
    user_id = str(message.from_user.id)
    data = load_user_data()
    if user_id not in data or not data[user_id]['projects']:
        await message.answer("Сначала настрой проекты через /start.")
        return
    text = "Вечер! Опиши в свободной форме, что удалось сделать по своим проектам. Можно писать как удобно — бот сам разберётся!"
    await message.answer(text)
    user_states[user_id] = 'awaiting_evening_report'

@dp.message(lambda m: user_states.get(str(m.from_user.id)) == 'awaiting_evening_report')
async def receive_evening_report(message: types.Message):
    user_id = str(message.from_user.id)
    reports_text = message.text.strip()
    data = load_user_data()
    # Анализируем отчёт через GPT
    prompt = load_prompt()
    user_projects = data[user_id]['projects']
    user_goals = data[user_id]['goals']
    gpt_input = f"Проекты: {user_projects}\nЦели: {user_goals}\nОтчёт за день (свободный текст): {reports_text}\n\n{prompt}"
    gpt_response = await ask_gpt(gpt_input)
    # Сохраняем в историю
    data[user_id]['history'].append({'type': 'evening', 'report': reports_text, 'gpt': gpt_response})
    save_user_data(data)
    await message.answer(f"Рефлексия и анализ дня:\n{gpt_response}")
    user_states.pop(user_id, None)

# --- GPT запрос ---
async def ask_gpt(prompt):
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.7
        )
    )
    return response['choices'][0]['message']['content'].strip()

# --- Планировщик напоминаний ---
scheduler = AsyncIOScheduler()

async def send_morning_reminder():
    data = load_user_data()
    for user_id in data:
        await bot.send_message(user_id, "Доброе утро! Не забудь отправить план на день через /morning")

async def send_evening_reminder():
    data = load_user_data()
    for user_id in data:
        await bot.send_message(user_id, "Вечер! Не забудь отправить отчёт через /evening")

async def on_startup():
    scheduler.add_job(send_morning_reminder, 'cron', hour=9, minute=0)
    scheduler.add_job(send_evening_reminder, 'cron', hour=20, minute=0)
    scheduler.start()

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
