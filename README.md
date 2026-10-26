# Tax Filing Automation

Periodic crypto-gains filing obligations for SMEs, freelancers, traders.

## Service Description

TaxAuto automates crypto tax calculations and filing preparation:

- **Multi-chain transaction import** — CSV import from exchanges, wallets, block explorers
- **Cost basis tracking** — FIFO, LIFO, HIFO accounting methods
- **Gain/loss calculation** — Short-term vs long-term classification
- **Per-asset summaries** — Volume, gains, losses, net position
- **Report generation** — CSV exports for tax software (TurboTax, CoinTracker, Koinly)
- **Multi-wallet support** — Consolidated reporting across wallets
- **Audit trail** — Complete transaction history with cost basis

Pricing: **$49–199/mo** (Accountability tier)

## Installation

```bash
git clone https://github.com/jonathanngiroux-star/taxauto
cd taxauto
pip install -r requirements.txt
# or
pip install git+https://github.com/jonathanngiroux-star/taxauto
```

## Configuration

Create `config.json`:

```json
{
  "accounting_method": "FIFO",
  "tax_year": 2024,
  "default_currency": "USD",
  "report_output_dir": "./reports"
}
```

## CSV Import Format

```csv
tx_hash,chain,timestamp,type,asset,amount,price_usd,fee_usd,exchange,wallet,notes
0x123...,ethereum,2024-01-15T10:30:00,buy,ETH,1.5,2500.00,5.00,coinbase,main_wallet,
0x456...,ethereum,2024-06-20T14:00:00,sell,ETH,0.5,3200.00,3.00,uniswap,main_wallet,
```

Supported types: `buy`, `sell`, `swap`, `transfer_in`, `transfer_out`, `stake`, `unstake`, `reward`, `airdrop`, `fee`

## CLI Interface

```bash
# Import from CSV
taxauto import transactions.csv --wallet "main_wallet"

# Add single transaction
taxauto add --hash 0x123... --chain ethereum --timestamp "2024-01-15T10:30:00" \
  --type buy --asset ETH --amount 1.5 --price 2500 --fee 5 --wallet main_wallet

# Calculate gains/losses
taxauto calculate --wallet main_wallet --year 2024 --output report.csv

# List transactions
taxauto list --wallet main_wallet --limit 50

# List wallets
taxauto wallets
```

## Accounting Methods

| Method | Description |
|--------|-------------|
| **FIFO** | First In, First Out (default, IRS preferred) |
| **LIFO** | Last In, First Out |
| **HIFO** | Highest In, First Out (tax optimization) |

## Report Outputs

- `report.csv` — Detailed transaction list with gain/loss per transaction
- `report_summary.csv` — Per-asset summary (count, volume, gains, losses, net)

## Pricing

| Tier | Price | Includes |
|------|-------|----------|
| Personal | $49/mo | Up to 1,000 txs/yr, FIFO only, CSV export |
| Professional | $99/mo | Up to 10,000 txs/yr, all methods, multi-wallet, API |
| Enterprise | $199/mo | Unlimited txs, CPA review, audit support, white-label |

## Hosted Version

Managed tax automation at **katsironni.com/taxauto** — includes CPA review, audit support, multi-jurisdiction.

## License

MIT — see [LICENSE](LICENSE)