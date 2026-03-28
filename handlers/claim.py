"""
Da'vogarlik tizimi — Eng kuchli vassal qirollikka da'vo qiladi

Jarayon:
  1. Lord /claim yoki "👑 Da'vogarlik" tugmasini bosadi
  2. Bot uning vassali shu qirollikda eng kuchli ekanini tekshiradi
  3. Agar shart bajarilsa → da'vogarlik yaratiladi
  4. Shu qirollikdagi BARCHA boshqa Lordlarga xabar ketadi
  5. Har bir Lord: "✅ Qabul qilaman" yoki "⚔️ Urush qilaman"
  6. Barcha qabul qilsa → claimant Qirol bo'ladi (tinch o'tish)
  7. Kimdir urush desa → qo'shinlar bilan jang, g'olib aniqlashadi
  8. Barcha urushlar tugagach → eng ko'p g'alaba qozongan Qirol bo'ladi
"""

import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.queries import (
    get_vassal_by_lord, get_kingdom, get_kingdom_vassals,
    get_vassal_members, get_vassal, get_user, update_user,
    update_vassal, update_kingdom, add_chronicle,
    get_strongest_vassal_in_kingdom, create_claim, get_active_claim,
    get_claim, update_claim, add_claim_response, get_claim_responses,
    get_pending_claim_vassals, create_claim_war, resolve_claim_war,
    get_active_claim_wars, vassal_power
)
from keyboards.kb import lord_main_kb, back_kb

router = Router()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Yordamchi funksiya: barcha urushlar tugagach kimning qo'lida taxt?
# ─────────────────────────────────────────────────────────────────────────────

async def _check_claim_completion(claim_id: int, bot: Bot):
    """
    Da'vogarlik tugadimi? Agar:
    - Barcha vassallar javob bergan bo'lsa
    - Va faol urush qolmagan bo'lsa
    → G'olibni aniqlash va Qirol tayinlash
    """
    from database.db import get_pool
    from datetime import datetime

    claim = await get_claim(claim_id)
    if not claim or claim["status"] == "resolved":
        return

    kingdom_id = claim["kingdom_id"]
    claimant_vassal_id = claim["claimant_vassal_id"]
    vassals = await get_kingdom_vassals(kingdom_id)

    # Claimant o'zi javob bermaydi — boshqa vassallar soni
    other_vassals = [v for v in vassals if v["id"] != claimant_vassal_id]
    if not other_vassals:
        # Faqat o'zi — avtomatik g'alaba
        await _crown_claimant(claim_id, claimant_vassal_id, kingdom_id, bot)
        return

    responses = await get_claim_responses(claim_id)
    responded_ids = {r["vassal_id"] for r in responses}
    other_ids = {v["id"] for v in other_vassals}

    # Hali javob bermagan vassallar bor
    if not other_ids.issubset(responded_ids):
        return

    # Barcha javob berdi — faol urushlar bormi?
    active_wars = await get_active_claim_wars(claim_id)
    if active_wars:
        return

    # Hammasi tayyor — claimant Qirol bo'ladi
    await _crown_claimant(claim_id, claimant_vassal_id, kingdom_id, bot)


