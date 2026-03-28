"""
Database query helpers
"""
from database.db import get_pool
from config import (
    MAX_KINGDOM_MEMBERS, MIN_VASSAL_MEMBERS, MAX_VASSAL_MEMBERS,
    KINGDOMS_COUNT, KINGDOM_NAMES, KINGDOM_SIGILS
)
import logging

logger = logging.getLogger(__name__)


# ── User queries ──────────────────────────────────────────────────────────────

async def get_user(telegram_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1", telegram_id
        )


async def create_user(telegram_id: int, username: str, full_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO users (telegram_id, username, full_name)
               VALUES ($1, $2, $3) RETURNING *""",
            telegram_id, username, full_name
        )


async def update_user(telegram_id: int, **kwargs):
    pool = await get_pool()
    cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(kwargs))
    vals = list(kwargs.values())
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE users SET {cols} WHERE telegram_id = $1",
            telegram_id, *vals
        )


# ── Queue / placement system ──────────────────────────────────────────────────

async def assign_user_to_slot(telegram_id: int) -> dict:
    """
    Queue algoritmi:
    Foydalanuvchilar to'g'ridan-to'g'ri vassal oilalarga round-robin usulida joylashtiriladi.
      - Har bir vassalga navbat bilan 1 ta qo'shiladi.
      - Hamma vassal bittadan to'lsa, yana birinchisidan boshlanadi.
      - Maksimum MAX_VASSAL_MEMBERS ta.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        qs = await conn.fetchrow("SELECT * FROM queue_state WHERE id = 1")
        phase = qs["phase"]

        # ── VASSAL ROUND-ROBIN ─────────────────────────────────────────────────
        vassals = await conn.fetch("SELECT * FROM vassals ORDER BY id")
        if not vassals:
            return {"phase": phase, "error": "No vassals defined"}

        n = len(vassals)
        idx = qs["current_vassal_index"] % n

        for _ in range(n):
            vassal = vassals[idx % n]
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE vassal_id = $1", vassal["id"]
            )
            if count < MAX_VASSAL_MEMBERS:
                await conn.execute(
                    """UPDATE users SET kingdom_id=$1, vassal_id=$2
                       WHERE telegram_id=$3""",
                    vassal["kingdom_id"], vassal["id"], telegram_id
                )
                next_idx = (idx + 1) % n
                # Phase 2 → 3: barcha vassal kamida 1 kishiga ega bo'lsa
                new_phase = phase
                if phase == 2:
                    all_have_one = True
                    for v in vassals:
                        c = await conn.fetchval(
                            "SELECT COUNT(*) FROM users WHERE vassal_id = $1", v["id"]
                        )
                        if c < 1:
                            all_have_one = False
                            break
                    if all_have_one:
                        new_phase = 3

                await conn.execute(
                    "UPDATE queue_state SET phase=$1, current_vassal_index=$2 WHERE id=1",
                    new_phase, next_idx
                )
                return {"phase": new_phase, "vassal": vassal["name"]}
            idx = (idx + 1) % n

        return {"phase": phase, "error": "All vassal slots full"}


# ── Kingdom queries ───────────────────────────────────────────────────────────

async def get_all_kingdoms():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM kingdoms ORDER BY id")


async def get_kingdom(kingdom_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM kingdoms WHERE id = $1", kingdom_id
        )


async def get_kingdom_by_king(king_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM kingdoms WHERE king_id = $1", king_id
        )


async def create_kingdom(name: str):
    pool = await get_pool()
    sigil = KINGDOM_SIGILS.get(name, "⚔️")
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO kingdoms (name, sigil) VALUES ($1, $2)
               ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING *""",
            name, sigil
        )


async def update_kingdom(kingdom_id: int, **kwargs):
    pool = await get_pool()
    cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(kwargs))
    vals = list(kwargs.values())
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE kingdoms SET {cols} WHERE id = $1", kingdom_id, *vals
        )


async def get_kingdom_members(kingdom_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM users WHERE kingdom_id = $1", kingdom_id
        )


# ── Vassal queries ────────────────────────────────────────────────────────────

async def get_all_vassals():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM vassals ORDER BY id")


async def get_vassal(vassal_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM vassals WHERE id = $1", vassal_id
        )


async def get_vassal_by_lord(lord_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM vassals WHERE lord_id = $1", lord_id
        )


async def get_kingdom_vassals(kingdom_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM vassals WHERE kingdom_id = $1", kingdom_id
        )


async def get_vassal_members(vassal_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM users WHERE vassal_id = $1", vassal_id
        )


async def create_vassal(name: str, kingdom_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO vassals (name, kingdom_id) VALUES ($1, $2) RETURNING *""",
            name, kingdom_id
        )


