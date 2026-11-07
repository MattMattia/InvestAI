"""001_initial_schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-24 18:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------
    # Nivel 0 (Raíces sin Foreign Keys)
    # ---------------------------------------------------------

    # 1. Table: users
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=100), server_default='InvestAI User', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('role', sa.Enum('VIEWER', 'TRADER', 'ADMIN', name='userrole', native_enum=False, length=20), server_default='VIEWER', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('investor_profile', sa.String(length=50), server_default='MODERATE', nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # 2. Table: assets
    op.create_table(
        'assets',
        sa.Column('ticker', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('asset_type', sa.String(length=50), nullable=False),
        sa.Column('currency', sa.String(length=10), server_default='ARS', nullable=False),
        sa.Column('sector', sa.String(length=100), server_default='OTHER', nullable=False),
        sa.Column('market', sa.String(length=50), server_default='BYMA', nullable=False),
        sa.Column('cedear_ratio', sa.Float(), nullable=True),
        sa.Column('underlying_ticker', sa.String(length=30), nullable=True),
        sa.Column('history_start_date', sa.String(length=20), server_default='2016-11-01', nullable=True),
        sa.Column('history_years_available', sa.Float(), server_default='10.0', nullable=False),
        sa.Column('data_points_count', sa.Integer(), server_default='2520', nullable=False),
        sa.Column('cagr_annualized', sa.Float(), server_default='0.12', nullable=False),
        sa.Column('volatility_annualized', sa.Float(), server_default='0.25', nullable=False),
        sa.Column('sharpe_ratio', sa.Float(), server_default='0.48', nullable=False),
        sa.Column('sortino_ratio', sa.Float(), server_default='0.68', nullable=False),
        sa.Column('max_drawdown', sa.Float(), server_default='0.28', nullable=False),
        sa.Column('beta_market', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('var_95_daily', sa.Float(), server_default='0.026', nullable=False),
        sa.Column('pe_ratio', sa.Float(), nullable=True),
        sa.Column('pb_ratio', sa.Float(), nullable=True),
        sa.Column('roe_pct', sa.Float(), nullable=True),
        sa.Column('debt_to_equity', sa.Float(), nullable=True),
        sa.Column('dividend_yield_pct', sa.Float(), nullable=True),
        sa.Column('market_cap_usd', sa.Float(), nullable=True),
        sa.Column('ytm_tir_pct', sa.Float(), nullable=True),
        sa.Column('modified_duration', sa.Float(), nullable=True),
        sa.Column('parity_pct', sa.Float(), nullable=True),
        sa.Column('metrics_payload', sa.JSON(), nullable=True),
        sa.Column('metrics_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('ticker', name=op.f('pk_assets')),
    )
    op.create_index(op.f('ix_assets_ticker'), 'assets', ['ticker'], unique=False)

    # ---------------------------------------------------------
    # Nivel 1 (Dependientes de Nivel 0)
    # ---------------------------------------------------------

    # 3. Table: portfolios
    op.create_table(
        'portfolios',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), server_default='Portafolio Principal', nullable=False),
        sa.Column('investor_profile', sa.String(length=50), server_default='MODERATE', nullable=False),
        sa.Column('cash_balance_ars', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('cash_balance_usd', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_portfolios_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_portfolios')),
    )
    op.create_index(op.f('ix_portfolios_user_id'), 'portfolios', ['user_id'], unique=False)

    # 4. Table: market_bars
    op.create_table(
        'market_bars',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('ticker', sa.String(length=30), nullable=False),
        sa.Column('timeframe', sa.String(length=10), server_default='1d', nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open_price', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('high_price', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('low_price', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('close_price', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('volume', sa.Numeric(precision=24, scale=4), server_default='0', nullable=False),
        sa.Column('vwap', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_market_bars')),
        sa.UniqueConstraint('ticker', 'timeframe', 'timestamp', name='uq_market_bar_ticker_tf_timestamp'),
    )
    op.create_index(op.f('ix_market_bars_ticker'), 'market_bars', ['ticker'], unique=False)
    op.create_index(op.f('ix_market_bars_timestamp'), 'market_bars', ['timestamp'], unique=False)

    # ---------------------------------------------------------
    # Nivel 2 (Dependientes de Nivel 1 y 0)
    # ---------------------------------------------------------

    # 5. Table: holdings
    op.create_table(
        'holdings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('portfolio_id', sa.String(length=36), nullable=False),
        sa.Column('asset_ticker', sa.String(length=30), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('average_buy_price', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('current_price', sa.Float(), server_default='0.0', nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], name=op.f('fk_holdings_portfolio_id_portfolios'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asset_ticker'], ['assets.ticker'], name=op.f('fk_holdings_asset_ticker_assets'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_holdings')),
    )
    op.create_index(op.f('ix_holdings_portfolio_id'), 'holdings', ['portfolio_id'], unique=False)
    op.create_index(op.f('ix_holdings_asset_ticker'), 'holdings', ['asset_ticker'], unique=False)

    # 6. Table: rebalance_orders
    op.create_table(
        'rebalance_orders',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('portfolio_id', sa.String(length=36), nullable=False),
        sa.Column('ticker', sa.String(length=30), nullable=False),
        sa.Column('side', sa.String(length=10), nullable=False),
        sa.Column('current_weight', sa.Float(), nullable=False),
        sa.Column('target_weight', sa.Float(), nullable=False),
        sa.Column('delta_amount', sa.Float(), nullable=False),
        sa.Column('estimated_shares', sa.Integer(), nullable=False),
        sa.Column('price_used', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=30), server_default='PENDING', nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], name=op.f('fk_rebalance_orders_portfolio_id_portfolios'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rebalance_orders')),
    )
    op.create_index(op.f('ix_rebalance_orders_portfolio_id'), 'rebalance_orders', ['portfolio_id'], unique=False)

    # 7. Table: risk_audit_snapshots
    op.create_table(
        'risk_audit_snapshots',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('portfolio_id', sa.String(length=36), nullable=False),
        sa.Column('compliance_status', sa.String(length=50), nullable=False),
        sa.Column('total_rules_evaluated', sa.Integer(), server_default='0', nullable=False),
        sa.Column('critical_alerts_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column(
            'report_payload',
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False,
        ),
        sa.Column('notification_status', sa.String(length=50), server_default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], name=op.f('fk_risk_audit_snapshots_portfolio_id_portfolios'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_audit_snapshots')),
    )
    op.create_index(op.f('ix_risk_audit_snapshots_portfolio_id'), 'risk_audit_snapshots', ['portfolio_id'], unique=False)


def downgrade() -> None:
    # ---------------------------------------------------------
    # Nivel 2 (Dependientes de Nivel 1 y 0)
    # ---------------------------------------------------------
    op.drop_index(op.f('ix_risk_audit_snapshots_portfolio_id'), table_name='risk_audit_snapshots')
    op.drop_table('risk_audit_snapshots')

    op.drop_index(op.f('ix_rebalance_orders_portfolio_id'), table_name='rebalance_orders')
    op.drop_table('rebalance_orders')

    op.drop_index(op.f('ix_holdings_asset_ticker'), table_name='holdings')
    op.drop_index(op.f('ix_holdings_portfolio_id'), table_name='holdings')
    op.drop_table('holdings')

    # ---------------------------------------------------------
    # Nivel 1 (Dependientes de Nivel 0)
    # ---------------------------------------------------------
    op.drop_index(op.f('ix_market_bars_timestamp'), table_name='market_bars')
    op.drop_index(op.f('ix_market_bars_ticker'), table_name='market_bars')
    op.drop_table('market_bars')

    op.drop_index(op.f('ix_portfolios_user_id'), table_name='portfolios')
    op.drop_table('portfolios')

    # ---------------------------------------------------------
    # Nivel 0 (Raíces sin Foreign Keys)
    # ---------------------------------------------------------
    op.drop_index(op.f('ix_assets_ticker'), table_name='assets')
    op.drop_table('assets')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
