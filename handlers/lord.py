"""
Lord (Vassal) handlers — Orders, Elections, Defection, Execution
"""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.queries import (
    get_vassal_by_lord, get_vassal, get_vassal_members, update_vassal,
    get_kingdom, add_chronicle, get_user, cast_vote, get_votes,
    get_election_winner, get_all_kingdoms, update_kingdom,
    update_user, get_all_vassals, has_executed_today,
    create_loan, get_loans
)
from keyboards.kb import lord_main_kb, back_kb, vassals_select_kb, kingdoms_select_kb
from config import MIN_VASSAL_MEMBERS

router = Router()


class LordStates(StatesGroup):
    waiting_defect_kingdom = State()
    waiting_execute_confirm = State()
    waiting_dm_text = State()   # Oila a'zolariga shaxsiy xabar
    waiting_loan_amount = State()  # Temir bank qarz so'rash


def is_lord(db_user: dict) -> bool:
    return db_user.get("role") == "lord"


@router.callback_query(F.data == "lord_main")
async def cb_lord_main(call: CallbackQuery, db_user: dict):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return
    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        await call.answer("❌ Siz Lord emassiz!")
        return
    from database.queries import get_strongest_vassal_in_kingdom
    strongest = await get_strongest_vassal_in_kingdom(vassal["kingdom_id"])
    is_strongest = strongest and strongest["id"] == vassal["id"]
    extra = (
        "\n\n💪 <i>Siz qirollikdagi eng kuchli oilasiz! Da\'vogarlik qila olasiz.</i>"
        if is_strongest else ""
    )
    await call.message.edit_text(
        f"🛡️ <b>{vassal['name']} Lord Paneli</b>" + extra,
        reply_markup=lord_main_kb(show_claim=is_strongest)
    )


@router.callback_query(F.data == "lord_family_status")
async def cb_family_status(call: CallbackQuery, db_user: dict):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return
    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        await call.answer("❌ Vassal topilmadi!")
        return
    members = await get_vassal_members(vassal["id"])
    kingdom = await get_kingdom(vassal["kingdom_id"])

    text = f"🏠 <b>{vassal['name']} Oila Holati</b>\n\n"
    text += f"🏰 Qirollik: {kingdom['sigil']} {kingdom['name']}\n"
    text += f"💰 Oila oltini: {vassal['gold']}\n"
    text += f"⚔️ Qo'shin: {vassal['soldiers']}\n"
    text += f"👥 A'zolar ({len(members)}):\n"
    for m in members:
        role_mark = "👑" if m["telegram_id"] == vassal["lord_id"] else "⚔️"
        text += f"  {role_mark} {m['full_name']} | 💰 {m['gold']}\n"

    await call.message.edit_text(text, reply_markup=back_kb("lord_main"))


# ── Lord → Oila a'zolariga shaxsiy xabar ─────────────────────────────────────

