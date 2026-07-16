# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import Client

from anony import config, logger


class Userbot:
    """Manage an unlimited set of assistant sessions in stable numeric slots."""

    def __init__(self) -> None:
        self.clients: dict[int, Client] = {}

    async def _start_client(
        self,
        slot: int,
        session_string: str,
        attach_calls: bool,
    ) -> Client:
        if slot in self.clients:
            return self.clients[slot]

        client = Client(
            name=f"AnonyUB{slot}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=session_string,
        )
        await client.start()
        client.id = client.me.id
        client.name = client.me.first_name
        client.username = client.me.username
        client.mention = client.me.mention

        duplicate = next(
            (
                active_slot
                for active_slot, active in self.clients.items()
                if active.id == client.id
            ),
            None,
        )
        if duplicate is not None:
            await client.stop()
            raise ValueError(
                f"This account is already active in session {duplicate}."
            )

        from anony import db

        # Persist the verified identity before voice attachment. If the voice
        # layer fails, the account remains manageable and can be retried.
        await db.update_assistant_session(
            slot,
            enabled=False,
            user_id=client.id,
            username=client.username or "",
            display_name=client.name or "",
        )

        self.clients[slot] = client
        try:
            if attach_calls:
                from anony import anon

                await anon.add_client(slot, client)
        except Exception:
            self.clients.pop(slot, None)
            await client.stop()
            raise

        await db.update_assistant_session(
            slot,
            enabled=True,
            user_id=client.id,
            username=client.username or "",
            display_name=client.name or "",
        )
        logger.info("Assistant session %s started as @%s", slot, client.username)
        return client

    async def boot(self) -> None:
        from anony import db

        for session_string in config.SESSIONS:
            await db.ensure_assistant_session(session_string, source="environment")

        sessions = await db.get_assistant_sessions()
        if not sessions:
            logger.warning(
                "No assistant session is configured; continuing in bot-only mode."
            )
            return

        for session in sessions:
            if not session["enabled"]:
                continue
            try:
                await self._start_client(
                    session["slot"],
                    session["session_string"],
                    attach_calls=False,
                )
            except Exception:
                logger.exception(
                    "Assistant session %s could not start", session["slot"]
                )
                await db.update_assistant_session(session["slot"], enabled=False)

        if not self.clients:
            logger.warning(
                "No assistant session could be started; continuing in bot-only mode."
            )
            return
        logger.info("Started %s assistant session(s).", len(self.clients))

    async def add_session(
        self,
        session_string: str,
        *,
        keep_on_failure: bool = False,
    ) -> tuple[int, Client]:
        from anony import db

        slot = await db.ensure_assistant_session(session_string, source="runtime")
        session = await db.get_assistant_session(slot)
        if slot in self.clients:
            return slot, self.clients[slot]
        try:
            client = await self._start_client(
                slot,
                session["session_string"],
                attach_calls=True,
            )
        except Exception:
            await db.update_assistant_session(slot, enabled=False)
            if session["source"] == "runtime" and not keep_on_failure:
                mapping = await db.delete_assistant_session(slot)
                self._apply_slot_mapping(mapping)
            raise
        return slot, client

    async def enable_session(self, slot: int) -> Client:
        from anony import db

        session = await db.get_assistant_session(slot)
        if not session:
            raise KeyError(slot)
        return await self._start_client(
            slot,
            session["session_string"],
            attach_calls=True,
        )

    async def _stop_session(self, slot: int) -> None:
        from anony import anon

        voice_client = anon.clients.pop(slot, None)
        if voice_client:
            try:
                await voice_client.stop()
            except Exception:
                logger.warning(
                    "Voice client for assistant session %s did not stop cleanly",
                    slot,
                    exc_info=True,
                )
        client = self.clients.pop(slot, None)
        if client:
            await client.stop()

    def _apply_slot_mapping(self, mapping: dict[int, int]) -> None:
        if not mapping:
            return
        from anony import anon

        self.clients = {
            mapping.get(slot, slot): client
            for slot, client in self.clients.items()
        }
        anon.clients = {
            mapping.get(slot, slot): client
            for slot, client in anon.clients.items()
        }

    async def disable_session(self, slot: int, delete: bool = False) -> None:
        from anony import db

        session = await db.get_assistant_session(slot)
        if not session:
            raise KeyError(slot)
        active_chats = db.active_chats_for_assistant(slot)
        if active_chats:
            raise RuntimeError(
                "Session is currently playing in: "
                + ", ".join(map(str, active_chats))
            )
        await self._stop_session(slot)
        if delete:
            mapping = await db.delete_assistant_session(slot)
            self._apply_slot_mapping(mapping)
        else:
            await db.release_assistant_slot(slot)
            await db.update_assistant_session(slot, enabled=False)

    async def restart_session(self, slot: int) -> Client:
        from anony import db

        session = await db.get_assistant_session(slot)
        if not session:
            raise KeyError(slot)
        active_chats = db.active_chats_for_assistant(slot)
        if active_chats:
            raise RuntimeError(
                "Session is currently playing in: "
                + ", ".join(map(str, active_chats))
            )
        await self._stop_session(slot)
        return await self._start_client(
            slot,
            session["session_string"],
            attach_calls=True,
        )

    async def exit(self) -> None:
        for slot in list(self.clients):
            client = self.clients.pop(slot)
            try:
                await client.stop()
            except Exception:
                logger.warning(
                    "Assistant session %s did not stop cleanly",
                    slot,
                    exc_info=True,
                )
        logger.info("Assistants stopped.")
