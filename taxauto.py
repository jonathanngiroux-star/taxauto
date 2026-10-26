#!/usr/bin/env python3
"""
TaxAuto - Tax Filing Automation
Periodic crypto-gains filing obligations for SMEs, freelancers, traders.
"""

import json
import sqlite3
import csv
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta
import argparse
import sys
import hashlib


@dataclass
class Transaction:
    tx_hash: str
    chain: str
    timestamp: str
    tx_type: str  # buy, sell, swap, transfer_in, transfer_out, stake, unstake, reward, airdrop, fee
    asset: str
    amount: float
    price_usd: float
    cost_basis_usd: float = 0.0
    gain_loss_usd: float = 0.0
    fee_usd: float = 0.0
    exchange: str = ""
    wallet: str = ""
    notes: str = ""


@dataclass
class TaxLot:
    id: str
    asset: str
    amount: float
    cost_basis_per_unit: float
    acquired_date: str
    acquired_tx_hash: str
    remaining_amount: float
    wallet: str


@dataclass
class TaxReport:
    tax_year: int
    wallet: str
    generated_at: str
    short_term_gains: float
    long_term_gains: float
    total_gains: float
    total_losses: float
    net_gain_loss: float
    transactions: List[Dict]
    summary_by_asset: Dict[str, Dict]


