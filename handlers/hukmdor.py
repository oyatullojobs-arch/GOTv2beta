"""
Hukmdor vassal da'vosi tizimi.
Lord da'vo qiladi → boshqa lordlar qabul/rad etadi → jang → g'olib hukmdor bo'ladi.
"""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.queries import (
    get_vassal_by_lord, get_kingdom_vassals, get_kingdom_ruler_vassal,
    set_hukmdor_vassal, create_hukmdor_claim, get_active_hukmdor_claim,
    add_hukmdor_claim_response, get_hukmdor_claim_responses, get_hukmdor_claim,
    close_hukmdor_claim, vassal_power, get_vassal, add_chronicle, get_kingdom
)
from keyboards.kb import back_kb, lord_main_kb

router = Router()


@router.callback_query(F.data == "lord_claim_hukmdor")
async def cb_lord_claim_hukmdor(call: CallbackQuery, db_user: dict, bot: Bot):
    if db_user.get("role") != "lord":
        await call.answer("🛡️ Faqat Lord uchun!")
        return

    my_vassal = await get_vassal_by_lord(call.from_user.id)
    if not my_vassal:
        await call.answer("❌ Vassal oilangiz topilmadi!", show_alert=True)
        return

    kingdom_id = my_vassal["kingdom_id"]

    # Mavjud faol da'vo bormi?
    existing = await get_active_hukmdor_claim(kingdom_id)
    if existing:
        claimant = await get_vassal(existing["claimant_vassal_id"])
        await call.message.edit_text(
            f"⚠️ Bu hududda allaqachon faol da'vo mavjud!\n\n"
            f"🛡️ Da'vogar: <b>{claimant['name'] if claimant else '?'}</b>\n\n"
            f"Avval u yakunlansin.",
            reply_markup=back_kb("lord_main")
        )
        return

    # Siz allaqachon hukmdormisiz?
    current_hukmdor = await get_kingdom_ruler_vassal(kingdom_id)
    if current_hukmdor and current_hukmdor["id"] == my_vassal["id"]:
        await call.answer("👑 Siz allaqachon hukmdor vassalsiz!", show_alert=True)
        return

    # Hudud vassallarini topamiz (o'zidan tashqari, lordi bo'lganlari)
    all_vassals = await get_kingdom_vassals(kingdom_id)
    other_vassals = [
        v for v in all_vassals
        if v["id"] != my_vassal["id"] and v.get("lord_id")
    ]

    # Da'vo yaratamiz
    claim = await create_hukmdor_claim(my_vassal["id"], kingdom_id)
    kingdom = await get_kingdom(kingdom_id)
    my_power = await vassal_power(my_vassal["id"])

    # Agar boshqa vassal yo'q → avtomatik hukmdor
    if not other_vassals:
        await set_hukmdor_vassal(kingdom_id, my_vassal["id"])
        await close_hukmdor_claim(claim["id"])
        await call.message.edit_text(
            f"👑 <b>Siz hukmdor vassalsiz!</b>\n\n"
            f"🏰 Hudud: {kingdom['sigil']} <b>{kingdom['name']}</b>\n\n"
            f"Hududda boshqa lord bo'lmagani uchun da'vo avtomatik qabul qilindi.",
            reply_markup=lord_main_kb()
        )
        await add_chronicle(
            "hukmdor", "👑 Yangi hukmdor vassal",
            f"{my_vassal['name']} → {kingdom['name']} hukmdori (avtomatik)",
            actor_id=call.from_user.id
        )
        return

    # Boshqa lordlarga xabar yuborish
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="✅ Qabul qilaman",
            callback_data=f"hukmdor_accept_{claim['id']}_{my_vassal['id']}"
        ),
        InlineKeyboardButton(
            text="⚔️ Rad etaman — jangga!",
            callback_data=f"hukmdor_reject_{claim['id']}_{my_vassal['id']}"
        )
    )

    notified = 0
    for v in other_vassals:
        try:
            await bot.send_message(
                v["lord_id"],
                f"👑 <b>HUKMDOR DA'VOSI!</b>\n\n"
                f"🏰 Hudud: {kingdom['sigil']} <b>{kingdom['name']}</b>\n\n"
                f"🛡️ <b>{my_vassal['name']}</b> vassal oilasi bu hududning\n"
                f"hukmdori bo'lmoqchi!\n\n"
                f"⚔️ Da'vogar kuchi: <b>{my_power}</b>\n\n"
                f"Qabul qilasizmi yoki jangga kirasizmi?",
                reply_markup=kb.as_markup()
            )
            notified += 1
        except Exception:
            pass

    # Da'vogarga "Jangni boshlash" tugmasi (kutmasdan boshlash uchun)
    force_kb = InlineKeyboardBuilder()
    force_kb.row(InlineKeyboardButton(
        text="⚔️ Jangni boshlash (hozir)",
        callback_data=f"hukmdor_force_fight_{claim['id']}"
    ))
    force_kb.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="lord_main"))

    await call.message.edit_text(
        f"👑 <b>Da'vo yuborildi!</b>\n\n"
        f"🏰 Hudud: {kingdom['sigil']} <b>{kingdom['name']}</b>\n"
        f"👥 Xabardor qilingan lordlar: <b>{notified}</b>\n"
        f"⚔️ Sizning kuchingiz: <b>{my_power}</b>\n\n"
        f"Barcha lordlar javob bergandan so'ng yoki\n"
        f"'Jangni boshlash' tugmasi orqali natija aniqlanadi.",
        reply_markup=force_kb.as_markup()
    )