async def update_vassal(vassal_id: int, **kwargs):
    pool = await get_pool()
    cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(kwargs))
    vals = list(kwargs.values())
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE vassals SET {cols} WHERE id = $1", vassal_id, *vals
        )


# ── Chronicle queries ─────────────────────────────────────────────────────────

async def add_chronicle(event_type: str, title: str, description: str,
                        actor_id: int = None, target_id: int = None,
                        bot=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO chronicles (event_type, title, description, actor_id, target_id)
               VALUES ($1, $2, $3, $4, $5)""",
            event_type, title, description, actor_id, target_id
        )

    # Kanalga post yuborish
    if bot is not None:
        await _post_to_channel(bot, event_type, title, description)


async def _post_to_channel(bot, event_type: str, title: str, description: str):
    """Voqeani kanal ga post qilish"""
    from config import CHRONICLE_CHANNEL_ID

    event_emojis = {
        "war":                "⚔️",
        "war_end":            "🏆",
        "assassination_success": "💀",
        "assassination_attempt": "🗡️",
        "coronation":         "👑",
        "election":           "🗳️",
        "alliance":           "🤝",
        "loan":               "🏦",
        "purchase":           "💰",
        "gm_event":           "🔮",
        "defection":          "🚀",
        "punishment":         "⚔️",
        "vassal_created":     "🛡️",
        "tribute":            "💸",
        "system":             "⚙️",
    }

    # Kanalga bormaydigan voqealar
    skip_types = {"join", "purchase"}
    if event_type in skip_types:
        return

    emoji = event_emojis.get(event_type, "📜")
    text = (
        f"{emoji} <b>{title}</b>\n\n"
        f"{description}\n\n"
        f"<i>📜 Taxtlar O\'yini Xronikasi</i>"
    )
    try:
        await bot.send_message(CHRONICLE_CHANNEL_ID, text)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Chronicle channel error: {e}")


async def get_chronicles(limit: int = 20):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM chronicles ORDER BY created_at DESC LIMIT $1", limit
        )


# ── Election queries ──────────────────────────────────────────────────────────

async def cast_vote(vassal_id: int, candidate_id: int, voter_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """INSERT INTO elections (vassal_id, candidate_id, voter_id)
                   VALUES ($1, $2, $3)""",
                vassal_id, candidate_id, voter_id
            )
            return True
        except Exception:
            return False  # already voted


async def get_votes(vassal_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT candidate_id, COUNT(*) as votes
               FROM elections WHERE vassal_id = $1
               GROUP BY candidate_id ORDER BY votes DESC""",
            vassal_id
        )


async def get_election_winner(vassal_id: int) -> int | None:
    rows = await get_votes(vassal_id)
    if rows:
        return rows[0]["candidate_id"]
    return None


# ── Diplomacy queries ─────────────────────────────────────────────────────────

async def create_diplomacy(from_kingdom: int, to_kingdom: int, offer_type: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO diplomacy (from_kingdom_id, to_kingdom_id, offer_type)
               VALUES ($1, $2, $3) RETURNING *""",
            from_kingdom, to_kingdom, offer_type
        )


async def update_diplomacy(diplomacy_id: int, status: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE diplomacy SET status=$1 WHERE id=$2", status, diplomacy_id
        )


async def get_pending_diplomacy(to_kingdom_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT d.*, k.name as from_name, k.sigil as from_sigil
               FROM diplomacy d JOIN kingdoms k ON d.from_kingdom_id = k.id
               WHERE d.to_kingdom_id = $1 AND d.status = 'pending'""",
            to_kingdom_id
        )


# ── Artifact queries ──────────────────────────────────────────────────────────

