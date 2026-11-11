from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from .base import Base
from core.security import encrypt_token, decrypt_token, token_hash, is_encrypted


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    # Stored encrypted ("enc:..."). Assign the plain token; it is encrypted on assignment.
    token: Mapped[str] = mapped_column(
        String(512),
        unique=True,
        index=True,
        nullable=False
    )

    # Keyed hash of the plain token, used for lookups (see core.security.token_hash).
    token_hash: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    webhook_url: Mapped[str] = mapped_column(
        String(500),
        nullable=True
    )

    webhook_set: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    # "standard" (menus/buttons) or "cinema" (movie catalogue managed from inside the bot)
    kind: Mapped[str] = mapped_column(
        String(20), default="standard", server_default="standard", nullable=False
    )

    # Relationship
    owner = relationship("User", backref="bots")

    @validates("token")
    def _encrypt_on_assign(self, _key, value: str) -> str:
        if is_encrypted(value):
            return value
        self.token_hash = token_hash(value)
        return encrypt_token(value)

    @property
    def plain_token(self) -> str:
        """Decrypted Telegram token. Only use it to call the Telegram API."""
        return decrypt_token(self.token)

    @staticmethod
    def token_matches(plain_token: str):
        """SQL filter matching a bot by plain token.

        Only the keyed hash is sent to the database, never the token itself, so a token cannot
        appear in SQL logs (e.g. with DEBUG echo on). Every row has a hash: protect_bot_tokens()
        encrypts legacy plaintext rows and fills token_hash on startup.
        """
        return Bot.token_hash == token_hash(plain_token)
