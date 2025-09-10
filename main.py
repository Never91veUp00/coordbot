import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from config import TOKEN
from db import init_db, close_db, migrate
from handlers import admin, user, registration, tasks, reports, files
from utils import set_commands
from filters import IsNotAdminFilter, IsAdminMessageFilter
from export_excel import listen_for_updates, main as export_main


def register_handlers(dp: Dispatcher):

    # ---------------- Files (ставим в начало, чтобы не перехватывали другие фильтры)
    dp.message.register(files.send_ldk_cmd, Command("sendldk"))
    dp.callback_query.register(files.choose_ldk_target, lambda c: c.data.startswith("ldk_target:"))
    dp.callback_query.register(files.cancel_ldk, lambda c: c.data == "ldk_cancel")
    dp.message.register(files.handle_ldk, lambda m: m.document and m.document.file_name.endswith(".ldk"))
    dp.message.register(files.handle_video, lambda m: m.video is not None)

    # ---------------- Admin
    dp.message.register(admin.add_admin, Command("addadmin"))
    dp.message.register(admin.del_admin_cmd, Command("deladmin"))
    dp.callback_query.register(admin.del_admin_cb, lambda c: c.data.startswith("deladm:"))
    dp.message.register(admin.list_admins, Command("admins"))
    dp.message.register(admin.show_ready_squads, Command("status"))
    dp.message.register(admin.show_active_tasks, Command("active"))
    dp.message.register(admin.add_user, Command("adduser"))

    # ---------------- User
    dp.message.register(user.finish_cmd, Command("finish"))
    dp.message.register(user.my_tasks, Command("mytasks"))
    dp.message.register(user.start_cmd, Command("start"))
    dp.message.register(user.reconfig, Command("config"))
    dp.message.register(user.my_id, Command("myid"))
    dp.message.register(user.support_cmd, Command("support"))
    dp.callback_query.register(user.set_bow, lambda c: c.data.startswith("bow:"))
    dp.callback_query.register(user.set_arrow, lambda c: c.data.startswith("arrow:"))

    dp.message.register(reports.handle_true_point, StateFilter(reports.ReportStates.await_true_point))

    # ---------------- Registration
    dp.message.register(registration.handle_registration, IsNotAdminFilter(), F.text & ~F.text.startswith("/"))
    dp.callback_query.register(registration.register_request, lambda c: c.data == "register_request")
    dp.callback_query.register(registration.approve_user, lambda c: c.data.startswith("approve:"))
    dp.callback_query.register(registration.reject_user, lambda c: c.data.startswith("reject:"))

    # ---------------- Tasks
    dp.message.register(tasks.task_cmd, Command("task"))
    dp.message.register(tasks.edit_task_cmd, Command("edittask"))
    dp.callback_query.register(tasks.choose_target, lambda c: c.data.startswith("task_squad:"))
    dp.message.register(tasks.handle_admin_task_message, IsAdminMessageFilter())
    dp.callback_query.register(tasks.edit_task_choose_squad, lambda c: c.data.startswith("edit_squad:"))
    dp.callback_query.register(tasks.edit_task_select, lambda c: c.data.startswith("edit_task:"))
    dp.callback_query.register(tasks.cancel_task, lambda c: c.data == "cancel_task")
    dp.callback_query.register(tasks.accept_task, lambda c: c.data.startswith("accept:"))
    dp.callback_query.register(tasks.set_ready, lambda c: c.data == "ready")

    # ---------------- Reports
    dp.message.register(reports.report_start, Command("report"))
    dp.callback_query.register(reports.choose_task, lambda c: c.data.startswith("choose_task:"))
    dp.callback_query.register(reports.handle_report, lambda c: c.data.startswith("report:"))
    dp.callback_query.register(reports.no_video, lambda c: c.data.startswith("novideo:"))
    dp.callback_query.register(reports.confirm_no_video, lambda c: c.data.startswith("confirm_novideo:"))
    dp.callback_query.register(reports.wait_video, lambda c: c.data.startswith("wait_video:"))


logging.basicConfig(level=logging.INFO)


async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    # БД
    await init_db()
    await migrate()

    # Хендлеры
    register_handlers(dp)

    # Команды
    await set_commands(bot)

    # Экспорт Excel
    await export_main()  # первый раз сформируем отчёт при старте
    asyncio.create_task(listen_for_updates())  # слушаем изменения в tasks

    logging.info("✅ Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
        await bot.session.close()
        logging.info("🛑 Бот остановлен корректно.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Получен сигнал завершения (CTRL+C). Бот остановлен.")
