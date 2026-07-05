"""
Clean-slate reset for one user's learned state.

WHY THIS EXISTS
---------------
All data collected before the look-ahead-bias fix has systematically biased
simulated P&L and training labels — the models learned from trade mechanics that
peeked at the future. To start fresh you must wipe the *learned state* so nothing
carries the old bias forward.

WHAT GETS DELETED (always), scoped strictly to the given user:
    predictions   — every prediction row and its (biased) P&L / outcome
    cc_history    — Champion/Challenger promotion history
    model_levels  — XP, levels, streaks, bars_learned
    model_state   — ALL persisted model weights (8 River models + Personal + LSTM)

RAW PRICE BARS (`ticks`):
    Kept by default. The OHLCV price data itself is NOT biased — only the trade
    simulation and labels derived from it were. So the recommended flow is to
    KEEP the bars (--keep-bars) and retrain on them cleanly via training mode,
    now that the look-ahead mechanics are fixed. Pass no flag / --include-bars to
    also delete the price history for a total wipe.

USAGE
-----
    cd backend
    python -m scripts.reset_user_data --email you@example.com --keep-bars
    python -m scripts.reset_user_data --email you@example.com            # also deletes bars

The script prints exactly what it will delete (with row counts) and requires you
to type RESET to confirm before anything is deleted.

NOTE: run this while the backend is stopped (or restart it afterward). On next
start everything re-initializes cleanly from the emptied tables — models at
level 1 with fresh weights, LSTM dormant, watermark reseeded from remaining bars.
"""

import argparse
import asyncio
import sys

import asyncpg

from app.core.config import settings
from app.services.user_reset import count_user_data, reset_user_data


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reset_user_data",
        description=(
            "Wipe one user's learned state (predictions, CC history, levels, model "
            "weights). Raw price bars are KEPT unless you ask to delete them. The "
            "recommended clean-slate flow after the look-ahead-bias fix is "
            "--keep-bars, then retrain via training mode on the clean price history."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--email", required=True, help="Email of the user to reset.")
    bars = parser.add_mutually_exclusive_group()
    bars.add_argument(
        "--keep-bars", dest="keep_bars", action="store_true", default=True,
        help="Keep raw OHLCV bars (default). Price data is not biased — retrain on it cleanly.",
    )
    bars.add_argument(
        "--include-bars", dest="keep_bars", action="store_false",
        help="ALSO delete all raw price bars for a total wipe.",
    )
    return parser.parse_args(argv)


async def _run(email: str, keep_bars: bool) -> int:
    include_bars = not keep_bars
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        user = await conn.fetchrow("SELECT id, email FROM users WHERE email = $1", email)
        if user is None:
            print(f"✗ No user found with email {email!r}. Nothing to do.")
            return 1

        user_id = user["id"]
        counts = await count_user_data(conn, user_id, include_bars=include_bars)

        print()
        print(f"About to reset ALL learned state for: {user['email']}  (user_id={user_id})")
        print("The following rows will be PERMANENTLY DELETED:")
        for table in ("predictions", "cc_history", "model_levels", "model_state"):
            print(f"    {table:<14} {counts[table]:>10,} rows")
        if include_bars:
            print(f"    {'ticks':<14} {counts['ticks']:>10,} rows   ← raw price bars (--include-bars)")
        else:
            print(f"    {'ticks':<14} {'(kept)':>10}          ← raw price bars preserved (--keep-bars)")
        print()

        try:
            answer = input('Type RESET to confirm (anything else aborts): ')
        except EOFError:
            answer = ""
        if answer.strip() != "RESET":
            print("Aborted — nothing was deleted.")
            return 1

        deleted = await reset_user_data(conn, user_id, include_bars=include_bars)

        print()
        print("✓ Reset complete. Deleted:")
        for table, n in deleted.items():
            print(f"    {table:<14} {n:>10,} rows")
        print()
        if include_bars:
            print("All price history was also removed — the user starts from an empty slate.")
        else:
            print("Price bars were KEPT. Recommended next step:")
            print("  1. Start the backend (models come up fresh at level 1, LSTM dormant).")
            print("  2. Turn on Training Mode and replay your sessions — with the look-ahead")
            print("     fixes in place, this produces clean learned state from clean mechanics.")
        return 0
    finally:
        await conn.close()


def main() -> None:
    args = _parse_args()
    sys.exit(asyncio.run(_run(args.email, args.keep_bars)))


if __name__ == "__main__":
    main()