async def _crown_claimant(claim_id: int, claimant_vassal_id: int,
                          kingdom_id: int, bot: Bot):
    """Claimantni Qirol sifatida taxtga o'tkazish"""
    from database.db import get_pool
    from datetime import datetime

    claimant_vassal = await get_vassal(claimant_vassal_id)
    kingdom = await get_kingdom(kingdom_id)

    if not claimant_vassal or not kingdom:
        return

    # Eski Qirolni member ga tushirish
    if kingdom["king_id"]:
        old_king = await get_user(kingdom["king_id"])
        if old_king:
            await update_user(kingdom["king_id"], role="member")
            try:
                await bot.send_message(
                    kingdom["king_id"],
                    f"👑 Siz taxtdan tushirildingiz!\n\n"
                    f"{kingdom['sigil']} <b>{kingdom['name']}</b> qirolligiga yangi hukmdor "
                    f"<b>{claimant_vassal['name']}</b> oilasining Lordi bo'ldi."
                )
            except Exception:
                pass

    # Claimant Lordini Qirol qilish
    lord_id = claimant_vassal["lord_id"]
    if lord_id:
        await update_user(lord_id, role="king")
        await update_kingdom(kingdom_id, king_id=lord_id)

    # Da'vogarlikni yopish
    await update_claim(claim_id, status="resolved", resolved_at=datetime.utcnow())

    # Xronikaga yozish
    await add_chronicle(
        "coronation",
        f"Yangi Qirol! {kingdom['sigil']} {kingdom['name']}",
        f"{claimant_vassal['name']} oilasi da'vogarlik orqali "
        f"{kingdom['name']} qirolligini zabt etdi!",
        actor_id=lord_id,
        bot=bot
    )

    # Yangi Qirolga tabriklash
    if lord_id:
        try:
            await bot.send_message(
                lord_id,
                f"🎉 <b>Tabriklaymiz!</b>\n\n"
                f"Siz {kingdom['sigil']} <b>{kingdom['name']}</b> qirolligining\n"
                f"yangi <b>QIROLI</b> bo'ldingiz!\n\n"
                f"👑 Da'vogarlik g'alaba bilan yakunlandi.",
                reply_markup=back_kb("main_menu")
            )
        except Exception:
            pass

    # Butun qirollikka xabar
    from utils.helpers import broadcast_to_kingdom
    vassals_in_kingdom = await get_kingdom_vassals(kingdom_id)
    for v in vassals_in_kingdom:
        members = await get_vassal_members(v["id"])
        for m in members:
            if m["telegram_id"] == lord_id:
                continue
            try:
                await bot.send_message(
                    m["telegram_id"],
                    f"👑 <b>Yangi Qirol!</b>\n\n"
                    f"{kingdom['sigil']} {kingdom['name']} qirolligiga "
                    f"<b>{claimant_vassal['name']}</b> oilasining Lordi taxtga o'tirdi!"
                )
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  /claim buyrug'i va tugma
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("claim"))
async def cmd_claim(message: Message, db_user: dict, bot: Bot):
    await _handle_claim(message.from_user.id, db_user, bot,
                        reply_func=message.answer)


@router.callback_query(F.data == "lord_claim_throne")
async def cb_claim_throne(call: CallbackQuery, db_user: dict, bot: Bot):
    await _handle_claim(call.from_user.id, db_user, bot,
                        reply_func=call.message.edit_text,
                        call=call)


