""" system commands """
# Copyright (C) 2020-2022 by UsergeTeam@Github, < https://github.com/UsergeTeam >.
#
# This file is part of < https://github.com/UsergeTeam/Userge > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/UsergeTeam/Userge/blob/master/LICENSE >
#
# All rights reserved.

import time
import asyncio
import shutil

from pyrogram import Client
from pyrogram.types import User
from pyrogram.errors import SessionPasswordNeeded, YouBlockedUser

from userge.core.ext import RawClient
from userge import userge, Message, config, get_collection
from userge.utils import terminate, extract_entities
from userge.utils.exceptions import StopConversation
from .. import system

SAVED_SETTINGS = get_collection("CONFIGS")
DISABLED_CHATS = get_collection("DISABLED_CHATS")

MAX_IDLE_TIME = 300
LOG = userge.getLogger(__name__)
CHANNEL = userge.getCLogger(__name__)


@userge.on_start
async def _init() -> None:
    global MAX_IDLE_TIME  # pylint: disable=global-statement
    d_s = await SAVED_SETTINGS.find_one({'_id': 'DYNO_SAVER'})
    if d_s:
        system.Dynamic.RUN_DYNO_SAVER = bool(d_s['on'])
        MAX_IDLE_TIME = int(d_s['timeout'])
    disabled_all = await SAVED_SETTINGS.find_one({'_id': 'DISABLE_ALL_CHATS'})
    if disabled_all:
        system.Dynamic.DISABLED_ALL = bool(disabled_all['on'])
    else:
        async for i in DISABLED_CHATS.find():
            if i['_id'] == config.LOG_CHANNEL_ID:
                continue
            system.DISABLED_CHATS.add(i['_id'])


@userge.on_cmd('restart', about={
    'header': "Restarts the bot and reload all plugins",
    'flags': {
        '-h': "restart hard",
        '-d': "clean working folder"},
    'usage': "{tr}restart [flag | flags]",
    'examples': "{tr}restart -t -d"}, del_pre=True, allow_channels=False)
async def restart_(message: Message):
    """ restart userge """
    await message.edit("`Restarting Userge Services`", log=__name__)
    LOG.info("USERGE Services - Restart initiated")
    if 'd' in message.flags:
        shutil.rmtree(config.Dynamic.DOWN_PATH, ignore_errors=True)
    if 'h' in message.flags:
        await message.edit("`Restarting [HARD] ...`", del_in=1)
        await userge.restart(hard=True)
    else:
        await message.edit("`Restarting [SOFT] ...`", del_in=1)
        await userge.restart()


@userge.on_cmd("shutdown", about={'header': "shutdown userge :)"}, allow_channels=False)
async def shutdown_(message: Message) -> None:
    """ shutdown userge """
    await message.edit("`shutting down ...`")
    if config.HEROKU_APP:
        try:
            config.HEROKU_APP.process_formation()['worker'].scale(0)
        except Exception as h_e:  # pylint: disable=broad-except
            await message.edit(f"**heroku error** : `{h_e}`")
            await asyncio.sleep(3)
    else:
        await asyncio.sleep(1)
    await message.delete()
    terminate()


@userge.on_cmd("die", about={
    'header': "set auto heroku dyno off timeout",
    'flags': {'-t': "input offline timeout in min : default to 5min"},
    'usage': "{tr}die [flags]",
    'examples': ["{tr}die", "{tr}die -t5"]}, allow_channels=False)