@router.callback_query(F.data.startswith("hukmdor_accept_"))
async def cb_hukmdor_accept(call: CallbackQuery, db_user: dict, bot: Bot):
    if db_user.get("role") != "lord":
        await call.answer("🛡️ Faqat Lord uchun!")
        return

    parts = call.data.split("_")
    claim_id = int(parts[2])

    my_vassal = await get_vassal_by_lord(call.from_user.id)
    if not my_vassal:
        await call.answer("❌ Vassal topilmadi!")
        return

    claim = await get_hukmdor_claim(claim_id)
    if not claim or claim["status"] != "pending":
        await call.answer("❌ Bu da'vo allaqachon yakunlangan!", show_alert=True)
        return

    await add_hukmdor_claim_response(claim_id, my_vassal["id"], "accept")
    await call.message.edit_text(
        "✅ <b>Qabul qildingiz.</b>\n\nSiz da'vogarning hukmdorligini tan oldingiz."
    )

    await _check_and_process_claim(claim, bot)


@router.callback_query(F.data.startswith("hukmdor_reject_"))
async def cb_hukmdor_reject(call: CallbackQuery, db_user: dict, bot: Bot):
    if db_user.get("role") != "lord":
        await call.answer("🛡️ Faqat Lord uchun!")
        return

    parts = call.data.split("_")
    claim_id = int(parts[2])

    my_vassal = await get_vassal_by_lord(call.from_user.id)
    if not my_vassal:
        await call.answer("❌ Vassal topilmadi!")
        return

    claim = await get_hukmdor_claim(claim_id)
    if not claim or claim["status"] != "pending":
        await call.answer("❌ Bu da'vo allaqachon yakunlangan!", show_alert=True)
        return

    my_power = await vassal_power(my_vassal["id"])
    await add_hukmdor_claim_response(claim_id, my_vassal["id"], "reject")
    await call.message.edit_text(
        f"⚔️ <b>Rad etdingiz!</b>\n\n"
        f"Siz da'vogarga qarshi jangga kirasiz.\n"
        f"Sizning kuchingiz: <b>{my_power}</b>"
    )

    await _check_and_process_claim(claim, bot)


@router.callback_query(F.data.startswith("hukmdor_force_fight_"))
async def cb_hukmdor_force_fight(call: CallbackQuery, db_user: dict, bot: Bot):
    if db_user.get("role") != "lord":
        await call.answer("🛡️ Faqat Lord uchun!")
        return

    claim_id = int(call.data.split("_")[-1])
    claim = await get_hukmdor_claim(claim_id)
    if not claim or claim["status"] != "pending":
        await call.answer("❌ Bu da'vo allaqachon yakunlangan!", show_alert=True)
        return

    claimant_vassal = await get_vassal(claim["claimant_vassal_id"])
    if not claimant_vassal or claimant_vassal.get("lord_id") != call.from_user.id:
        await call.answer("❌ Faqat da'vogar jangni boshlashi mumkin!", show_alert=True)
        return

    await call.message.edit_text("⚔️ <b>Jang boshlanmoqda...</b>")
    await _process_hukmdor_fight(claim, bot)