async def _handle_claim(user_id: int, db_user: dict, bot: Bot,
                        reply_func, call=None):
    # Faqat Lord
    if db_user.get("role") != "lord":
        msg = "🛡️ Faqat Lordlar da'vogarlik qila oladi!"
        if call:
            await call.answer(msg)
        else:
            await reply_func(msg)
        return

    vassal = await get_vassal_by_lord(user_id)
    if not vassal:
        await reply_func("❌ Vassal oilangiz topilmadi!", reply_markup=back_kb("lord_main"))
        return

    kingdom_id = vassal["kingdom_id"]
    kingdom = await get_kingdom(kingdom_id)

    # Faol da'vogarlik bormi?
    active = await get_active_claim(kingdom_id)
    if active:
        await reply_func(
            f"⚠️ <b>{kingdom['sigil']} {kingdom['name']}</b> qirolligida allaqachon "
            f"da'vogarlik jarayoni davom etmoqda!\n\n"
            "Avval joriy da'vogarlik yakunlanishi kerak.",
            reply_markup=back_kb("lord_main")
        )
        return

    # Eng kuchli vassalmi?
    strongest = await get_strongest_vassal_in_kingdom(kingdom_id)
    if not strongest or strongest["id"] != vassal["id"]:
        strongest_name = strongest["name"] if strongest else "?"
        strongest_soldiers = strongest["soldiers"] if strongest else 0
        await reply_func(
            f"❌ <b>Da'vogarlik qila olmaysiz!</b>\n\n"
            f"Hozirda {kingdom['sigil']} <b>{kingdom['name']}</b> qirolligidagi\n"
            f"eng kuchli oila: <b>{strongest_name}</b> ({strongest_soldiers} ⚔️)\n\n"
            f"Sizning oilangiz: <b>{vassal['name']}</b> ({vassal['soldiers']} ⚔️)\n\n"
            f"Da'vogarlik qilish uchun qirollikdagi <b>eng kuchli</b> oila bo'ling!",
            reply_markup=back_kb("lord_main")
        )
        return

    # Agar qirollik Qirolsiz bo'lsa → bevosita taxt egallash
    if not kingdom["king_id"]:
        claim = await create_claim(vassal["id"], kingdom_id)
        await update_claim(claim["id"], status="resolved")
        await update_user(user_id, role="king")
        await update_kingdom(kingdom_id, king_id=user_id)
        await add_chronicle(
            "coronation",
            f"Yangi Qirol! {kingdom['sigil']} {kingdom['name']}",
            f"{vassal['name']} oilasi bo'sh taxtga o'tirdi — {kingdom['name']}!",
            actor_id=user_id,
            bot=bot
        )
        await reply_func(
            f"👑 <b>Tabriklaymiz!</b>\n\n"
            f"Qirolsiz {kingdom['sigil']} <b>{kingdom['name']}</b> taxtiga\n"
            f"munosib hukmdor sifatida o'tirdingiz!\n\n"
            f"Siz endi bu qirollikning <b>QIROLISIZ</b>! 🎉",
            reply_markup=back_kb("main_menu")
        )
        return

    # Da'vogarlikni rasmiylashtirish
    claim = await create_claim(vassal["id"], kingdom_id)

    # Boshqa Lordlarga xabar yuborish
    other_vassals = [v for v in await get_kingdom_vassals(kingdom_id)
                     if v["id"] != vassal["id"]]
    notified = 0
    for ov in other_vassals:
        if ov["lord_id"]:
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(
                    text="✅ Qabul qilaman",
                    callback_data=f"claim_accept_{claim['id']}_{ov['id']}"
                ),
                InlineKeyboardButton(
                    text="⚔️ Urush qilaman",
                    callback_data=f"claim_war_{claim['id']}_{ov['id']}"
                )
            )
            try:
                await bot.send_message(
                    ov["lord_id"],
                    f"⚔️ <b>DA'VOGARLIK XABARI!</b>\n\n"
                    f"{kingdom['sigil']} <b>{kingdom['name']}</b> qirolligida\n"
                    f"<b>{vassal['name']}</b> oilasi taxtga da'vo qilmoqda!\n\n"
                    f"💪 Ularning kuchi: <b>{vassal['soldiers']} ⚔️</b>\n"
                    f"💪 Sizning oilangiz: <b>{ov['soldiers']} ⚔️</b>\n\n"
                    f"Qaror qiling:",
                    reply_markup=builder.as_markup()
                )
                notified += 1
            except Exception as e:
                logger.warning(f"Claim notify failed for lord {ov['lord_id']}: {e}")

    # Agar boshqa Lord yo'q bo'lsa — avtomatik g'alaba
    if not other_vassals or notified == 0:
        await _crown_claimant(claim["id"], vassal["id"], kingdom_id, bot)
        await reply_func(
            f"👑 <b>Tabriklaymiz!</b>\n\n"
            f"Raqibsiz {kingdom['sigil']} <b>{kingdom['name']}</b> taxtini zabt etdingiz!\n\n"
            f"Siz endi bu qirollikning <b>QIROLISIZ</b>! 🎉",
            reply_markup=back_kb("main_menu")
        )
        return

    await reply_func(
        f"📢 <b>Da'vogarlik e'lon qilindi!</b>\n\n"
        f"{kingdom['sigil']} <b>{kingdom['name']}</b> qirolligi uchun kurash boshlandi!\n\n"
        f"💪 Sizning kuchingiz: <b>{vassal['soldiers']} ⚔️</b>\n"
        f"📨 {notified} ta Lordga xabar yuborildi.\n\n"
        f"Ular javob berguncha kuting...",
        reply_markup=back_kb("lord_main")
    )
    await add_chronicle(
        "system",
        f"Da'vogarlik — {kingdom['name']}",
        f"{vassal['name']} oilasi {kingdom['name']} qirolligiga da'vogarlik e'lon qildi!",
        actor_id=user_id,
        bot=bot
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Vassallarning javobi — Qabul yoki Urush
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("claim_accept_"))
async def cb_claim_accept(call: CallbackQuery, db_user: dict, bot: Bot):
    """Vassal da'vogarlikni qabul qiladi — tinch o'tish"""
    if db_user.get("role") != "lord":
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    parts = call.data.split("_")
    # format: claim_accept_{claim_id}_{vassal_id}
    claim_id = int(parts[2])
    vassal_id = int(parts[3])

    claim = await get_claim(claim_id)
    if not claim or claim["status"] == "resolved":
        await call.answer("❌ Da'vogarlik allaqachon yakunlangan!")
        return

    # Javobni saqlash
    await add_claim_response(claim_id, vassal_id, "accepted")

    vassal = await get_vassal(vassal_id)
    claimant = await get_vassal(claim["claimant_vassal_id"])
    kingdom = await get_kingdom(claim["kingdom_id"])

    await call.message.edit_text(
        f"✅ <b>Qabul qildingiz</b>\n\n"
        f"<b>{claimant['name']}</b> oilasining {kingdom['sigil']} {kingdom['name']} "
        f"qirolligiga da'vosini tan oldingiz.\n\n"
        f"Natija e'lon qilinishini kuting..."
    )

    # Claimant Lordiga xabar
    if claimant["lord_id"]:
        try:
            await bot.send_message(
                claimant["lord_id"],
                f"✅ <b>{vassal['name']}</b> oilasi sizning da'voingizni qabul qildi!"
            )
        except Exception:
            pass

    # Barcha javob berganmi?
    await _check_claim_completion(claim_id, bot)