class TaxAuto:
    def __init__(self, db_path: str = "./taxauto.db", config_path: str = "./config.json"):
        self.db_path = db_path
        self.config_path = config_path
        self.config = self._load_config()
        self._init_db()

    def _load_config(self) -> Dict:
        if Path(self.config_path).exists():
            with open(self.config_path) as f:
                return json.load(f)
        return {
            "accounting_method": "FIFO",  # FIFO, LIFO, HIFO
            "tax_year": datetime.now().year,
            "default_currency": "USD",
            "price_sources": {
                "coingecko": "https://api.coingecko.com/api/v3",
            },
            "report_output_dir": "./reports",
        }

    def _save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    tx_hash TEXT PRIMARY KEY,
                    chain TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    tx_type TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    amount REAL NOT NULL,
                    price_usd REAL NOT NULL,
                    cost_basis_usd REAL DEFAULT 0,
                    gain_loss_usd REAL DEFAULT 0,
                    fee_usd REAL DEFAULT 0,
                    exchange TEXT,
                    wallet TEXT,
                    notes TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tax_lots (
                    id TEXT PRIMARY KEY,
                    asset TEXT NOT NULL,
                    amount REAL NOT NULL,
                    cost_basis_per_unit REAL NOT NULL,
                    acquired_date TEXT NOT NULL,
                    acquired_tx_hash TEXT NOT NULL,
                    remaining_amount REAL NOT NULL,
                    wallet TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    tax_year INTEGER NOT NULL,
                    wallet TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    short_term_gains REAL,
                    long_term_gains REAL,
                    total_gains REAL,
                    total_losses REAL,
                    net_gain_loss REAL,
                    report_data TEXT
                )
            """)

    def import_transactions_csv(self, csv_path: str, wallet: str = "") -> int:
        imported = 0
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tx = Transaction(
                    tx_hash=row.get('tx_hash', hashlib.md5(f"{row}{datetime.now()}".encode()).hexdigest()[:16]),
                    chain=row.get('chain', 'ethereum'),
                    timestamp=row.get('timestamp', datetime.now().isoformat()),
                    tx_type=row.get('type', row.get('tx_type', 'swap')),
                    asset=row.get('asset', row.get('token', 'ETH')),
                    amount=float(row.get('amount', 0)),
                    price_usd=float(row.get('price_usd', row.get('value_usd', 0))),
                    fee_usd=float(row.get('fee_usd', row.get('fee', 0))),
                    exchange=row.get('exchange', ''),
                    wallet=wallet or row.get('wallet', ''),
                    notes=row.get('notes', ''),
                )
                if self.add_transaction(tx):
                    imported += 1
        return imported

    def add_transaction(self, tx: Transaction) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO transactions 
                    (tx_hash, chain, timestamp, tx_type, asset, amount, price_usd, cost_basis_usd, gain_loss_usd, fee_usd, exchange, wallet, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (tx.tx_hash, tx.chain, tx.timestamp, tx.tx_type, tx.asset, tx.amount,
                      tx.price_usd, tx.cost_basis_usd, tx.gain_loss_usd, tx.fee_usd,
                      tx.exchange, tx.wallet, tx.notes))
                return True
            except sqlite3.Error:
                return False

    def calculate_gains(self, wallet: str = "", tax_year: int = None) -> TaxReport:
        if tax_year is None:
            tax_year = self.config["tax_year"]

        method = self.config.get("accounting_method", "FIFO")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM transactions WHERE 1=1"
            params = []
            if wallet:
                query += " AND wallet = ?"
                params.append(wallet)
            if tax_year:
                query += " AND strftime('%Y', timestamp) = ?"
                params.append(str(tax_year))
            query += " ORDER BY timestamp ASC"

            rows = conn.execute(query, params).fetchall()

        # Group transactions by asset for lot tracking
        lots_by_asset: Dict[str, List[TaxLot]] = {}
        processed_txs = []

        for row in rows:
            tx = Transaction(**dict(row))
            
            if tx.tx_type in ('buy', 'transfer_in', 'reward', 'airdrop', 'stake'):
                # Acquire new lot
                lot = TaxLot(
                    id=hashlib.md5(f"{tx.tx_hash}{tx.asset}".encode()).hexdigest()[:16],
                    asset=tx.asset,
                    amount=tx.amount,
                    cost_basis_per_unit=tx.price_usd,
                    acquired_date=tx.timestamp,
                    acquired_tx_hash=tx.tx_hash,
                    remaining_amount=tx.amount,
                    wallet=tx.wallet,
                )
                if tx.asset not in lots_by_asset:
                    lots_by_asset[tx.asset] = []
                lots_by_asset[tx.asset].append(lot)
                tx.cost_basis_usd = tx.amount * tx.price_usd
                tx.gain_loss_usd = 0

            elif tx.tx_type in ('sell', 'transfer_out', 'swap', 'unstake'):
                # Dispose of lots
                if tx.asset not in lots_by_asset or not lots_by_asset[tx.asset]:
                    # No lots available - treat as zero cost basis
                    tx.cost_basis_usd = 0
                    tx.gain_loss_usd = tx.amount * tx.price_usd - tx.fee_usd
                else:
                    lots = lots_by_asset[tx.asset]
                    if method == "LIFO":
                        lots = list(reversed(lots))
                    elif method == "HIFO":
                        lots = sorted(lots, key=lambda l: l.cost_basis_per_unit, reverse=True)

                    remaining_to_sell = tx.amount
                    total_cost_basis = 0
                    total_gain_loss = 0

                    for lot in lots:
                        if remaining_to_sell <= 0:
                            break
                        if lot.remaining_amount <= 0:
                            continue

                        sell_from_lot = min(remaining_to_sell, lot.remaining_amount)
                        lot_cost = sell_from_lot * lot.cost_basis_per_unit
                        lot_gain = sell_from_lot * tx.price_usd - lot_cost

                        total_cost_basis += lot_cost
                        total_gain_loss += lot_gain
                        lot.remaining_amount -= sell_from_lot
                        remaining_to_sell -= sell_from_lot

                        # Classify as short/long term
                        acquired = datetime.fromisoformat(lot.acquired_date.replace('Z', '+00:00'))
                        disposed = datetime.fromisoformat(tx.timestamp.replace('Z', '+00:00'))
                        holding_period = (disposed - acquired).days

                    tx.cost_basis_usd = total_cost_basis
                    tx.gain_loss_usd = total_gain_loss - tx.fee_usd

            processed_txs.append(tx)

        # Calculate summary
        short_term = 0
        long_term = 0
        total_gains = 0
        total_losses = 0

        for tx in processed_txs:
            if tx.gain_loss_usd > 0:
                total_gains += tx.gain_loss_usd
                # Determine holding period (simplified)
                # In production, would track per-lot
                short_term += tx.gain_loss_usd  # Simplified
            elif tx.gain_loss_usd < 0:
                total_losses += abs(tx.gain_loss_usd)
                short_term += tx.gain_loss_usd  # Simplified

        summary_by_asset = {}
        for tx in processed_txs:
            if tx.asset not in summary_by_asset:
                summary_by_asset[tx.asset] = {"gains": 0, "losses": 0, "volume": 0, "count": 0}
            summary_by_asset[tx.asset]["volume"] += tx.amount * tx.price_usd
            summary_by_asset[tx.asset]["count"] += 1
            if tx.gain_loss_usd > 0:
                summary_by_asset[tx.asset]["gains"] += tx.gain_loss_usd
            elif tx.gain_loss_usd < 0:
                summary_by_asset[tx.asset]["losses"] += abs(tx.gain_loss_usd)

        return TaxReport(
            tax_year=tax_year,
            wallet=wallet or "all",
            generated_at=datetime.now().isoformat(),
            short_term_gains=short_term,
            long_term_gains=long_term,
            total_gains=total_gains,
            total_losses=total_losses,
            net_gain_loss=total_gains - total_losses,
            transactions=[asdict(tx) for tx in processed_txs],
            summary_by_asset=summary_by_asset,
        )

    def save_report(self, report: TaxReport):
        report_id = hashlib.md5(f"{report.tax_year}{report.wallet}{report.generated_at}".encode()).hexdigest()[:16]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO reports 
                (id, tax_year, wallet, generated_at, short_term_gains, long_term_gains, total_gains, total_losses, net_gain_loss, report_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (report_id, report.tax_year, report.wallet, report.generated_at,
                  report.short_term_gains, report.long_term_gains, report.total_gains,
                  report.total_losses, report.net_gain_loss, json.dumps(asdict(report))))

    def export_report_csv(self, report: TaxReport, output_path: str):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', newline='') as f:
            if report.transactions:
                writer = csv.DictWriter(f, fieldnames=report.transactions[0].keys())
                writer.writeheader()
                writer.writerows(report.transactions)

    def export_summary_csv(self, report: TaxReport, output_path: str):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Asset', 'Transactions', 'Volume (USD)', 'Gains (USD)', 'Losses (USD)', 'Net (USD)'])
            for asset, data in report.summary_by_asset.items():
                writer.writerow([
                    asset, data['count'], f"{data['volume']:.2f}",
                    f"{data['gains']:.2f}", f"{data['losses']:.2f}",
                    f"{data['gains'] - data['losses']:.2f}"
                ])

    def list_transactions(self, wallet: str = "", limit: int = 100) -> List[Transaction]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM transactions WHERE 1=1"
            params = []
            if wallet:
                query += " AND wallet = ?"
                params.append(wallet)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [Transaction(**dict(row)) for row in rows]

    def get_wallets(self) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT DISTINCT wallet FROM transactions WHERE wallet != ''").fetchall()
            return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser(description="TaxAuto - Crypto Tax Filing Automation")
    parser.add_argument("-c", "--config", default="./config.json", help="Config file")
    parser.add_argument("-d", "--db", default="./taxauto.db", help="Database path")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Import CSV
    import_parser = subparsers.add_parser("import", help="Import transactions from CSV")
    import_parser.add_argument("csv_file", help="CSV file path")
    import_parser.add_argument("--wallet", default="", help="Wallet label")

    # Add transaction
    add_parser = subparsers.add_parser("add", help="Add single transaction")
    add_parser.add_argument("--hash", required=True)
    add_parser.add_argument("--chain", default="ethereum")
    add_parser.add_argument("--timestamp", required=True)
    add_parser.add_argument("--type", required=True, choices=['buy', 'sell', 'swap', 'transfer_in', 'transfer_out', 'stake', 'unstake', 'reward', 'airdrop', 'fee'])
    add_parser.add_argument("--asset", required=True)
    add_parser.add_argument("--amount", type=float, required=True)
    add_parser.add_argument("--price", type=float, required=True)
    add_parser.add_argument("--fee", type=float, default=0)
    add_parser.add_argument("--exchange", default="")
    add_parser.add_argument("--wallet", default="")
    add_parser.add_argument("--notes", default="")

    # Calculate gains
    calc_parser = subparsers.add_parser("calculate", help="Calculate gains/losses")
    calc_parser.add_argument("--wallet", default="")
    calc_parser.add_argument("--year", type=int, default=datetime.now().year)
    calc_parser.add_argument("--output", help="Output CSV path")

    # List transactions
    list_parser = subparsers.add_parser("list", help="List transactions")
    list_parser.add_argument("--wallet", default="")
    list_parser.add_argument("--limit", type=int, default=100)

    # Wallets
    subparsers.add_parser("wallets", help="List wallets")

    args = parser.parse_args()

    tax = TaxAuto(db_path=args.db, config_path=args.config)

    if args.action == "import":
        count = tax.import_transactions_csv(args.csv_file, args.wallet)
        print(f"Imported {count} transactions")

    elif args.action == "add":
        tx = Transaction(
            tx_hash=args.hash,
            chain=args.chain,
            timestamp=args.timestamp,
            tx_type=args.type,
            asset=args.asset,
            amount=args.amount,
            price_usd=args.price,
            fee_usd=args.fee,
            exchange=args.exchange,
            wallet=args.wallet,
            notes=args.notes,
        )
        if tax.add_transaction(tx):
            print(f"Added transaction {tx.tx_hash}")
        else:
            print("Failed to add transaction")

    elif args.action == "calculate":
        report = tax.calculate_gains(args.wallet, args.year)
        tax.save_report(report)
        
        print(f"\n=== Tax Report for {report.tax_year} ===")
        print(f"Wallet: {report.wallet}")
        print(f"Short-term Gains: ${report.short_term_gains:,.2f}")
        print(f"Long-term Gains: ${report.long_term_gains:,.2f}")
        print(f"Total Gains: ${report.total_gains:,.2f}")
        print(f"Total Losses: ${report.total_losses:,.2f}")
        print(f"Net Gain/Loss: ${report.net_gain_loss:,.2f}")
        print(f"\nBy Asset:")
        for asset, data in report.summary_by_asset.items():
            net = data['gains'] - data['losses']
            print(f"  {asset}: {data['count']} txs, Vol: ${data['volume']:,.2f}, Gain: ${data['gains']:,.2f}, Loss: ${data['losses']:,.2f}, Net: ${net:,.2f}")

        if args.output:
            tax.export_report_csv(report, args.output)
            tax.export_summary_csv(report, args.output.replace('.csv', '_summary.csv'))
            print(f"\nExported to {args.output}")

    elif args.action == "list":
        txs = tax.list_transactions(args.wallet, args.limit)
        for tx in txs:
            print(f"{tx.timestamp[:19]} | {tx.tx_type:12} | {tx.asset:8} | {tx.amount:12.6f} | ${tx.price_usd:>10.2f} | ${tx.gain_loss_usd:>10.2f} | {tx.wallet}")

    elif args.action == "wallets":
        wallets = tax.get_wallets()
        for w in wallets:
            print(w)


if __name__ == "__main__":
    main()