async def die_(message: Message) -> None:
    """ set offline timeout to die userge """
    global MAX_IDLE_TIME  # pylint: disable=global-statement
    if not config.HEROKU_APP:
        await message.edit("`heroku app not detected !`", del_in=5)
        return
    await message.edit('`processing ...`')
    if system.Dynamic.RUN_DYNO_SAVER:
        if isinstance(system.Dynamic.RUN_DYNO_SAVER, asyncio.Task):
            system.Dynamic.RUN_DYNO_SAVER.cancel()
        system.Dynamic.RUN_DYNO_SAVER = False
        SAVED_SETTINGS.update_one({'_id': 'DYNO_SAVER'},
                                  {"$set": {'on': False}}, upsert=True)
        await message.edit('auto heroku dyno off worker has been **stopped**',
                           del_in=5, log=__name__)
        return
    time_in_min = int(message.flags.get('-t', 5))
    if time_in_min < 5:
        await message.err(f"`please set higher value [{time_in_min}] !`")
        return
    MAX_IDLE_TIME = time_in_min * 60
    SAVED_SETTINGS.update_one({'_id': 'DYNO_SAVER'},
                              {"$set": {'on': True, 'timeout': MAX_IDLE_TIME}}, upsert=True)
    await message.edit('auto heroku dyno off worker has been **started** '
                       f'[`{time_in_min}`min]', del_in=3, log=__name__)
    system.Dynamic.RUN_DYNO_SAVER = asyncio.get_event_loop().create_task(_dyno_saver_worker())


@userge.on_cmd("setvar", about={
    'header': "set var in heroku",
    'usage': "{tr}setvar [var_name] [var_data]",
    'examples': "{tr}setvar WORKERS 4"})
async def setvar_(message: Message) -> None:
    """ set var (heroku) """
    if not config.HEROKU_APP:
        await message.edit("`heroku app not detected !`", del_in=5)
        return
    if not message.input_str:
        await message.err("`input needed !`")
        return
    var_name, var_data = message.input_str.split(maxsplit=1)
    if not var_data:
        await message.err("`var data needed !`")
        return
    var_name = var_name.strip()
    var_data = var_data.strip()
    heroku_vars = config.HEROKU_APP.config()
    if var_name in heroku_vars:
        await CHANNEL.log(
            f"#HEROKU_VAR #SET #UPDATED\n\n`{var_name}` = `{var_data}`")
        await message.edit(f"`var {var_name} updated and forwarded to log channel !`", del_in=3)
    else:
        await CHANNEL.log(
            f"#HEROKU_VAR #SET #ADDED\n\n`{var_name}` = `{var_data}`")
        await message.edit(f"`var {var_name} added and forwarded to log channel !`", del_in=3)
    heroku_vars[var_name] = var_data


@userge.on_cmd("delvar", about={
    'header': "del var in heroku",
    'usage': "{tr}delvar [var_name]",
    'examples': "{tr}delvar WORKERS"})
async def delvar_(message: Message) -> None:
    """ del var (heroku) """
    if not config.HEROKU_APP:
        await message.edit("`heroku app not detected !`", del_in=5)
        return
    if not message.input_str:
        await message.err("`var name needed !`")
        return
    var_name = message.input_str.strip()
    heroku_vars = config.HEROKU_APP.config()
    if var_name not in heroku_vars:
        await message.err(f"`var {var_name} not found !`")
        return
    await CHANNEL.log(f"#HEROKU_VAR #DEL\n\n`{var_name}` = `{heroku_vars[var_name]}`")
    await message.edit(f"`var {var_name} deleted and forwarded to log channel !`", del_in=3)
    del heroku_vars[var_name]


@userge.on_cmd("getvar", about={
    'header': "get var in heroku",
    'usage': "{tr}getvar [var_name]",
    'examples': "{tr}getvar WORKERS"})
async def getvar_(message: Message) -> None:
    """ get var (heroku) """
    if not config.HEROKU_APP:
        await message.edit("`heroku app not detected !`", del_in=5)
        return
    if not message.input_str:
        await message.err("`var name needed !`")
        return
    var_name = message.input_str.strip()
    heroku_vars = config.HEROKU_APP.config()
    if var_name not in heroku_vars:
        await message.err(f"`var {var_name} not found !`")
        return
    await CHANNEL.log(f"#HEROKU_VAR #GET\n\n`{var_name}` = `{heroku_vars[var_name]}`")
    await message.edit(f"`var {var_name} forwarded to log channel !`", del_in=3)


@userge.on_cmd("enhere", about={
    'header': "enable userbot in disabled chat.",
    'flags': {'-all': "Enable Userbot in all chats."},
    'usage': "{tr}enhere [chat_id | username]\n{tr}enhere -all"})
