import pytest
import tempfile
import os
import csv
from taxauto import TaxAuto, Transaction, TaxLot

@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)

@pytest.fixture
def temp_config():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
        import json
        json.dump({"accounting_method": "FIFO", "tax_year": 2024}, f)
        config_path = f.name
    yield config_path
    if os.path.exists(config_path):
        os.unlink(config_path)

@pytest.fixture
def tax(temp_db, temp_config):
    return TaxAuto(db_path=temp_db, config_path=temp_config)

def test_add_transaction(tax):
    tx = Transaction(
        tx_hash="0x123",
        chain="ethereum",
        timestamp="2024-01-15T10:00:00",
        tx_type="buy",
        asset="ETH",
        amount=1.0,
        price_usd=2500.0,
        fee_usd=5.0,
        wallet="test_wallet",
    )
    assert tax.add_transaction(tx) == True

    txs = tax.list_transactions("test_wallet")
    assert len(txs) == 1
    assert txs[0].asset == "ETH"
    assert txs[0].amount == 1.0

def test_duplicate_transaction(tax):
    tx = Transaction(
        tx_hash="0x123",
        chain="ethereum",
        timestamp="2024-01-15T10:00:00",
        tx_type="buy",
        asset="ETH",
        amount=1.0,
        price_usd=2500.0,
        wallet="test_wallet",
    )
    tax.add_transaction(tx)
    tax.add_transaction(tx)  # Should not fail
    txs = tax.list_transactions("test_wallet")
    assert len(txs) == 1

def test_calculate_gains_fifo(tax):
    # Buy 1 ETH at $2500
    tax.add_transaction(Transaction(
        tx_hash="0x1", chain="ethereum", timestamp="2024-01-15T10:00:00",
        tx_type="buy", asset="ETH", amount=1.0, price_usd=2500.0, wallet="w1"
    ))
    # Buy 1 ETH at $3000
    tax.add_transaction(Transaction(
        tx_hash="0x2", chain="ethereum", timestamp="2024-02-15T10:00:00",
        tx_type="buy", asset="ETH", amount=1.0, price_usd=3000.0, wallet="w1"
    ))
    # Sell 1 ETH at $3500 (FIFO: should use first lot at $2500)
    tax.add_transaction(Transaction(
        tx_hash="0x3", chain="ethereum", timestamp="2024-06-15T10:00:00",
        tx_type="sell", asset="ETH", amount=1.0, price_usd=3500.0, wallet="w1"
    ))

    report = tax.calculate_gains("w1", 2024)
    # Gain should be 3500 - 2500 = 1000 (FIFO uses first lot)
    assert report.net_gain_loss == 1000.0

def test_calculate_gains_lifo(tax, temp_config):
    import json
    with open(temp_config, 'w') as f:
        json.dump({"accounting_method": "LIFO", "tax_year": 2024}, f)
    
    tax2 = TaxAuto(db_path=tax.db_path, config_path=temp_config)
    
    tax2.add_transaction(Transaction(
        tx_hash="0x1", chain="ethereum", timestamp="2024-01-15T10:00:00",
        tx_type="buy", asset="ETH", amount=1.0, price_usd=2500.0, wallet="w1"
    ))
    tax2.add_transaction(Transaction(
        tx_hash="0x2", chain="ethereum", timestamp="2024-02-15T10:00:00",
        tx_type="buy", asset="ETH", amount=1.0, price_usd=3000.0, wallet="w1"
    ))
    tax2.add_transaction(Transaction(
        tx_hash="0x3", chain="ethereum", timestamp="2024-06-15T10:00:00",
        tx_type="sell", asset="ETH", amount=1.0, price_usd=3500.0, wallet="w1"
    ))

    report = tax2.calculate_gains("w1", 2024)
    # LIFO: should use second lot at $3000, gain = 3500 - 3000 = 500
    assert report.net_gain_loss == 500.0

def test_import_csv(tax):
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['tx_hash', 'chain', 'timestamp', 'type', 'asset', 'amount', 'price_usd', 'fee_usd', 'exchange', 'wallet', 'notes'])
        writer.writerow(['0xabc', 'ethereum', '2024-01-15T10:00:00', 'buy', 'ETH', '1.0', '2500.0', '5.0', 'coinbase', 'w1', ''])
        writer.writerow(['0xdef', 'ethereum', '2024-02-15T10:00:00', 'sell', 'ETH', '0.5', '3000.0', '3.0', 'uniswap', 'w1', ''])
        csv_path = f.name
    
    try:
        count = tax.import_transactions_csv(csv_path, "w1")
        assert count == 2
        
        txs = tax.list_transactions("w1")
        assert len(txs) == 2
    finally:
        os.unlink(csv_path)

def test_multi_wallet(tax):
    tax.add_transaction(Transaction(
        tx_hash="0x1", chain="ethereum", timestamp="2024-01-15T10:00:00",
        tx_type="buy", asset="ETH", amount=1.0, price_usd=2500.0, wallet="wallet1"
    ))
    tax.add_transaction(Transaction(
        tx_hash="0x2", chain="ethereum", timestamp="2024-01-15T10:00:00",
        tx_type="buy", asset="BTC", amount=0.1, price_usd=45000.0, wallet="wallet2"
    ))

    wallets = tax.get_wallets()
    assert "wallet1" in wallets
    assert "wallet2" in wallets
    assert len(wallets) == 2

    report1 = tax.calculate_gains("wallet1", 2024)
    assert len(report1.transactions) == 1
    assert report1.transactions[0]['asset'] == "ETH"

    report2 = tax.calculate_gains("wallet2", 2024)
    assert len(report2.transactions) == 1
    assert report2.transactions[0]['asset'] == "BTC"

    # All wallets report
    report_all = tax.calculate_gains("", 2024)
    assert len(report_all.transactions) == 2

def test_report_summary(tax):
    tax.add_transaction(Transaction(
        tx_hash="0x1", chain="ethereum", timestamp="2024-01-15T10:00:00",
        tx_type="buy", asset="ETH", amount=1.0, price_usd=2500.0, wallet="w1"
    ))
    tax.add_transaction(Transaction(
        tx_hash="0x2", chain="ethereum", timestamp="2024-06-15T10:00:00",
        tx_type="sell", asset="ETH", amount=1.0, price_usd=3500.0, wallet="w1"
    ))

    report = tax.calculate_gains("w1", 2024)
    
    assert "ETH" in report.summary_by_asset
    eth_summary = report.summary_by_asset["ETH"]
    assert eth_summary['count'] == 2
    assert eth_summary['gains'] == 1000.0
    assert eth_summary['losses'] == 0.0

def test_export_csv(tax, temp_db):
    tax.add_transaction(Transaction(
        tx_hash="0x1", chain="ethereum", timestamp="2024-01-15T10:00:00",
        tx_type="buy", asset="ETH", amount=1.0, price_usd=2500.0, wallet="w1"
    ))
    tax.add_transaction(Transaction(
        tx_hash="0x2", chain="ethereum", timestamp="2024-06-15T10:00:00",
        tx_type="sell", asset="ETH", amount=1.0, price_usd=3500.0, wallet="w1"
    ))

    report = tax.calculate_gains("w1", 2024)
    
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
        output_path = f.name
    
    try:
        tax.export_report_csv(report, output_path)
        assert os.path.exists(output_path)
        
        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 2
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)