async def _check_and_process_claim(claim, bot: Bot):
    """Barcha lordlar javob berganda avtomatik jangni hisoblash"""
    kingdom_id = claim["kingdom_id"]
    all_vassals = await get_kingdom_vassals(kingdom_id)
    other_vassals = [
        v for v in all_vassals
        if v["id"] != claim["claimant_vassal_id"] and v.get("lord_id")
    ]

    responses = await get_hukmdor_claim_responses(claim["id"])
    responded_ids = {r["vassal_id"] for r in responses}

    all_responded = all(v["id"] in responded_ids for v in other_vassals)
    if not all_responded:
        return

    await _process_hukmdor_fight(claim, bot)


async def _process_hukmdor_fight(claim, bot: Bot):
    """Jang natijasini hisoblash va hukmdorni belgilash"""
    kingdom_id = claim["kingdom_id"]
    claimant_vassal_id = claim["claimant_vassal_id"]

    responses = await get_hukmdor_claim_responses(claim["id"])
    rejector_ids = {r["vassal_id"] for r in responses if r["response"] == "reject"}

    # Barcha ishtirokchilar: da'vogar + rad etganlar
    participants = [claimant_vassal_id] + list(rejector_ids)

    powers = {}
    for vid in participants:
        powers[vid] = await vassal_power(vid)

    # G'olibni aniqlash (eng yuqori kuch)
    winner_id = max(powers, key=lambda x: powers[x])
    winner_vassal = await get_vassal(winner_id)
    claimant_vassal = await get_vassal(claimant_vassal_id)
    kingdom = await get_kingdom(kingdom_id)

    # Hukmdorni belgilash
    await set_hukmdor_vassal(kingdom_id, winner_id)
    await close_hukmdor_claim(claim["id"])

    # Barcha kingdom lordlarini xabardor qilish
    all_vassals = await get_kingdom_vassals(kingdom_id)
    lord_ids = [v["lord_id"] for v in all_vassals if v.get("lord_id")]

    if rejector_ids:
        # Jang bo'lgan — batafsil natija
        battle_lines = []
        for vid, pw in sorted(powers.items(), key=lambda x: x[1], reverse=True):
            v = await get_vassal(vid)
            if not v:
                continue
            marker = "🏆" if vid == winner_id else "💀"
            role_tag = " (da'vogar)" if vid == claimant_vassal_id else " (raqib)"
            battle_lines.append(f"{marker} <b>{v['name']}</b>{role_tag}: {pw} kuch")

        result_text = (
            f"⚔️ <b>HUKMDOR JANGI YAKUNLANDI!</b>\n\n"
            f"🏰 Hudud: {kingdom['sigil']} <b>{kingdom['name']}</b>\n\n"
            f"📊 <b>Jang natijalari:</b>\n"
            + "\n".join(battle_lines) +
            f"\n\n👑 <b>{winner_vassal['name']}</b> — yangi hukmdor vassal!"
        )
    else:
        # Hech kim rad etmadi
        result_text = (
            f"👑 <b>HUKMDOR BELGILANDI!</b>\n\n"
            f"🏰 Hudud: {kingdom['sigil']} <b>{kingdom['name']}</b>\n\n"
            f"Barcha lordlar qabul qildi.\n\n"
            f"👑 <b>{winner_vassal['name']}</b> — yangi hukmdor vassal!"
        )

    for lord_id in lord_ids:
        try:
            await bot.send_message(lord_id, result_text)
        except Exception:
            pass

    await add_chronicle(
        "hukmdor", "👑 Yangi hukmdor vassal",
        f"{winner_vassal['name']} → {kingdom['name']} hukmdori | "
        f"kuch: {powers.get(winner_id, 0)}",
        actor_id=winner_vassal.get("lord_id")
    )