async def enable_userbot(message: Message):
    if message.flags:
        if '-all' in message.flags:
            system.Dynamic.DISABLED_ALL = False
            system.DISABLED_CHATS.clear()
            await asyncio.gather(
                DISABLED_CHATS.drop(),
                SAVED_SETTINGS.update_one(
                    {'_id': 'DISABLE_ALL_CHATS'}, {"$set": {'on': False}}, upsert=True
                ),
                message.edit("**Enabled** all chats!", del_in=5))
        else:
            await message.err("invalid flag!")
    elif message.input_str:
        try:
            chat = await message.client.get_chat(message.input_str)
        except Exception as err:
            await message.err(str(err))
            return
        if chat.id not in system.DISABLED_CHATS:
            await message.edit("this chat is already enabled!")
        else:
            system.DISABLED_CHATS.remove(chat.id)
            await asyncio.gather(
                DISABLED_CHATS.delete_one(
                    {'_id': chat.id}
                ),
                message.edit(
                    f"CHAT : `{chat.title}` removed from **DISABLED_CHATS**!",
                    del_in=5,
                    log=__name__
                )
            )
    else:
        await message.err("chat_id not found!")


@userge.on_cmd("dishere", about={
    'header': "disable userbot in current chat.",
    'flags': {'-all': "disable Userbot in all chats."},
    'usage': "{tr}dishere\n{tr}dishere [chat_id | username]\n{tr}dishere -all"})
async def disable_userbot(message: Message):
    if message.flags:
        if '-all' in message.flags:
            system.Dynamic.DISABLED_ALL = True
            await asyncio.gather(
                SAVED_SETTINGS.update_one(
                    {'_id': 'DISABLE_ALL_CHATS'}, {"$set": {'on': True}}, upsert=True
                ),
                message.edit("**Disabled** all chats!", del_in=5))
        else:
            await message.err("invalid flag!")
    else:
        chat = message.chat
        if message.input_str:
            try:
                chat = await message.client.get_chat(message.input_str)
            except Exception as err:
                await message.err(str(err))
                return
        if chat.id in system.DISABLED_CHATS:
            await message.edit("this chat is already disabled!")
        elif chat.id == config.LOG_CHANNEL_ID:
            await message.err("can't disabled log channel")
        else:
            system.DISABLED_CHATS.add(chat.id)
            await asyncio.gather(
                DISABLED_CHATS.insert_one({'_id': chat.id, 'title': chat.title}),
                message.edit(
                    f"CHAT : `{chat.title}` added to **DISABLED_CHATS**!", del_in=5, log=__name__
                )
            )


@userge.on_cmd("listdisabled", about={'header': "List all disabled chats."})
async def view_disabled_chats_(message: Message):
    if system.Dynamic.DISABLED_ALL:
        # bot will not print this, but dont worry except log channel
        await message.edit("All chats are disabled!", del_in=5)
    elif not system.DISABLED_CHATS:
        await message.edit("**DISABLED_CHATS** not found!", del_in=5)
    else:
        out_str = '🚷 **DISABLED_CHATS** 🚷\n\n'
        async for chat in DISABLED_CHATS.find():
            out_str += f" 👥 {chat['title']} 🆔 `{chat['_id']}`\n"
        await message.edit(out_str, del_in=0)