async def buy_artifact(owner_type: str, owner_id: int, artifact: str, tier: str = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO artifacts (owner_type, owner_id, artifact, tier)
               VALUES ($1, $2, $3, $4)""",
            owner_type, owner_id, artifact, tier
        )


async def get_artifacts(owner_type: str, owner_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM artifacts WHERE owner_type=$1 AND owner_id=$2",
            owner_type, owner_id
        )


async def delete_artifact(artifact_id: int):
    """Artifact bazadan o'chirish (bir martalik chayon/ajdar uchun)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM artifacts WHERE id=$1", artifact_id)


async def get_kingdom_ruler_vassal(kingdom_id: int):
    """Qirollikning hukmdor vassalini qaytaradi (hukmdor_vassal_id orqali)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        kingdom = await conn.fetchrow("SELECT * FROM kingdoms WHERE id=$1", kingdom_id)
        if not kingdom or not kingdom.get("hukmdor_vassal_id"):
            return None
        return await conn.fetchrow(
            "SELECT * FROM vassals WHERE id=$1", kingdom["hukmdor_vassal_id"]
        )


async def set_hukmdor_vassal(kingdom_id: int, vassal_id: int):
    """Hukmdor vassalni belgilash"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE kingdoms SET hukmdor_vassal_id=$1 WHERE id=$2",
            vassal_id, kingdom_id
        )


async def create_hukmdor_claim(claimant_vassal_id: int, kingdom_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO hukmdor_claims (claimant_vassal_id, kingdom_id, status)
               VALUES ($1, $2, 'pending') RETURNING *""",
            claimant_vassal_id, kingdom_id
        )


async def get_active_hukmdor_claim(kingdom_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT * FROM hukmdor_claims
               WHERE kingdom_id=$1 AND status='pending'
               ORDER BY created_at DESC LIMIT 1""",
            kingdom_id
        )


async def get_hukmdor_claim(claim_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM hukmdor_claims WHERE id=$1", claim_id
        )


async def add_hukmdor_claim_response(claim_id: int, vassal_id: int, response: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO hukmdor_claim_responses (claim_id, vassal_id, response)
               VALUES ($1, $2, $3)
               ON CONFLICT (claim_id, vassal_id) DO UPDATE SET response=$3""",
            claim_id, vassal_id, response
        )


async def get_hukmdor_claim_responses(claim_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM hukmdor_claim_responses WHERE claim_id=$1", claim_id
        )


async def close_hukmdor_claim(claim_id: int, status: str = "completed"):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE hukmdor_claims SET status=$1 WHERE id=$2",
            status, claim_id
        )


async def get_vassal_lord_user(vassal_id: int):
    """Vassalning lord foydalanuvchisini topish (vassals.lord_id orqali)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        vassal = await conn.fetchrow("SELECT * FROM vassals WHERE id=$1", vassal_id)
        if not vassal or not vassal.get("lord_id"):
            return None
        return await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1", vassal["lord_id"]
        )


# ── Assassination queries ─────────────────────────────────────────────────────

async def add_assassination_hit(target_id: int, attacker_id: int, attacker_role: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO assassination_hits (target_id, attacker_id, attacker_role)
               VALUES ($1, $2, $3)""",
            target_id, attacker_id, attacker_role
        )


async def count_assassination_hits(target_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM assassination_hits WHERE target_id = $1",
            target_id
        )


async def count_lord_hits(target_id: int) -> int:
    """Count hits from Lords only (for king death threshold)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """SELECT COUNT(*) FROM assassination_hits
               WHERE target_id = $1 AND attacker_role = 'lord'""",
            target_id
        )


