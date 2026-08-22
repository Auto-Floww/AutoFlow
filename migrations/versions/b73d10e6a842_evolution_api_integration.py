"""migrate WhatsApp integration from Meta identifiers to Evolution instances

Revision ID: b73d10e6a842
Revises: 6973a8314ce3
Create Date: 2026-08-21 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b73d10e6a842"
down_revision: Union[str, None] = "6973a8314ce3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("whatsapp_integrations") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("instance_name", sa.String(length=100), nullable=True))

    op.execute(
        sa.text(
            "UPDATE whatsapp_integrations "
            "SET instance_name = phone_number_id, display_name = display_phone_number "
            "WHERE instance_name IS NULL"
        )
    )

    with op.batch_alter_table("whatsapp_integrations") as batch_op:
        batch_op.alter_column(
            "instance_name",
            existing_type=sa.String(length=100),
            nullable=False,
        )
        batch_op.drop_index(op.f("ix_whatsapp_integrations_business_account_id"))
        batch_op.drop_index(op.f("ix_whatsapp_integrations_phone_number_id"))
        batch_op.create_index(
            op.f("ix_whatsapp_integrations_instance_name"),
            ["instance_name"],
            unique=True,
        )
        batch_op.drop_column("metadata")
        batch_op.drop_column("app_secret_encrypted")
        batch_op.drop_column("access_token_encrypted")
        batch_op.drop_column("business_account_id")
        batch_op.drop_column("phone_number_id")
        batch_op.drop_column("display_phone_number")


def downgrade() -> None:
    with op.batch_alter_table("whatsapp_integrations") as batch_op:
        batch_op.add_column(sa.Column("display_phone_number", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("phone_number_id", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("business_account_id", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("access_token_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("app_secret_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    op.execute(
        sa.text(
            "UPDATE whatsapp_integrations "
            "SET phone_number_id = instance_name, display_phone_number = display_name "
            "WHERE phone_number_id IS NULL"
        )
    )

    with op.batch_alter_table("whatsapp_integrations") as batch_op:
        batch_op.alter_column(
            "phone_number_id",
            existing_type=sa.String(length=100),
            nullable=False,
        )
        batch_op.drop_index(op.f("ix_whatsapp_integrations_instance_name"))
        batch_op.create_index(
            op.f("ix_whatsapp_integrations_phone_number_id"),
            ["phone_number_id"],
            unique=True,
        )
        batch_op.create_index(
            op.f("ix_whatsapp_integrations_business_account_id"),
            ["business_account_id"],
            unique=False,
        )
        batch_op.drop_column("instance_name")
        batch_op.drop_column("display_name")