@userge.on_cmd("convert_usermode", about={
    'header': "convert your bot into userbot to use user mode",
    'flags': {
        '-c': "provide code",
        '-sc': "provide two step authentication code"
    },
    'usage': "{tr}convert_usermode +915623461809\n"
             "{tr}convert_usermode -c=12345\n"
             "{tr}convert_usermode -sc=yourcode"
}, allow_channels=False)
async def convert_usermode(msg: Message):
    if bool(config.SESSION_STRING):
        return await msg.err("already using user mode")
    if msg.from_user.id not in config.OWNER_ID:
        return await msg.err("only owners can use this command")
    if msg.flags:
        if not hasattr(generate_session, "phone_number"):
            return await msg.err(
                "first give phone number, click on below button 👇")
        code = msg.flags.get('-c')
        two_step = msg.flags.get('-sc')
        if code:
            try:
                if hasattr(generate_session, "two_step_code"):
                    delattr(generate_session, "two_step_code")
                setattr(generate_session, "phone_code", code)
                if await generate_session():
                    session_string = await generate_session.client.export_session_string()
                    if config.HEROKU_APP:
                        await msg.reply(
                            "DONE! User Mode will be enabled after restart."
                        )
                        config.HEROKU_APP.config()["HU_STRING_SESSION"] = session_string
                    else:
                        await msg.reply(
                            "Add this in your environmental variables\n"
                            "Key = `HEROKU_STRING_SESION`\nValue 👇\n\n"
                            f"`{session_string}`"
                        )
            except SessionPasswordNeeded:
                await msg.reply(
                    "Your account have two-step verification code.\n"
                    "Please send your second factor authentication code "
                    "using\n`{tr}convert_usermode -sc=yourcode`"
                )
            except Exception as e:
                delattr(generate_session, "phone_code")
                await msg.reply(str(e))
        elif two_step:
            if not hasattr(generate_session, "phone_code"):
                return await msg.err("first verify OTP, click on below button 👇")
            try:
                setattr(generate_session, "two_step_code", two_step)
                if await generate_session():
                    session_string = await generate_session.client.export_session_string()
                    if config.HEROKU_APP:
                        await msg.reply(
                            "DONE! User Mode will be enabled after restart."
                        )
                        config.HEROKU_APP.config()["HU_STRING_SESSION"] = session_string
                    else:
                        await msg.reply(
                            "Add this in your environmental variables\n"
                            "Key = `HEROKU_STRING_SESION`\nValue 👇\n\n"
                            f"`{session_string}`"
                        )
            except Exception as e:
                delattr(generate_session, "two_step_code")
                await msg.reply(str(e))
        else:
            await msg.err("invalid flag or didn't provide argument with flag")
    else:
        if not msg.input_str:
            return await msg.err("phone number not found, click on below button 👇")

        if not hasattr(generate_session, "client"):
            client = Client(
                session_name=":memory:",
                api_id=config.API_ID,
                api_hash=config.API_HASH
            )
            try:
                await client.connect()
            except ConnectionError:
                await client.disconnect()
                await client.connect()
            setattr(generate_session, "client", client)
        for i in ("phone_number", "phone_code", "two_step"):
            if hasattr(generate_session, i):
                delattr(generate_session, i)
        setattr(generate_session, "phone_number", msg.input_str)
        try:
            if await generate_session():
                return await msg.reply(
                    "An otp is sent to your phone number\n\n"
                    "Send otp using `{tr}convert_usermode -c12345` command."
                )
            raise Exception("Unable to send OTP to this phone number.")
        except Exception as error:
            await msg.reply(str(error))


@userge.on_cmd("convert_botmode", about={
    'header': "convert your userbot to use bot mode",
    'usage': "{tr}convert_botmode bot_name | bot_username"}, allow_channels=False)
async def convert_botmode(msg: Message):
    if userge.has_bot:
        return await msg.err("using have bot mode")
    if not msg.input_str and '|' not in msg.input_str:
        return await msg.err("read .help convert_botmode")

    _, __ = msg.input_str.split('|', maxsplit=1)
    name = _.strip()
    username = __.strip()
    await msg.edit("`Converting to use bot mode`")
    try:
        async with userge.conversation('botfather') as conv:
            try:
                await conv.send_message('/start')
            except YouBlockedUser:
                await userge.unblock_user('botfather')
                await conv.send_message('/start')
            await conv.get_response()
            await conv.send_message('/newbot')
            await conv.get_response()
            await conv.send_message(name)
            await conv.get_response()
            await conv.send_message(username)
            response = await conv.get_response(mark_read=True)
            if 'Sorry' in response.text:
                await msg.err(response.text)
            else:
                await userge.promote_chat_member(config.LOG_CHANNEL_ID, username)
                token = extract_entities(response, ["code"])[0]
                if config.HEROKU_APP:
                    await msg.edit("DONE! Bot Mode will be enabled after restart.")
                    config.HEROKU_APP.config()["BOT_TOKEN"] = token
                else:
                    await msg.reply(
                        "Add this in your environmental variables\n"
                        "Key = `BOT_TOKEN`\n"
                        f"Value = `{token}`"
                    )
    except StopConversation:
        await msg.err("@botfather didn't respond in time.")


