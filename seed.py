import asyncio
from core.database import AsyncSessionLocal
from models.users import User
from models.bots import Bot
from models.menus import Menu
from models.buttons import Button
from models.button_actions import ButtonAction, ActionType


TOKEN = "5901209945:AAGQqHQmo5xOk-zlWYZJrNQOH48N8FmGoKU"


async def seed():
    async with AsyncSessionLocal() as session:
        user = User(tg_id=5502850858, full_name="Amirkhon")
        session.add(user)
        await session.flush()

        bot = Bot(
            owner_id=user.id,
            name="python Bot",
            token=TOKEN,
            is_active=True,
        )
        session.add(bot)
        await session.flush()

        menu = Menu(
            bot_id=bot.id,
            title="Asosiy menyu",
            is_start=True,
        )
        session.add(menu)
        await session.flush()

        button = Button(
            menu_id=menu.id,
            text="Salom tugma",
            position=1,
        )
        session.add(button)
        await session.flush()

        action = ButtonAction(
            button_id=button.id,
            action_type=ActionType.text,
            value="Salom! Constructor ishlayapti 🚀",
        )
        session.add(action)

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