async def count_king_hits(target_id: int) -> int:
    """Count hits from Kings only (for Targaryen death threshold)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """SELECT COUNT(*) FROM assassination_hits
               WHERE target_id = $1 AND attacker_role = 'king'""",
            target_id
        )


async def get_assassination_attackers(target_id: int):
    """Get list of attackers for a target"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT attacker_id, attacker_role, COUNT(*) as hits
               FROM assassination_hits WHERE target_id = $1
               GROUP BY attacker_id, attacker_role
               ORDER BY hits DESC""",
            target_id
        )


async def reset_assassination_hits(target_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM assassination_hits WHERE target_id = $1",
            target_id
        )


async def has_assassinated_today(attacker_id: int, target_id: int) -> bool:
    """Bugun shu nishonga suiqasd qilganmi tekshirish (UTC+5)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM assassination_hits
            WHERE attacker_id = $1
              AND target_id   = $2
              AND created_at >= (NOW() AT TIME ZONE 'Asia/Tashkent')::date
              AND created_at <  (NOW() AT TIME ZONE 'Asia/Tashkent')::date + INTERVAL '1 day'
            LIMIT 1
            """,
            attacker_id, target_id
        )
        return row is not None


async def has_executed_today(lord_id: int) -> bool:
    """Lord bugun qatl qilganmi tekshirish (UTC+5)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM chronicles
            WHERE actor_id   = $1
              AND event_type = 'execution'
              AND created_at >= (NOW() AT TIME ZONE 'Asia/Tashkent')::date
              AND created_at <  (NOW() AT TIME ZONE 'Asia/Tashkent')::date + INTERVAL '1 day'
            LIMIT 1
            """,
            lord_id
        )
        return row is not None


async def get_all_lords():
    """Get all users with lord role"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT u.*, v.name as vassal_name, k.name as kingdom_name, k.sigil
               FROM users u
               LEFT JOIN vassals v ON u.vassal_id = v.id
               LEFT JOIN kingdoms k ON u.kingdom_id = k.id
               WHERE u.role = 'lord'
               ORDER BY k.name, v.name"""
        )


async def get_all_kings():
    """Get all users with king role"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT u.*, k.name as kingdom_name, k.sigil
               FROM users u
               LEFT JOIN kingdoms k ON u.kingdom_id = k.id
               WHERE u.role = 'king'
               ORDER BY k.name"""
        )


# ── Market prices queries ─────────────────────────────────────────────────────

async def get_all_prices():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM market_prices ORDER BY item")
        return {r["item"]: {"price": r["price"], "label": r["label"]} for r in rows}


async def get_price(item: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT price FROM market_prices WHERE item=$1", item)
        return row["price"] if row else 0


async def update_price(item: str, price: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE market_prices SET price=$1 WHERE item=$2",
            price, item
        )


# ── Loan queries ──────────────────────────────────────────────────────────────

async def create_loan(borrower_type: str, borrower_id: int,
                      amount: int, interest: int = 0, due_date=None):
    pool = await get_pool()
    total_due = amount + (amount * interest // 100)
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO loans
               (borrower_type, borrower_id, amount, interest, total_due, due_date)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
            borrower_type, borrower_id, amount, interest, total_due, due_date
        )


async def get_loans(borrower_type: str, borrower_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT * FROM loans
               WHERE borrower_type=$1 AND borrower_id=$2
               ORDER BY created_at DESC""",
            borrower_type, borrower_id
        )


async def get_all_active_loans():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM loans WHERE status='active' ORDER BY created_at"
        )


async def repay_loan(loan_id: int, amount: int):
    """Qarzni to'lash — qisman yoki to'liq"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        loan = await conn.fetchrow("SELECT * FROM loans WHERE id=$1", loan_id)
        if not loan:
            return None
        new_paid = loan["paid"] + amount
        status = "paid" if new_paid >= loan["total_due"] else "active"
        return await conn.fetchrow(
            """UPDATE loans SET paid=$1, status=$2 WHERE id=$3 RETURNING *""",
            new_paid, status, loan_id
        )


async def get_loan(loan_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM loans WHERE id=$1", loan_id)


# ── War queries ───────────────────────────────────────────────────────────────

async def create_war(attacker_id: int, defender_id: int, starts_at) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO wars (attacker_id, defender_id, status, starts_at)
               VALUES ($1, $2, 'pending', $3) RETURNING *""",
            attacker_id, defender_id, starts_at
        )


async def get_war(war_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM wars WHERE id=$1", war_id)


async def get_active_war(kingdom_id: int):
    """Qirollikning joriy urushi"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT * FROM wars
               WHERE (attacker_id=$1 OR defender_id=$1)
               AND status NOT IN ('finished')
               ORDER BY starts_at DESC LIMIT 1""",
            kingdom_id
        )


async def update_war(war_id: int, **kwargs):
    pool = await get_pool()
    cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(kwargs))
    vals = list(kwargs.values())
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE wars SET {cols} WHERE id=$1", war_id, *vals
        )