@userge.on_cmd("sleep (\\d+)", about={
    'header': "sleep userge :P",
    'usage': "{tr}sleep [timeout in seconds]"}, allow_channels=False)
async def sleep_(message: Message) -> None:
    """ sleep userge """
    seconds = int(message.matches[0].group(1))
    await message.edit(f"`sleeping {seconds} seconds...`")
    asyncio.get_event_loop().create_task(_slp_wrkr(seconds))


async def generate_session() -> bool:
    myFunc = generate_session
    if not hasattr(myFunc, "client"):
        return False

    client = myFunc.client
    if hasattr(myFunc, "two_step_code"):
        await client.check_password(myFunc.two_step_code)
    elif hasattr(myFunc, "code") and hasattr(myFunc, "phone_code"):
        await client.sign_in(
            myFunc.phone_number,
            myFunc.code.phone_code_hash,
            phone_code=myFunc.phone_code
        )
    elif hasattr(myFunc, "phone_number"):
        code = await client.send_code(myFunc.phone_number)
        setattr(generate_session, "code", code)
    else:
        return False
    return True


async def _slp_wrkr(seconds: int) -> None:
    await userge.stop()
    await asyncio.sleep(seconds)
    await userge.reload_plugins()
    await userge.start()


@userge.on_user_status()
async def _user_status(_, user: User) -> None:
    system.Dynamic.STATUS = user.status


@userge.add_task
async def _dyno_saver_worker() -> None:
    count = 0
    check_delay = 5
    offline_start_time = time.time()
    while system.Dynamic.RUN_DYNO_SAVER:
        if not count % check_delay and (
            system.Dynamic.STATUS is None or system.Dynamic.STATUS != "online"
        ):
            if system.Dynamic.STATUS is None:
                LOG.info("< bot client found ! >")
            else:
                LOG.info("< state changed to offline ! >")
                offline_start_time = time.time()
            warned = False
            while system.Dynamic.RUN_DYNO_SAVER and (
                    system.Dynamic.STATUS is None or system.Dynamic.STATUS != "online"):
                if not count % check_delay:
                    if system.Dynamic.STATUS is None:
                        offline_start_time = RawClient.LAST_OUTGOING_TIME
                    current_idle_time = int((time.time() - offline_start_time))
                    if current_idle_time < 5:
                        warned = False
                    if current_idle_time >= MAX_IDLE_TIME:
                        try:
                            config.HEROKU_APP.process_formation()['worker'].scale(0)
                        except Exception as h_e:  # pylint: disable=broad-except
                            LOG.error(f"heroku app error : {h_e}")
                            offline_start_time += 20
                            await asyncio.sleep(10)
                            continue
                        LOG.info("< successfully killed heroku dyno ! >")
                        await CHANNEL.log("heroku dyno killed !")
                        terminate()
                        return
                    prog = round(current_idle_time * 100 / MAX_IDLE_TIME, 2)
                    mins = int(MAX_IDLE_TIME / 60)
                    if prog >= 75 and not warned:
                        rem = int((100 - prog) * MAX_IDLE_TIME / 100)
                        await CHANNEL.log(
                            f"#WARNING\n\ndyno kill worker `{prog}%` completed !"
                            f"\n`{rem}`s remaining !")
                        warned = True
                    LOG.info(f"< dyno kill worker ... ({prog}%)({mins}) >")
                await asyncio.sleep(1)
                count += 1
            LOG.info("< state changed to online ! >")
        await asyncio.sleep(1)
        count += 1
    if count:
        LOG.info("< auto heroku dyno off worker has been stopped! >")