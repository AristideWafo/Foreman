"""Hachage argon2id, exécuté hors de la boucle asynchrone (CPU)."""

import asyncio

from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2Hasher:
    def __init__(self) -> None:
        self._argon = Argon2()  # argon2id par défaut
        self._dummy: str | None = None

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._argon.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        return await asyncio.to_thread(self._verify, password_hash, password)

    def _verify(self, password_hash: str | None, password: str) -> bool:
        if password_hash is None:
            # Même travail qu'un vrai refus : le temps ne révèle pas si l'e-mail existe.
            self._dummy = self._dummy or self._argon.hash("dummy-password-for-timing")
            password_hash = self._dummy
            password = password + "x"
        try:
            return self._argon.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