@router.callback_query(F.data == "lord_send_dm")
async def cb_lord_send_dm_start(call: CallbackQuery, db_user: dict, state: FSMContext):
    """Lord xabar yuborishni boshlaydi"""
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        await call.answer("❌ Vassal topilmadi!")
        return

    members = await get_vassal_members(vassal["id"])
    non_lord = [m for m in members if m["telegram_id"] != call.from_user.id]

    if not non_lord:
        await call.message.edit_text(
            "❌ Oilangizda boshqa a'zolar yo'q!",
            reply_markup=back_kb("lord_main")
        )
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📢 Barcha a'zolarga",
        callback_data="lord_dm_target_all"
    ))
    for m in non_lord:
        name = m.get("full_name") or m.get("username") or str(m["telegram_id"])
        builder.row(InlineKeyboardButton(
            text=f"⚔️ {name}",
            callback_data=f"lord_dm_target_{m['telegram_id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="lord_main"))

    await state.set_state(LordStates.waiting_dm_text)
    await state.update_data(dm_target="__choosing__")
    await call.message.edit_text(
        "💬 <b>Shaxsiy xabar</b>\n\nKimga xabar yuborasiz?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("lord_dm_target_"))
async def cb_lord_dm_target(call: CallbackQuery, state: FSMContext, db_user: dict):
    """A'zo tanlandi — matn kutilmoqda"""
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    target = call.data.replace("lord_dm_target_", "")
    await state.update_data(dm_target=target)
    await state.set_state(LordStates.waiting_dm_text)

    vassal = await get_vassal_by_lord(call.from_user.id)
    if target == "all":
        who = "barcha oila a'zolaringizga"
    else:
        user = await get_user(int(target))
        name = user["full_name"] if user else target
        who = f"<b>{name}</b> ga"

    await call.message.edit_text(
        f"💬 <b>Shaxsiy xabar</b>\n\n{who} yuboriladigan xabarni yozing:",
        reply_markup=back_kb("lord_send_dm")
    )


@router.message(LordStates.waiting_dm_text)
async def msg_lord_dm_text(message: Message, state: FSMContext, bot: Bot, db_user: dict):
    """Matn keldi — yuborish"""
    if not is_lord(db_user):
        await state.clear()
        return

    data = await state.get_data()
    target = data.get("dm_target", "all")

    # Hali kimni tanlashda bo'lsa — tekst emas tugma kutilmoqda
    if target == "__choosing__":
        await message.answer("⚠️ Iltimos yuqoridagi tugmalardan birini tanlang.")
        return

    await state.clear()

    vassal = await get_vassal_by_lord(message.from_user.id)
    if not vassal:
        await message.answer("❌ Vassal topilmadi!", reply_markup=lord_main_kb())
        return

    header = (
        f"🛡️ <b>Lord — {vassal['name']} oilasidan shaxsiy xabar:</b>\n\n"
        f"{message.text}"
    )

    members = await get_vassal_members(vassal["id"])
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
        user = await get_user(int(target))
        name = user["full_name"] if user else target
        recipient_text = f"<b>{name}</b> ga"

    await message.answer(
        f"✅ Shaxsiy xabar {recipient_text} yuborildi!",
        reply_markup=lord_main_kb()
    )


# ── Order response ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("order_accept_"))
async def cb_order_accept(call: CallbackQuery, db_user: dict, bot: Bot):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return
    parts = call.data.replace("order_accept_", "").split("_")
    rtype, amount, vassal_id = parts[0], int(parts[1]), int(parts[2])

    vassal = await get_vassal(vassal_id)
    if not vassal:
        await call.answer("❌ Vassal topilmadi!")
        return

    # Transfer resources from vassal to kingdom
    kingdom = await get_kingdom(vassal["kingdom_id"])
    label = "oltin" if rtype == "gold" else "qo'shin"

    if rtype == "gold":
        if vassal["gold"] < amount:
            await call.message.edit_text(
                f"❌ Yetarli oltin yo'q! Sizda: {vassal['gold']}, Talab: {amount}",
                reply_markup=back_kb("lord_main")
            )
            return
        await update_vassal(vassal_id, gold=vassal["gold"] - amount)
        await update_kingdom(kingdom["id"], gold=kingdom["gold"] + amount)
    else:
        if vassal["soldiers"] < amount:
            await call.message.edit_text(
                f"❌ Yetarli qo'shin yo'q! Sizda: {vassal['soldiers']}, Talab: {amount}",
                reply_markup=back_kb("lord_main")
            )
            return
        await update_vassal(vassal_id, soldiers=vassal["soldiers"] - amount)
        await update_kingdom(kingdom["id"], soldiers=kingdom["soldiers"] + amount)

    # Notify king
    if kingdom["king_id"]:
        try:
            await bot.send_message(
                kingdom["king_id"],
                f"✅ <b>{vassal['name']}</b> Lordi {amount} {label} yubordi!"
            )
        except Exception:
            pass

    await call.message.edit_text(
        f"✅ {amount} {label} Qirolga yuborildi!", reply_markup=lord_main_kb()
    )
    await add_chronicle(
        "tribute", "Soliq to'landi",
        f"{vassal['name']} → {kingdom['name']}: {amount} {label}",
        actor_id=call.from_user.id
    )


@router.callback_query(F.data.startswith("order_reject_"))
async def cb_order_reject(call: CallbackQuery, db_user: dict, bot: Bot):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return
    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        return
    kingdom = await get_kingdom(vassal["kingdom_id"])

    # Warn king about refusal
    if kingdom["king_id"]:
        try:
            await bot.send_message(
                kingdom["king_id"],
                f"⚠️ <b>{vassal['name']}</b> Lordi sizning talabingizni RAD ETDI!\n"
                f"Jazo choralarini ko'rishingiz mumkin."
            )
        except Exception:
            pass

    await call.message.edit_text(
        "❌ Talab rad etildi. Qirolga xabar yuborildi.", reply_markup=lord_main_kb()
    )
    await add_chronicle(
        "defiance", "Talabga qarshi chiqish",
        f"{vassal['name']} Lordi Qirol talabini rad etdi",
        actor_id=call.from_user.id
    )


# ── Election ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "lord_election")
async def cb_election(call: CallbackQuery, db_user: dict):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return
    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        return
    members = await get_vassal_members(vassal["id"])
    if len(members) < MIN_VASSAL_MEMBERS:
        await call.message.edit_text(
            f"❌ Saylov uchun kamida {MIN_VASSAL_MEMBERS} a'zo kerak. "
            f"Hozir: {len(members)}",
            reply_markup=back_kb("lord_main")
        )
        return

    votes = await get_votes(vassal["id"])
    text = f"🗳️ <b>{vassal['name']} Saylov Natijalari</b>\n\n"
    for v in votes:
        user = await get_user(v["candidate_id"])
        name = user["full_name"] if user else str(v["candidate_id"])
        text += f"  👤 {name}: {v['votes']} ovoz\n"
    if not votes:
        text += "Hali ovoz berilmagan.\n"
    text += f"\nJami a'zolar: {len(members)}"

    await call.message.edit_text(text, reply_markup=back_kb("lord_main"))


# ── Defection (panoh so'rash) ─────────────────────────────────────────────────

@router.callback_query(F.data == "lord_defect")
async def cb_defect(call: CallbackQuery, db_user: dict, state: FSMContext):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return
    all_kingdoms = await get_all_kingdoms()
    vassal = await get_vassal_by_lord(call.from_user.id)
    others = [k for k in all_kingdoms if k["id"] != vassal["kingdom_id"]]
    await state.set_state(LordStates.waiting_defect_kingdom)
    await call.message.edit_text(
        "🚀 <b>Panoh so'rash</b>\n\nQaysi Qirollik panohiga o'tmoqchisiz?",
        reply_markup=kingdoms_select_kb(others, "defect_to")
    )


@router.callback_query(F.data.startswith("defect_to_"), LordStates.waiting_defect_kingdom)
async def cb_defect_to(call: CallbackQuery, state: FSMContext, db_user: dict, bot: Bot):
    target_id = int(call.data.split("_")[-1])
    vassal = await get_vassal_by_lord(call.from_user.id)
    target_kingdom = await get_kingdom(target_id)
    old_kingdom = await get_kingdom(vassal["kingdom_id"])

    # Notify old king
    if old_kingdom["king_id"]:
        try:
            await bot.send_message(
                old_kingdom["king_id"],
                f"⚠️ <b>XIYONAT!</b>\n\n"
                f"<b>{vassal['name']}</b> Lordi {target_kingdom['sigil']} "
                f"{target_kingdom['name']} qirolligiga o'tmoqchi!"
            )
        except Exception:
            pass

    # Notify target king
    if target_kingdom["king_id"]:
        try:
            await bot.send_message(
                target_kingdom["king_id"],
                f"📨 <b>{vassal['name']}</b> Lordi sizning qirolligingizga panoh so'ramoqda!\n"
                f"Qabul qilish uchun admin bilan bog'laning."
            )
        except Exception:
            pass

    await update_vassal(vassal["id"], kingdom_id=target_id)
    # Update all vassal members
    from database.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET kingdom_id=$1 WHERE vassal_id=$2",
            target_id, vassal["id"]
        )

    await state.clear()
    await call.message.edit_text(
        f"✅ Siz {target_kingdom['sigil']} <b>{target_kingdom['name']}</b> qirolligiga o'tdingiz!",
        reply_markup=lord_main_kb()
    )
    await add_chronicle(
        "defection", "Xiyonat!",
        f"{vassal['name']} {old_kingdom['name']}dan {target_kingdom['name']}ga o'tdi",
        actor_id=call.from_user.id
    )


# ═════════════════════════════════════════════════════════════════════════════
#  QATL TIZIMI — Lord o'z vassali a'zosini qatl etadi
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "lord_execute_member")
async def cb_execute_menu(call: CallbackQuery, db_user: dict):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    # Kunlik limit tekshiruvi
    if await has_executed_today(call.from_user.id):
        await call.message.edit_text(
            "⏳ <b>Siz bugun allaqachon qatl qildingiz!</b>\n\n"
            "Qatl huquqi har kuni yangilanadi.",
            reply_markup=back_kb("lord_main")
        )
        return

    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        await call.answer("❌ Vassal topilmadi!")
        return

    members = await get_vassal_members(vassal["id"])
    # O'z-o'zini qatl qilib bo'lmaydi
    targets = [m for m in members if m["telegram_id"] != call.from_user.id]

    if not targets:
        await call.message.edit_text(
            "👥 Qatl qilish mumkin bo'lgan a'zo yo'q.",
            reply_markup=back_kb("lord_main")
        )
        return

    builder = InlineKeyboardBuilder()
    for m in targets:
        name = m.get("full_name") or m.get("username") or str(m["telegram_id"])
        role_mark = "🛡️ " if m["role"] == "lord" else "⚔️ "
        builder.row(InlineKeyboardButton(
            text=f"{role_mark}{name}",
            callback_data=f"execute_confirm_{m['telegram_id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="lord_main"))

    await call.message.edit_text(
        f"⚔️ <b>Qatl — {vassal['name']} oilasi</b>\n\n"
        "⚠️ Qatl qilingan a'zo boshqa vassalga o'tkaziladi.\n"
        "❗ Kuniga faqat <b>1 marta</b> qatl qilish mumkin.\n\n"
        "Kimni qatl etasiz?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("execute_confirm_"))
async def cb_execute_confirm(call: CallbackQuery, db_user: dict, state: FSMContext):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    target_id = int(call.data.split("_")[-1])
    target = await get_user(target_id)
    if not target:
        await call.answer("❌ A'zo topilmadi!")
        return

    name = target.get("full_name") or target.get("username") or str(target_id)
    await state.update_data(execute_target_id=target_id, execute_target_name=name)
    await state.set_state(LordStates.waiting_execute_confirm)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚔️ Ha, qatl etaman", callback_data="execute_do"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="lord_execute_member")
    )
    await call.message.edit_text(
        f"⚔️ <b>Tasdiqlash</b>\n\n"
        f"<b>{name}</b> ni qatl etishni tasdiqlaysizmi?\n\n"
        f"A'zo boshqa bo'sh vassalga o'tkaziladi.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "execute_do", LordStates.waiting_execute_confirm)
async def cb_execute_do(call: CallbackQuery, state: FSMContext, db_user: dict, bot: Bot):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    data = await state.get_data()
    target_id = data.get("execute_target_id")
    target_name = data.get("execute_target_name", "Noma'lum")
    await state.clear()

    # Qayta tekshirish — kunlik limit (ikki marta bosmaslik uchun)
    if await has_executed_today(call.from_user.id):
        await call.message.edit_text(
            "⏳ Siz bugun allaqachon qatl qildingiz!",
            reply_markup=back_kb("lord_main")
        )
        return

    target = await get_user(target_id)
    if not target:
        await call.message.edit_text("❌ A'zo topilmadi!", reply_markup=back_kb("lord_main"))
        return

    lord_vassal = await get_vassal_by_lord(call.from_user.id)
    if not lord_vassal:
        await call.answer("❌ Vassal topilmadi!")
        return

    # A'zo haqiqatan shu vassaldami tekshirish
    if target.get("vassal_id") != lord_vassal["id"]:
        await call.message.edit_text(
            "❌ Bu a'zo sizning oilangizda emas!",
            reply_markup=back_kb("lord_main")
        )
        return

    # ── Boshqa bo'sh vassalni topish ─────────────────────────────────────────
    all_vassals = await get_all_vassals()
    from config import MAX_VASSAL_MEMBERS
    new_vassal = None
    for v in all_vassals:
        if v["id"] == lord_vassal["id"]:
            continue
        members_count = len(await get_vassal_members(v["id"]))
        if members_count < MAX_VASSAL_MEMBERS:
            new_vassal = v
            break

    if new_vassal:
        # Boshqa vassalga o'tkazish
        await update_user(target_id,
            vassal_id=new_vassal["id"],
            kingdom_id=new_vassal["kingdom_id"]
        )
        transfer_text = (
            f"🔀 {new_vassal['name']} oilasiga o'tkazildi."
        )
    else:
        # Bo'sh vassal topilmadi — kingdom ga bog'lab qo'yamiz (vassalsiz)
        await update_user(target_id, vassal_id=None)
        transfer_text = "⚠️ Bo'sh vassal topilmadi, a'zo vassalsiz qoldi."

    # Agar target Lord bo'lsa — undan lordlikni olib qo'yamiz
    if target.get("role") == "lord":
        v = await get_vassal_by_lord(target_id)
        if v:
            await update_vassal(v["id"], lord_id=None)
        await update_user(target_id, role="member")

    # Qatl haqida xronikaga yozish (actor_id saqlanadi — bu public qatl)
    lord_vassal_name = lord_vassal["name"]
    await add_chronicle(
        "execution",
        f"⚔️ Qatl — {lord_vassal_name}",
        f"Lord {call.from_user.full_name} — {target_name} ni qatl etdi.\n{transfer_text}",
        actor_id=call.from_user.id,
        target_id=target_id
    )

    # Nishonga xabar
    try:
        await bot.send_message(
            target_id,
            f"⚔️ <b>Siz qatl etildingiz!</b>\n\n"
            f"Lord tomonidan oiladan chiqarildingiz.\n"
            f"{transfer_text}"
        )
    except Exception:
        pass

    await call.message.edit_text(
        f"⚔️ <b>{target_name} qatl etildi.</b>\n\n"
        f"{transfer_text}",
        reply_markup=lord_main_kb()
    )


# ── Temir Bank — Qarz so'rash (Lord) ─────────────────────────────────────────

@router.callback_query(F.data == "lord_request_loan")
async def cb_lord_request_loan(call: CallbackQuery, db_user: dict, state: FSMContext):
    if not is_lord(db_user):
        await call.answer("🛡️ Faqat Lordlar uchun!", show_alert=True)
        return
    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        await call.answer("❌ Vassal topilmadi!", show_alert=True)
        return

    # Joriy faol qarzlarni tekshirish
    loans = await get_loans("vassal", vassal["id"])
    active = [l for l in loans if l["status"] == "active"]
    if active:
        total_due = sum(l["total_due"] - l["paid"] for l in active)
        await call.message.edit_text(
            f"🏦 <b>Temir Bank</b>\n\n"
            f"❌ Sizda hali to'lanmagan qarz bor!\n"
            f"💸 Umumiy qarzdorlik: <b>{total_due} oltin</b>\n\n"
            f"Avval joriy qarzingizni to'lang.",
            reply_markup=back_kb("lord_main")
        )
        return

    await state.set_state(LordStates.waiting_loan_amount)
    await state.update_data(vassal_id=vassal["id"], vassal_gold=vassal["gold"])
    await call.message.edit_text(
        f"🏦 <b>Temir Bank — Qarz so'rash</b>\n\n"
        f"💰 Oila xazinasi: <b>{vassal['gold']} oltin</b>\n\n"
        f"📋 Shartlar:\n"
        f"• Foiz: 20%\n"
        f"• To'lov muddati: 7 kun\n\n"
        f"Qancha oltin qarz olmoqchisiz?\n"
        f"<i>(Minimal: 50, Maksimal: 5000)</i>",
        reply_markup=back_kb("lord_main")
    )


@router.message(LordStates.waiting_loan_amount)
async def msg_loan_amount(message: Message, state: FSMContext, db_user: dict):
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Raqam kiriting!")
        return

    if amount < 50:
        await message.answer("❌ Minimal qarz miqdori: 50 oltin")
        return
    if amount > 5000:
        await message.answer("❌ Maksimal qarz miqdori: 5000 oltin")
        return

    data = await state.get_data()
    vassal_id = data.get("vassal_id")
    vassal = await get_vassal(vassal_id)
    if not vassal:
        await state.clear()
        await message.answer("❌ Vassal topilmadi!")
        return

    interest = amount * 20 // 100
    total_due = amount + interest
    from datetime import datetime, timedelta
    due_date = datetime.utcnow() + timedelta(days=7)

    await create_loan("vassal", vassal_id, amount, interest, total_due, due_date)
    await update_vassal(vassal_id, gold=vassal["gold"] + amount)
    await state.clear()

    await add_chronicle(
        "loan", "🏦 Qarz olindi",
        f"{vassal['name']} oilasi Temir Bankdan {amount} oltin qarz oldi. "
        f"Qaytarish: {total_due} oltin (7 kun ichida).",
        actor_id=message.from_user.id
    )
    from keyboards.kb import lord_main_kb
    await message.answer(
        f"🏦 <b>Temir Bank qarz berdi!</b>\n\n"
        f"💰 Qarz: <b>{amount} oltin</b>\n"
        f"📈 Foiz (20%): <b>{interest} oltin</b>\n"
        f"💸 Qaytarish: <b>{total_due} oltin</b>\n"
        f"📅 Muddati: 7 kun\n\n"
        f"Oltin oila xazinasiga qo'shildi!",
        reply_markup=lord_main_kb()
    )