async def get_pending_wars():
    """Boshlanishi kerak bo'lgan urushlar"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        from datetime import datetime
        return await conn.fetch(
            """SELECT * FROM wars
               WHERE status='pending' AND starts_at <= $1""",
            datetime.utcnow()
        )


async def add_war_support(war_id: int, from_type: str, from_id: int,
                          to_kingdom: int, gold: int = 0,
                          soldiers: int = 0, scorpions: int = 0):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO war_support
               (war_id, from_type, from_id, to_kingdom, gold, soldiers, scorpions)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            war_id, from_type, from_id, to_kingdom, gold, soldiers, scorpions
        )


async def get_war_support(war_id: int, to_kingdom: int):
    """Biror qirollikka kelgan jami yordam"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT
               COALESCE(SUM(gold),0) as total_gold,
               COALESCE(SUM(soldiers),0) as total_soldiers,
               COALESCE(SUM(scorpions),0) as total_scorpions
               FROM war_support
               WHERE war_id=$1 AND to_kingdom=$2""",
            war_id, to_kingdom
        )


async def create_tribute(war_id: int, from_kingdom: int, to_kingdom: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO tributes (war_id, from_kingdom, to_kingdom)
               VALUES ($1, $2, $3)""",
            war_id, from_kingdom, to_kingdom
        )


async def get_active_tributes():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM tributes WHERE active=TRUE"
        )


# ── Game settings ─────────────────────────────────────────────────────────────

async def get_game_active() -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM game_settings WHERE key='game_active'"
        )
        return row["value"] == "true" if row else True


async def set_game_active(active: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO game_settings (key, value) VALUES ('game_active', $1)
               ON CONFLICT (key) DO UPDATE SET value=$1""",
            "true" if active else "false"
        )


# ── Da'vogarlik (Claim) queries ───────────────────────────────────────────────

async def get_strongest_vassal_in_kingdom(kingdom_id: int):
    """Qirollikdagi eng kuchli vassalni topish (soldiers + artifact bonusi)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        vassals = await conn.fetch(
            "SELECT * FROM vassals WHERE kingdom_id=$1", kingdom_id
        )
        if not vassals:
            return None
        best = None
        best_power = -1
        for v in vassals:
            power = v["soldiers"] or 0
            arts = await conn.fetch(
                "SELECT artifact, tier FROM artifacts WHERE owner_type='vassal' AND owner_id=$1",
                v["id"]
            )
            for a in arts:
                if a["artifact"] == "🐉 Ajdar":
                    if a["tier"] == "A": power += 100
                    elif a["tier"] == "B": power += 50
                    elif a["tier"] == "C": power += 25
            if power > best_power:
                best_power = power
                best = dict(v)
                best["power"] = power
        return best


async def create_claim(claimant_vassal_id: int, kingdom_id: int):
    """Yangi da'vogarlik yaratish"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO claims (claimant_vassal_id, kingdom_id, status)
               VALUES ($1, $2, 'pending') RETURNING *""",
            claimant_vassal_id, kingdom_id
        )


async def get_active_claim(kingdom_id: int):
    """Qirollikdagi faol da'vogarlikni olish"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT * FROM claims
               WHERE kingdom_id = $1
               AND status IN ('pending', 'contested')
               ORDER BY created_at DESC LIMIT 1""",
            kingdom_id
        )


async def get_claim(claim_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM claims WHERE id=$1", claim_id)


async def update_claim(claim_id: int, **kwargs):
    pool = await get_pool()
    cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(kwargs))
    vals = list(kwargs.values())
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE claims SET {cols} WHERE id=$1", claim_id, *vals
        )


async def add_claim_response(claim_id: int, vassal_id: int, response: str):
    """Vassalning da'vogarlikka javobini qo'shish"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return await conn.fetchrow(
                """INSERT INTO claim_responses (claim_id, vassal_id, response)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (claim_id, vassal_id) DO UPDATE SET response=$3
                   RETURNING *""",
                claim_id, vassal_id, response
            )
        except Exception:
            return None


async def get_claim_responses(claim_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM claim_responses WHERE claim_id=$1", claim_id
        )


async def get_pending_claim_vassals(claim_id: int, kingdom_id: int, claimant_vassal_id: int):
    """Hali javob bermagan vassallar (claimant o'zi hisoblanmaydi)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT v.* FROM vassals v
               WHERE v.kingdom_id = $1
               AND v.id != $2
               AND v.id NOT IN (
                   SELECT vassal_id FROM claim_responses WHERE claim_id=$3
               )""",
            kingdom_id, claimant_vassal_id, claim_id
        )


async def create_claim_war(claim_id: int, claimant_vassal_id: int,
                           challenger_vassal_id: int,
                           claimant_power: int, challenger_power: int):
    """Da'vogarlik urushini yaratish"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO claim_wars
               (claim_id, claimant_vassal_id, challenger_vassal_id,
                claimant_power, challenger_power, status)
               VALUES ($1, $2, $3, $4, $5, 'active') RETURNING *""",
            claim_id, claimant_vassal_id, challenger_vassal_id,
            claimant_power, challenger_power
        )


async def resolve_claim_war(claim_war_id: int, winner_vassal_id: int):
    """Da'vogarlik urushini yakunlash"""
    from datetime import datetime
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """UPDATE claim_wars
               SET winner_vassal_id=$2, status='resolved', ended_at=$3
               WHERE id=$1 RETURNING *""",
            claim_war_id, winner_vassal_id, datetime.utcnow()
        )


