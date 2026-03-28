"""
Member handlers — Daily Farm, Voting, Chronicles, Iron Bank, Assassination
"""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timedelta, timezone

from database.queries import (
    get_user, update_user, get_vassal, get_vassal_members, cast_vote,
    get_chronicles, add_chronicle, buy_artifact, get_artifacts,
    get_kingdom, update_vassal, get_election_winner, update_kingdom,
    get_price, get_all_prices, get_kingdom_ruler_vassal
)
from keyboards.kb import member_main_kb, market_kb, back_kb, candidates_kb
from config import DAILY_FARM_GOLD, GOLD_TO_SOLDIER_RATE, MIN_VASSAL_MEMBERS

router = Router()


class MemberStates(StatesGroup):
    waiting_dm_text = State()   # Oila a'zolariga shaxsiy xabar


# ── Member → Vassal oilasiga shaxsiy xabar ───────────────────────────────────

@router.callback_query(F.data == "member_send_dm")
async def cb_member_send_dm_start(call: CallbackQuery, db_user: dict, state: FSMContext):
    """Member xabar yuborishni boshlaydi"""
    user = db_user
    if not user.get("vassal_id"):
        await call.message.edit_text(
            "❌ Siz hech qanday vassal oilaga tegishli emassiz.",
            reply_markup=back_kb()
        )
        return

    vassal = await get_vassal(user["vassal_id"])
    members = await get_vassal_members(user["vassal_id"])
    others = [m for m in members if m["telegram_id"] != call.from_user.id]

    if not others:
        await call.message.edit_text(
            "❌ Oilangizda boshqa a'zolar yo'q!",
            reply_markup=back_kb()
        )
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📢 Barcha oila a'zolariga",
        callback_data="member_dm_target_all"
    ))
    for m in others:
        name = m.get("full_name") or m.get("username") or str(m["telegram_id"])
        role_icon = "🛡️" if m["role"] == "lord" else "⚔️"
        builder.row(InlineKeyboardButton(
            text=f"{role_icon} {name}",
            callback_data=f"member_dm_target_{m['telegram_id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="main_menu"))

    await state.set_state(MemberStates.waiting_dm_text)
    await state.update_data(dm_target="__choosing__", vassal_id=user["vassal_id"])
    await call.message.edit_text(
        f"💬 <b>Shaxsiy xabar — {vassal['name']} oilasi</b>\n\nKimga xabar yuborasiz?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("member_dm_target_"))
async def cb_member_dm_target(call: CallbackQuery, state: FSMContext):
    """A'zo tanlandi — matn kutilmoqda"""
    target = call.data.replace("member_dm_target_", "")
    await state.update_data(dm_target=target)
    await state.set_state(MemberStates.waiting_dm_text)

    if target == "all":
        who = "barcha oila a'zolaringizga"
    else:
        user = await get_user(int(target))
        name = user["full_name"] if user else target
        who = f"<b>{name}</b> ga"

    await call.message.edit_text(
        f"💬 <b>Shaxsiy xabar</b>\n\n{who} yuboriladigan xabarni yozing:",
        reply_markup=back_kb()
    )


@router.message(MemberStates.waiting_dm_text)
async def msg_member_dm_text(message: Message, state: FSMContext, bot: Bot, db_user: dict):
    """Matn keldi — yuborish"""
    data = await state.get_data()
    target = data.get("dm_target", "all")
    vassal_id = data.get("vassal_id") or db_user.get("vassal_id")

    if target == "__choosing__":
        await message.answer("⚠️ Iltimos yuqoridagi tugmalardan birini tanlang.")
        return

    await state.clear()

    if not vassal_id:
        await message.answer("❌ Vassal topilmadi!", reply_markup=member_main_kb())
        return

    vassal = await get_vassal(vassal_id)
    user = db_user
    sender_name = user.get("full_name") or user.get("username") or "A'zo"

    header = (
        f"💬 <b>{sender_name}</b> ({vassal['name'] if vassal else 'Oila'}) shaxsiy xabar:\n\n"
        f"{message.text}"
    )

    members = await get_vassal_members(vassal_id)
    sent = 0

    if target == "all":
        for m in members:
            if m["telegram_id"] == message.from_user.id:
                continue
            try:
                await bot.send_message(m["telegram_id"], header)
                sent += 1
            except Exception:
                pass
        recipient_text = f"barcha {sent} ta a'zoga"
    else:
        try:
            await bot.send_message(int(target), header)
            sent = 1
        except Exception:
            pass
        u = await get_user(int(target))
        name = u["full_name"] if u else target
        recipient_text = f"<b>{name}</b> ga"

    await message.answer(
        f"✅ Shaxsiy xabar {recipient_text} yuborildi!",
        reply_markup=member_main_kb()
    )


# ── Daily Farm ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "daily_farm")
async def cb_daily_farm(call: CallbackQuery, db_user: dict):
    user = db_user
    # Har doim timezone-naive UTC ishlatiladi (DB bilan mos)
    now = datetime.utcnow()
    last = user.get("last_farm")

    if last:
        if isinstance(last, str):
            last = datetime.fromisoformat(last)
        # Agar timezone-aware kelsa — naive ga aylantir
        if hasattr(last, "tzinfo") and last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        next_farm = last + timedelta(days=1)
        if now < next_farm:
            remaining = next_farm - now
            hours = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            await call.message.edit_text(
                f"⏳ Erta farm qilgansiz!\n\n"
                f"⏱️ Keyingi farm: <b>{hours}s {mins}d</b> dan so'ng",
                reply_markup=back_kb()
            )
            return

    # Oltin faqat vassal xazinasiga yig'iladi
    await update_user(call.from_user.id, last_farm=now)

    vassal_gold = 0
    if user.get("vassal_id"):
        vassal = await get_vassal(user["vassal_id"])
        if vassal:
            vassal_gold = vassal["gold"] + DAILY_FARM_GOLD
            await update_vassal(user["vassal_id"], gold=vassal_gold)

    await call.message.edit_text(
        f"⛏️ <b>Farm qilindi!</b>\n\n"
        f"💰 +{DAILY_FARM_GOLD} tanga vassal xazinasiga qo'shildi\n"
        f"🏦 Vassal xazinasi: {vassal_gold} oltin\n\n"
        f"Ertaga qaytib keling!",
        reply_markup=back_kb()
    )


# ── Chronicles ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "view_chronicles")
async def cb_chronicles(call: CallbackQuery):
    records = await get_chronicles(15)
    if not records:
        await call.message.edit_text(
            "📜 <b>Xronika bo'sh</b>\n\nHali hech qanday voqea sodir bo'lmagan.",
            reply_markup=back_kb()
        )
        return

    event_emojis = {
        "war": "⚔️", "alliance": "🤝", "coronation": "👑",
        "join": "🎉", "decree": "📜", "tribute": "💰",
        "punishment": "💀", "defection": "🚀", "defiance": "⚠️",
        "gm_event": "🔮", "assassination": "🗡️", "election": "🗳️",
        "system": "⚙️", "vassal_created": "🛡️", "resource_demand": "📦"
    }

    text = "📜 <b>O'YIN XRONIKASI</b>\n\n"
    for r in records:
        emoji = event_emojis.get(r["event_type"], "📌")
        dt = r["created_at"]
        if hasattr(dt, "strftime"):
            date_str = dt.strftime("%d.%m %H:%M")
        else:
            date_str = str(dt)[:16]
        text += f"{emoji} <b>{r['title']}</b> — <i>{date_str}</i>\n"
        if r["description"]:
            text += f"   {r['description'][:80]}\n"
        text += "\n"

    await call.message.edit_text(text, reply_markup=back_kb())


# ── Voting ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "vote_lord")
async def cb_vote_lord(call: CallbackQuery, db_user: dict):
    user = db_user
    if not user.get("vassal_id"):
        await call.message.edit_text(
            "❌ Siz hech qanday vassal oilaga tegishli emassiz.",
            reply_markup=back_kb()
        )
        return
    vassal = await get_vassal(user["vassal_id"])
    members = await get_vassal_members(user["vassal_id"])

    if len(members) < MIN_VASSAL_MEMBERS:
        await call.message.edit_text(
            f"❌ Saylov uchun kamida {MIN_VASSAL_MEMBERS} a'zo kerak.\n"
            f"Hozir: {len(members)}",
            reply_markup=back_kb()
        )
        return

    # Show candidates (all members except current user)
    candidates = [m for m in members if m["telegram_id"] != call.from_user.id]
    await call.message.edit_text(
        f"🗳️ <b>{vassal['name']} oilasi Lord saylovi</b>\n\n"
        f"Kim Lord bo'lishini xohlaysiz?",
        reply_markup=candidates_kb(candidates, vassal["id"])
    )


@router.callback_query(F.data.startswith("vote_"))
async def cb_cast_vote(call: CallbackQuery, db_user: dict, bot: Bot):
    parts = call.data.split("_")
    if len(parts) < 3:
        return
    vassal_id = int(parts[1])
    candidate_id = int(parts[2])

    success = await cast_vote(vassal_id, candidate_id, call.from_user.id)
    if not success:
        await call.answer("❌ Siz allaqachon ovoz bergansiz!", show_alert=True)
        return

    # Check if we have a winner (majority)
    vassal = await get_vassal(vassal_id)
    members = await get_vassal_members(vassal_id)
    from database.queries import get_votes
    votes = await get_votes(vassal_id)

    winner_id = None
    majority = len(members) // 2 + 1
    if votes and votes[0]["votes"] >= majority:
        winner_id = votes[0]["candidate_id"]

    if winner_id and not vassal["lord_id"]:
        winner = await get_user(winner_id)
        await update_vassal(vassal_id, lord_id=winner_id)
        await update_user(winner_id, role="lord")

        # Notify all vassal members
        for m in members:
            try:
                await bot.send_message(
                    m["telegram_id"],
                    f"🎉 <b>Lord saylandi!</b>\n\n"
                    f"<b>{winner['full_name']}</b> {vassal['name']} oilasining yangi Lordi!"
                )
            except Exception:
                pass
        await add_chronicle(
            "election", "Lord saylandi!",
            f"{winner['full_name']} — {vassal['name']} Lordi",
            actor_id=winner_id
        )
        await call.message.edit_text(
            f"🗳️ Ovozingiz qabul qilindi!\n\n"
            f"🎉 <b>{winner['full_name']}</b> yangi Lord etib saylandi!",
            reply_markup=member_main_kb()
        )
    else:
        vote_count = votes[0]["votes"] if votes else 1
        await call.message.edit_text(
            f"✅ Ovoz berildi! Jami: {vote_count}/{len(members)}",
            reply_markup=back_kb()
        )


# ── Iron Bank (Market) ────────────────────────────────────────────────────────

@router.callback_query(F.data == "market_main")
async def cb_market(call: CallbackQuery, db_user: dict):
    user = db_user
    artifacts = []
    if user.get("vassal_id"):
        arts = await get_artifacts("vassal", user["vassal_id"])
        artifacts = [a["artifact"] for a in arts]

    text = (
        f"🏦 <b>Iron Bank — Brinni'dan</b>\n\n"
        f"💰 Sizning oltiningiz: {user['gold']}\n\n"
        f"📦 Sizning artefaktlaringiz: {', '.join(artifacts) if artifacts else 'Yo\'q'}\n\n"
        f"💡 Xarid qilish uchun tanlang:"
    )
    await call.message.edit_text(text, reply_markup=market_kb())


async def _buy(call: CallbackQuery, db_user: dict, artifact: str, price: int, tier: str = None):
    user = db_user
    role = user.get("role", "member")

    # Member xarid qila olmaydi
    if role == "member":
        await call.answer("❌ Xarid qilish faqat Lord va Qirollar uchun!", show_alert=True)
        return

    # Lord — vassal xazinasidan
    if role == "lord":
        vassal = await get_vassal(user["vassal_id"]) if user.get("vassal_id") else None
        if not vassal or vassal["gold"] < price:
            have = vassal["gold"] if vassal else 0
            await call.answer(f"❌ Yetarli oltin yo'q! Kerak: {price}, Xazina: {have}", show_alert=True)
            return
        await update_vassal(vassal["id"], gold=vassal["gold"] - price)
        await buy_artifact("vassal", vassal["id"], artifact, tier)

    # Qirol — hukmdor vassal xazinasidan
    elif role == "king":
        kingdom = await get_kingdom(user["kingdom_id"]) if user.get("kingdom_id") else None
        ruler = await get_kingdom_ruler_vassal(kingdom["id"]) if kingdom else None
        if not ruler or ruler["gold"] < price:
            have = ruler["gold"] if ruler else 0
            await call.answer(f"❌ Yetarli oltin yo'q! Kerak: {price}, Xazina: {have}", show_alert=True)
            return
        await update_vassal(ruler["id"], gold=ruler["gold"] - price)
        await buy_artifact("vassal", ruler["id"], artifact, tier)

    await call.message.edit_text(
        f"✅ <b>{artifact}</b> sotib olindi!\n💰 Sarflandi: {price} oltin",
        reply_markup=back_kb("market_main")
    )
    await add_chronicle("purchase", f"{artifact} sotib olindi", f"Narx: {price} oltin", actor_id=call.from_user.id)


@router.callback_query(F.data == "buy_valyrian")
async def cb_buy_valyrian(call: CallbackQuery, db_user: dict):
    await _buy(call, db_user, "🗡️ Valeriya Po'lati", await get_price("valyrian"))


@router.callback_query(F.data == "buy_wildfire")
async def cb_buy_wildfire(call: CallbackQuery, db_user: dict):
    await _buy(call, db_user, "🔥 Yovvoyi Olov", await get_price("wildfire"))


@router.callback_query(F.data == "buy_dragon_a")
async def cb_buy_dragon_a(call: CallbackQuery, db_user: dict):
    await _buy(call, db_user, "🐉 Ajdar", await get_price("dragon_a"), "A")


@router.callback_query(F.data == "buy_dragon_b")
async def cb_buy_dragon_b(call: CallbackQuery, db_user: dict):
    await _buy(call, db_user, "🐉 Ajdar", await get_price("dragon_b"), "B")


@router.callback_query(F.data == "buy_dragon_c")
async def cb_buy_dragon_c(call: CallbackQuery, db_user: dict):
    await _buy(call, db_user, "🐉 Ajdar", await get_price("dragon_c"), "C")


@router.callback_query(F.data == "buy_scorpion")
async def cb_buy_scorpion(call: CallbackQuery, db_user: dict):
    price = await get_price("scorpion")
    await _buy(call, db_user, "🦂 Chayon", price)


# ── Gold → Soldier exchange ───────────────────────────────────────────────────

@router.callback_query(F.data == "exchange_gold")
async def cb_exchange_gold(call: CallbackQuery, db_user: dict):
    user = db_user
    if user["gold"] < 100:
        await call.answer("❌ Ayirboshlash uchun kamida 100 oltin kerak!", show_alert=True)
        return
    await update_user(call.from_user.id, gold=user["gold"] - 100)
    if user.get("vassal_id"):
        vassal = await get_vassal(user["vassal_id"])
        if vassal:
            await update_vassal(user["vassal_id"], soldiers=vassal["soldiers"] + 100)
    await call.message.edit_text(
        "⚔️ <b>Ayirboshlash muvaffaqiyatli!</b>\n\n100 💰 oltin → 100 ⚔️ qo'shin",
        reply_markup=back_kb("market_main")
    )