@router.callback_query(F.data.startswith("claim_war_"))
async def cb_claim_war(call: CallbackQuery, db_user: dict, bot: Bot):
    """Vassal da'vogarlikka urush bilan javob beradi"""
    if db_user.get("role") != "lord":
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    parts = call.data.split("_")
    # format: claim_war_{claim_id}_{vassal_id}
    claim_id = int(parts[2])
    vassal_id = int(parts[3])

    claim = await get_claim(claim_id)
    if not claim or claim["status"] == "resolved":
        await call.answer("❌ Da'vogarlik allaqachon yakunlangan!")
        return

    # Javobni saqlash
    await add_claim_response(claim_id, vassal_id, "war")
    await update_claim(claim_id, status="contested")

    challenger = await get_vassal(vassal_id)
    claimant = await get_vassal(claim["claimant_vassal_id"])
    kingdom = await get_kingdom(claim["kingdom_id"])

    # Kuchlarni hisoblash
    claimant_power = await vassal_power(claimant["id"])
    challenger_power = await vassal_power(challenger["id"])

    # Urushni yaratish
    claim_war = await create_claim_war(
        claim_id, claimant["id"], challenger["id"],
        claimant_power, challenger_power
    )

    # G'olibni aniqlash (hoziroq — deterministik jang)
    import random
    # Kuchga proporsional tasodifiy g'alaba
    total = claimant_power + challenger_power
    if total == 0:
        winner_id = random.choice([claimant["id"], challenger["id"]])
        w_power, l_power = 0, 0
    else:
        roll = random.randint(1, total)
        if roll <= claimant_power:
            winner_id = claimant["id"]
        else:
            winner_id = challenger["id"]

    winner = claimant if winner_id == claimant["id"] else challenger
    loser = challenger if winner_id == claimant["id"] else claimant

    # Jang natijalari — ikki tomondan yo'qotish (10-30%)
    loss_pct = random.randint(10, 30)
    claimant_loss = max(0, claimant["soldiers"] * loss_pct // 100)
    challenger_loss = max(0, challenger["soldiers"] * loss_pct // 100)

    from database.queries import update_vassal
    await update_vassal(claimant["id"],
                        soldiers=max(0, claimant["soldiers"] - claimant_loss))
    await update_vassal(challenger["id"],
                        soldiers=max(0, challenger["soldiers"] - challenger_loss))

    # Urushni yopish
    await resolve_claim_war(claim_war["id"], winner_id)

    result_text = (
        f"⚔️ <b>Da'vogarlik Urushi!</b>\n\n"
        f"🏠 {claimant['name']} vs {challenger['name']}\n\n"
        f"💪 {claimant['name']}: {claimant_power} kuch\n"
        f"💪 {challenger['name']}: {challenger_power} kuch\n\n"
        f"🏆 <b>G'olib: {winner['name']} oilasi!</b>\n\n"
        f"📉 Yo'qotishlar:\n"
        f"  {claimant['name']}: -{claimant_loss} ⚔️\n"
        f"  {challenger['name']}: -{challenger_loss} ⚔️"
    )

    # Ikki Lordga natijani yuborish
    for lord_id, role_vassal, outcome in [
        (claimant["lord_id"], claimant, "claimant"),
        (challenger["lord_id"], challenger, "challenger")
    ]:
        if not lord_id:
            continue
        try:
            if outcome == "claimant":
                personal = (
                    f"\n\n{'🎉 Siz g\'olib bo\'ldingiz!' if winner_id == claimant['id'] else '💀 Siz yutqazdingiz!'}"
                )
            else:
                personal = (
                    f"\n\n{'🎉 Siz g\'olib bo\'ldingiz!' if winner_id == challenger['id'] else '💀 Siz yutqazdingiz!'}"
                )
            await bot.send_message(lord_id, result_text + personal)
        except Exception:
            pass

    await call.message.edit_text(
        f"⚔️ <b>Urush boshlandi!</b>\n\n{result_text}"
    )

    await add_chronicle(
        "war",
        f"Da'vogarlik urushi — {kingdom['name']}",
        f"{claimant['name']} vs {challenger['name']} | G'olib: {winner['name']}",
        actor_id=call.from_user.id,
        bot=bot
    )

    # Claimant yutsa — da'vogarlik davom etadi; yutqazsa — da'vogarlik bekor
    if winner_id != claimant["id"]:
        # Claimant yutqazdi → da'vogarlik bekor
        await update_claim(claim_id, status="resolved")
        if claimant["lord_id"]:
            try:
                await bot.send_message(
                    claimant["lord_id"],
                    f"💀 <b>Da'vogarlik muvaffaqiyatsiz yakunlandi</b>\n\n"
                    f"{challenger['name']} oilasiga yutqazdingiz.\n"
                    f"Da'vogarlik bekor qilindi."
                )
            except Exception:
                pass
        return

    # Claimant yutdi — boshqa javob bermaganlar bormi?
    await _check_claim_completion(claim_id, bot)


# ─────────────────────────────────────────────────────────────────────────────
#  Da'vogarlik holati — Lord panelidan ko'rish
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "view_claim_status")
async def cb_view_claim_status(call: CallbackQuery, db_user: dict):
    if db_user.get("role") != "lord":
        await call.answer("🛡️ Faqat Lordlar uchun!")
        return

    vassal = await get_vassal_by_lord(call.from_user.id)
    if not vassal:
        await call.answer("❌ Vassal topilmadi!")
        return

    claim = await get_active_claim(vassal["kingdom_id"])
    kingdom = await get_kingdom(vassal["kingdom_id"])

    if not claim:
        # Da'vogarlik imkoniyatini tekshirish
        strongest = await get_strongest_vassal_in_kingdom(vassal["kingdom_id"])
        is_strongest = strongest and strongest["id"] == vassal["id"]

        text = f"⚔️ <b>Da'vogarlik — {kingdom['sigil']} {kingdom['name']}</b>\n\n"
        text += f"💪 Sizning oilangiz: <b>{vassal['name']}</b> ({vassal['soldiers']} ⚔️)\n"
        if strongest:
            text += f"🏆 Eng kuchli oila: <b>{strongest['name']}</b> ({strongest['soldiers']} ⚔️)\n\n"

        if is_strongest:
            text += "✅ <b>Siz eng kuchli oilasiz!</b>\nDa'vogarlik e'lon qila olasiz.\n"
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(
                text="👑 Taxtga da'vo qilish!",
                callback_data="lord_claim_throne"
            ))
            builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="lord_main"))
            await call.message.edit_text(text, reply_markup=builder.as_markup())
        else:
            text += "❌ Da'vogarlik qilish uchun qirollikdagi eng kuchli oila bo'lishingiz kerak."
            await call.message.edit_text(text, reply_markup=back_kb("lord_main"))
        return

    # Faol da'vogarlik bor
    claimant = await get_vassal(claim["claimant_vassal_id"])
    responses = await get_claim_responses(claim["id"])
    vassals = await get_kingdom_vassals(vassal["kingdom_id"])
    other_vassals = [v for v in vassals if v["id"] != claim["claimant_vassal_id"]]

    text = (
        f"⚔️ <b>Da'vogarlik jarayoni</b>\n"
        f"{kingdom['sigil']} {kingdom['name']}\n\n"
        f"👑 Da'vogar: <b>{claimant['name']}</b> ({claimant['soldiers']} ⚔️)\n"
        f"📊 Holat: <b>{claim['status']}</b>\n\n"
        f"📋 Javoblar:\n"
    )

    resp_map = {r["vassal_id"]: r["response"] for r in responses}
    for ov in other_vassals:
        resp = resp_map.get(ov["id"])
        if resp == "accepted":
            icon = "✅"
        elif resp == "war":
            icon = "⚔️"
        else:
            icon = "⏳"
        text += f"  {icon} {ov['name']}\n"

    await call.message.edit_text(text, reply_markup=back_kb("lord_main"))