async def get_active_claim_wars(claim_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM claim_wars WHERE claim_id=$1 AND status='active'",
            claim_id
        )


async def vassal_power(vassal_id: int) -> int:
    """Vassal kuchini hisoblash (soldiers + dragon bonusi)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchrow("SELECT soldiers FROM vassals WHERE id=$1", vassal_id)
        if not v:
            return 0
        power = v["soldiers"] or 0
        # Artifactlar bonusi
        artifacts = await conn.fetch(
            "SELECT artifact, tier FROM artifacts WHERE owner_type='vassal' AND owner_id=$1",
            vassal_id
        )
        for a in artifacts:
            if a["artifact"] == "dragon":
                if a["tier"] == "A":
                    power += 100
                elif a["tier"] == "B":
                    power += 50
                elif a["tier"] == "C":
                    power += 25
        return power


# ── O'yin bazasini tozalash ───────────────────────────────────────────────────

async def reset_all_users_for_new_game() -> list:
    """
    Barcha foydalanuvchilarni yangi o'yin uchun reset qiladi.

    - Foydalanuvchilar (admindan tashqari) kingdom_id, vassal_id = NULL,
      role = 'member', gold = 0, last_farm = NULL ga qaytariladi.
    - Qirolliklar: king_id = NULL, resurslar = 0.
    - Vassallar: lord_id = NULL, resurslar = 0.
    - queue_state: phase=1, current_vassal_index=0.
    - O'yin tarixi jadvallari tozalanadi (wars, diplomacy, artifacts va h.k.).

    Qaytaradi: xabar yuborish kerak bo'lgan telegram_id lar ro'yxati.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Barcha foydalanuvchilar ID larini oldindan saqlab qo'yamiz
        rows = await conn.fetch(
            "SELECT telegram_id FROM users WHERE role != 'admin'"
        )
        telegram_ids = [r["telegram_id"] for r in rows]

        # Foydalanuvchilarni reset (adminlar saqlanadi)
        await conn.execute("""
            UPDATE users
            SET kingdom_id = NULL,
                vassal_id  = NULL,
                role       = 'member',
                gold       = 0,
                last_farm  = NULL
            WHERE role != 'admin'
        """)

        # Qirolliklar: taxtlar bo'shatiladi, resurslar nolga tushadi
        await conn.execute(
            "UPDATE kingdoms SET king_id=NULL, hukmdor_vassal_id=NULL, gold=0, soldiers=0, dragons=0"
        )

        # Vassallar: lordlar ozod qilinadi, resurslar nolga tushadi
        await conn.execute(
            "UPDATE vassals SET lord_id=NULL, gold=0, soldiers=0"
        )

        # Navbat holati qayta boshidan
        await conn.execute(
            "UPDATE queue_state SET phase=2, current_vassal_index=0 WHERE id=1"
        )

        # O'yin tarixi jadvallarini tozalash
        await conn.execute("DELETE FROM hukmdor_claim_responses")
        await conn.execute("DELETE FROM hukmdor_claims")
        await conn.execute("DELETE FROM war_support")
        await conn.execute("DELETE FROM tributes")
        await conn.execute("DELETE FROM wars")
        await conn.execute("DELETE FROM diplomacy")
        await conn.execute("DELETE FROM elections")
        await conn.execute("DELETE FROM artifacts")
        await conn.execute("DELETE FROM assassination_hits")
        await conn.execute("DELETE FROM claim_wars")
        await conn.execute("DELETE FROM claim_responses")
        await conn.execute("DELETE FROM claims")
        await conn.execute("DELETE FROM loans")
        await conn.execute("DELETE FROM chronicles")

    return telegram_ids
