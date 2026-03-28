"""
Database layer — PostgreSQL with asyncpg
"""
import asyncpg
import logging
from config import DATABASE_URL

logger = logging.getLogger(__name__)
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ── Kingdoms ──────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kingdoms (
                id                  SERIAL PRIMARY KEY,
                name                VARCHAR(100) UNIQUE NOT NULL,
                sigil               VARCHAR(10)  DEFAULT '⚔️',
                king_id             BIGINT       UNIQUE,
                hukmdor_vassal_id   INTEGER,
                gold                INTEGER      DEFAULT 0,
                soldiers            INTEGER      DEFAULT 0,
                dragons             INTEGER      DEFAULT 0,
                created_at          TIMESTAMP    DEFAULT NOW()
            )
        """)
        # Eski baza uchun ustun qo'shish
        await conn.execute("""
            ALTER TABLE kingdoms
            ADD COLUMN IF NOT EXISTS hukmdor_vassal_id INTEGER
        """)

        # ── Vassal families ───────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vassals (
                id          SERIAL PRIMARY KEY,
                name        VARCHAR(100) NOT NULL,
                kingdom_id  INTEGER REFERENCES kingdoms(id) ON DELETE CASCADE,
                lord_id     BIGINT       UNIQUE,
                gold        INTEGER      DEFAULT 0,
                soldiers    INTEGER      DEFAULT 0,
                created_at  TIMESTAMP    DEFAULT NOW()
            )
        """)

        # ── Users ─────────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id     BIGINT   PRIMARY KEY,
                username        VARCHAR(100),
                full_name       VARCHAR(200),
                role            VARCHAR(20)  DEFAULT 'member',
                kingdom_id      INTEGER      REFERENCES kingdoms(id),
                vassal_id       INTEGER      REFERENCES vassals(id),
                gold            INTEGER      DEFAULT 0,
                last_farm       TIMESTAMP,
                joined_at       TIMESTAMP    DEFAULT NOW()
            )
        """)

        # ── Chronicles (event log) ────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chronicles (
                id          SERIAL PRIMARY KEY,
                event_type  VARCHAR(50) NOT NULL,
                title       VARCHAR(200),
                description TEXT,
                actor_id    BIGINT,
                target_id   BIGINT,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Diplomacy ─────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS diplomacy (
                id              SERIAL PRIMARY KEY,
                from_kingdom_id INTEGER REFERENCES kingdoms(id),
                to_kingdom_id   INTEGER REFERENCES kingdoms(id),
                offer_type      VARCHAR(20) NOT NULL,  -- 'war' | 'alliance'
                status          VARCHAR(20) DEFAULT 'pending',
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Lord elections ────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS elections (
                id          SERIAL PRIMARY KEY,
                vassal_id   INTEGER REFERENCES vassals(id),
                candidate_id BIGINT,
                voter_id    BIGINT,
                created_at  TIMESTAMP DEFAULT NOW(),
                UNIQUE(vassal_id, voter_id)
            )
        """)

        # ── Artifacts ─────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id          SERIAL PRIMARY KEY,
                owner_type  VARCHAR(20),   -- 'kingdom' | 'vassal' | 'user'
                owner_id    INTEGER,
                artifact    VARCHAR(50),
                tier        VARCHAR(5),
                purchased_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Queue tracking ────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS queue_state (
                id          INTEGER PRIMARY KEY DEFAULT 1,
                phase       INTEGER DEFAULT 2,
                current_vassal_index INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            INSERT INTO queue_state (id, phase, current_vassal_index)
            VALUES (1, 2, 0)
            ON CONFLICT (id) DO NOTHING
        """)

        # ── Hukmdor da'vosi ───────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hukmdor_claims (
                id                  SERIAL PRIMARY KEY,
                claimant_vassal_id  INTEGER NOT NULL REFERENCES vassals(id) ON DELETE CASCADE,
                kingdom_id          INTEGER NOT NULL REFERENCES kingdoms(id) ON DELETE CASCADE,
                status              VARCHAR(20) DEFAULT 'pending',
                created_at          TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hukmdor_claim_responses (
                id           SERIAL PRIMARY KEY,
                claim_id     INTEGER NOT NULL REFERENCES hukmdor_claims(id) ON DELETE CASCADE,
                vassal_id    INTEGER NOT NULL,
                response     VARCHAR(10) NOT NULL,
                responded_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (claim_id, vassal_id)
            )
        """)

        # ── Assassination hits ────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS assassination_hits (
                id            SERIAL PRIMARY KEY,
                target_id     BIGINT NOT NULL,
                attacker_id   BIGINT NOT NULL,
                attacker_role VARCHAR(20),
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Wars ──────────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wars (
                id             SERIAL PRIMARY KEY,
                attacker_id    INTEGER REFERENCES kingdoms(id),
                defender_id    INTEGER REFERENCES kingdoms(id),
                status         VARCHAR(20) DEFAULT 'pending',
                starts_at      TIMESTAMP,
                ended_at       TIMESTAMP,
                winner_id      INTEGER REFERENCES kingdoms(id),
                attacker_power INTEGER DEFAULT 0,
                defender_power INTEGER DEFAULT 0,
                created_at     TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── War support ───────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS war_support (
                id          SERIAL PRIMARY KEY,
                war_id      INTEGER REFERENCES wars(id),
                from_type   VARCHAR(20),
                from_id     INTEGER,
                to_kingdom  INTEGER REFERENCES kingdoms(id),
                gold        INTEGER DEFAULT 0,
                soldiers    INTEGER DEFAULT 0,
                scorpions   INTEGER DEFAULT 0,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Tributes ──────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tributes (
                id           SERIAL PRIMARY KEY,
                war_id       INTEGER REFERENCES wars(id),
                from_kingdom INTEGER REFERENCES kingdoms(id),
                to_kingdom   INTEGER REFERENCES kingdoms(id),
                active       BOOLEAN DEFAULT TRUE,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Market prices ─────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_prices (
                item    VARCHAR(50) PRIMARY KEY,
                price   INTEGER     NOT NULL,
                label   VARCHAR(100)
            )
        """)
        default_prices = [
            ("dragon_a", 150, "🐉 Ajdar A"),
            ("dragon_b", 100, "🐉 Ajdar B"),
            ("dragon_c",  60, "🐉 Ajdar C"),
            ("scorpion",  25, "🦂 Chayon"),
        ]
        for item, price, label in default_prices:
            await conn.execute("""
                INSERT INTO market_prices (item, price, label)
                VALUES ($1, $2, $3)
                ON CONFLICT (item) DO NOTHING
            """, item, price, label)

        # ── Loans ─────────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS loans (
                id            SERIAL PRIMARY KEY,
                borrower_type VARCHAR(20),
                borrower_id   INTEGER,
                amount        INTEGER,
                interest      INTEGER DEFAULT 0,
                total_due     INTEGER,
                paid          INTEGER DEFAULT 0,
                status        VARCHAR(20) DEFAULT 'active',
                due_date      TIMESTAMP,
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Game settings ─────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_settings (
                key   VARCHAR(50) PRIMARY KEY,
                value TEXT
            )
        """)
        await conn.execute("""
            INSERT INTO game_settings (key, value) VALUES ('game_active', 'true')
            ON CONFLICT (key) DO NOTHING
        """)

        # Qirolliklarning gold/soldiers ni 0 ga reset qilish (ular endi vassallarda saqlanadi)
        await conn.execute("UPDATE kingdoms SET gold=0, soldiers=0")

        # ══════════════════════════════════════════════════════════════════════
        # Da'vogarlik (Claim) tizimi
        # Logika:
        #   1. Lord /claim yoki tugma orqali o'z qirolligiga da'vo qiladi
        #   2. Bot shu qirollikdagi boshqa barcha Lord larga xabar yuboradi
        #   3. Har bir Lord: "Qabul" yoki "Urush" deydi
        #   4. Hammasi qabul qilsa → claimant avtomatik Qirol bo'ladi
        #   5. Kimdir urush desa → ikki vassal o'rtasida soldiers bilan jang
        # ══════════════════════════════════════════════════════════════════════
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id                 SERIAL PRIMARY KEY,
                claimant_vassal_id INTEGER REFERENCES vassals(id) ON DELETE CASCADE,
                kingdom_id         INTEGER REFERENCES kingdoms(id) ON DELETE CASCADE,
                status             VARCHAR(20) DEFAULT 'pending',
                created_at         TIMESTAMP DEFAULT NOW(),
                resolved_at        TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS claim_responses (
                id          SERIAL PRIMARY KEY,
                claim_id    INTEGER REFERENCES claims(id) ON DELETE CASCADE,
                vassal_id   INTEGER REFERENCES vassals(id) ON DELETE CASCADE,
                response    VARCHAR(20),
                created_at  TIMESTAMP DEFAULT NOW(),
                UNIQUE(claim_id, vassal_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS claim_wars (
                id                   SERIAL PRIMARY KEY,
                claim_id             INTEGER REFERENCES claims(id) ON DELETE CASCADE,
                claimant_vassal_id   INTEGER REFERENCES vassals(id),
                challenger_vassal_id INTEGER REFERENCES vassals(id),
                winner_vassal_id     INTEGER REFERENCES vassals(id),
                claimant_power       INTEGER DEFAULT 0,
                challenger_power     INTEGER DEFAULT 0,
                status               VARCHAR(20) DEFAULT 'active',
                created_at           TIMESTAMP DEFAULT NOW(),
                ended_at             TIMESTAMP
            )
        """)

    logger.info("Database initialized successfully")
