#!/usr/bin/env python3
"""
Interactive setup — run this once before starting the algo.
It will ask for your Kalshi credentials and write the config file.
"""
import getpass
import os
import subprocess
import sys


def ask(prompt, default=None, secret=False):
    if default:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "
    if secret:
        value = getpass.getpass(display)
    else:
        value = input(display).strip()
    if not value and default:
        return default
    return value


def main():
    print()
    print("=" * 50)
    print("  BTC Hourly Kalshi Algo — First-Time Setup")
    print("=" * 50)
    print()

    # Check if .env already exists
    if os.path.exists(".env"):
        overwrite = input(".env already exists. Overwrite it? (y/n): ").strip().lower()
        if overwrite != "y":
            print("Setup cancelled.")
            return

    print("Enter your Kalshi account details.")
    print("(Your password is hidden when you type it.)")
    print()

    email = ask("Kalshi email")
    if not email:
        print("Error: email is required.")
        sys.exit(1)

    password = ask("Kalshi password", secret=True)
    if not password:
        print("Error: password is required.")
        sys.exit(1)

    print()
    print("Mode:")
    print("  dry   — watches real markets and logs what it would have traded,")
    print("          but never places a real order. No money at risk.")
    print("          (recommended to start — run for a few days to verify it works)")
    print("  live  — places real orders with real money")
    print()
    mode = ask("Choose mode", default="dry")
    if mode not in ("dry", "live"):
        print("Invalid choice, defaulting to dry run.")
        mode = "dry"
    dry_run = mode == "dry"

    sim_balance = "10000"
    max_per_trade = "25"

    if dry_run:
        sim_balance = ask("Simulated starting balance in dollars", default="10000")
    else:
        print()
        print("Position sizing — how much real money per trade:")
        print("  Kalshi contracts are $1 face value. At 91 cents each,")
        print("  $25 buys about 27 contracts. Start small until you're confident.")
        print()
        max_per_trade = ask("Maximum dollars per single trade", default="25")

    print()
    print("Risk settings (press Enter to keep the defaults):")
    min_prob = ask("Minimum probability to trade, e.g. 0.91 = 91%", default="0.91")
    daily_loss = ask("Daily loss limit % (stop if down this much), e.g. 0.05 = 5%", default="0.05")

    env_content = f"""# Kalshi credentials
KALSHI_EMAIL={email}
KALSHI_PASSWORD={password}

# DRY_RUN=true  → reads real prices, logs simulated trades, never places orders
# DRY_RUN=false → places real orders with real money
DRY_RUN={"true" if dry_run else "false"}
SIMULATED_BALANCE={sim_balance}

# Risk settings
MIN_TRUE_PROBABILITY={min_prob}
MAX_TRUE_PROBABILITY=0.97
MIN_EDGE=0.03
MAX_OPEN_POSITIONS=5
KELLY_FRACTION=0.25
MAX_BANKROLL_PCT_PER_TRADE=0.02
MAX_DOLLARS_PER_TRADE={max_per_trade}
DAILY_LOSS_LIMIT_PCT={daily_loss}
DRAWDOWN_LIMIT_PCT=0.10
"""

    with open(".env", "w") as f:
        f.write(env_content)

    print()
    print("✓ Config saved to .env")

    # Install dependencies
    print()
    print("Installing required Python packages...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("✓ Packages installed")
    else:
        print("Warning: some packages may not have installed correctly.")
        print(result.stderr[:300])

    print()
    print("=" * 50)
    print("  Setup complete!")
    print()
    if dry_run:
        print("  You are in DRY RUN mode.")
        print("  The algo will watch real markets and log every trade it would")
        print(f"  have made, starting from a simulated ${sim_balance} balance.")
        print("  No real orders will be placed.")
    else:
        print(f"  LIVE mode — real orders up to ${max_per_trade} per trade.")
        print("  Daily loss limit: stops automatically if down "
              f"{float(daily_loss)*100:.0f}% on the day.")
    print()
    print("  To start the algo, run:")
    print()
    print("      python run.py")
    print()
    print("  To stop it at any time, press Ctrl+C")
    print("=" * 50)
    print()


if __name__ == "__main__":
    main()
