"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-24 18:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Table: users
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('investor_profile', sa.String(length=50), nullable=False, server_default='MODERATE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # 2. Table: assets
    op.create_table(
        'assets',
        sa.Column('ticker', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('asset_type', sa.String(length=50), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='ARS'),
        sa.Column('sector', sa.String(length=100), nullable=False, server_default='OTHER'),
        sa.Column('market', sa.String(length=50), nullable=False, server_default='BYMA'),
        sa.Column('cedear_ratio', sa.Float(), nullable=True),
        sa.Column('underlying_ticker', sa.String(length=30), nullable=True),
        sa.PrimaryKeyConstraint('ticker'),
    )
    op.create_index(op.f('ix_assets_ticker'), 'assets', ['ticker'], unique=False)

    # 3. Table: portfolios
    op.create_table(
        'portfolios',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, server_default='Portafolio Principal'),
        sa.Column('investor_profile', sa.String(length=50), nullable=False, server_default='MODERATE'),
        sa.Column('cash_balance_ars', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('cash_balance_usd', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_portfolios_user_id'), 'portfolios', ['user_id'], unique=False)

    # 4. Table: holdings
    op.create_table(
        'holdings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('portfolio_id', sa.String(length=36), nullable=False),
        sa.Column('asset_ticker', sa.String(length=30), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('average_buy_price', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('current_price', sa.Float(), nullable=False, server_default='0.0'),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asset_ticker'], ['assets.ticker'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_holdings_portfolio_id'), 'holdings', ['portfolio_id'], unique=False)
    op.create_index(op.f('ix_holdings_asset_ticker'), 'holdings', ['asset_ticker'], unique=False)

    # 5. Table: risk_audit_snapshots
    op.create_table(
        'risk_audit_snapshots',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('portfolio_id', sa.String(length=36), nullable=False),
        sa.Column('compliance_status', sa.String(length=50), nullable=False),
        sa.Column('total_rules_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('critical_alerts_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('report_payload', sa.JSON(), nullable=False),
        sa.Column('notification_status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_risk_audit_snapshots_portfolio_id'), 'risk_audit_snapshots', ['portfolio_id'], unique=False)

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
        sa.Column('status', sa.String(length=30), nullable=False, server_default='PENDING'),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rebalance_orders_portfolio_id'), 'rebalance_orders', ['portfolio_id'], unique=False)


def downgrade() -> None:
    op.drop_table('rebalance_orders')
    op.drop_table('risk_audit_snapshots')
    op.drop_table('holdings')
    op.drop_table('portfolios')
    op.drop_table('assets')
    op.drop_table('users')
