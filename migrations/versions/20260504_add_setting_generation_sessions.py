"""link setting generation sessions to main workbench migration

Revision ID: 20260504_setting_sessions
Revises: 20260502_setting_workbench
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union


revision: str = "20260504_setting_sessions"
down_revision: Union[str, Sequence[str], None] = "20260502_setting_workbench"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
