# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import Client

from anony import config, logger


class Userbot:
    """Manage an unlimited set of assistant sessions in stable numeric slots."""

    def __init__(self) -> None:
        self.clients: dict[int, Client] = {}
        self.locked: set[int] = set()

    @property
    def accepting_slots(self) -> set[int]:
        """Connected sessions that may accept new playback."""
        return set(self.clients).difference(self.locked)

    def is_accepting(self, slot: int | None) -> bool:
        return slot is not None and slot in self.clients and slot not in self.locked

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
        self.locked.discard(slot)
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
        current = self.clients.get(slot)
        if current is not None:
            from anony import anon

            if slot not in anon.clients:
                await anon.add_client(slot, current)
            await db.update_assistant_session(slot, enabled=True)
            self.locked.discard(slot)
            logger.info("Assistant session %s unlocked", slot)
            return current
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
        self.locked.discard(slot)

    def _apply_slot_mapping(self, mapping: dict[int, int]) -> None:
        if not mapping:
            return
        from anony import anon

        self.clients = {
            mapping.get(slot, slot): client
            for slot, client in self.clients.items()
        }
        self.locked = {
            mapping.get(slot, slot)
            for slot in self.locked
            if mapping.get(slot, slot) in self.clients
        }
        remap_workers = getattr(anon, "remap_slots", None)
        if remap_workers is not None:
            remap_workers(mapping)
        else:
            anon.clients = {
                mapping.get(slot, slot): client
                for slot, client in anon.clients.items()
            }

    async def disable_session(self, slot: int, delete: bool = False) -> bool:
        """Disable immediately, draining existing calls when necessary.

        Returns True when current calls are still finishing.
        """
        from anony import db

        session = await db.get_assistant_session(slot)
        if not session:
            raise KeyError(slot)
        active_chats = db.active_chats_for_assistant(slot)
        if delete and active_chats:
            raise RuntimeError(
                "Disable this session first. Its current calls must finish "
                "before it can be removed."
            )

        if delete:
            await self._stop_session(slot)
            mapping = await db.delete_assistant_session(slot)
            self._apply_slot_mapping(mapping)
            return False

        # Lock before the database write yields so no concurrent /play request
        # can select this session during the transition.
        self.locked.add(slot)
        try:
            await db.update_assistant_session(slot, enabled=False)
        except Exception:
            self.locked.discard(slot)
            raise

        if active_chats:
            logger.info(
                "Assistant session %s locked; draining %s active call(s)",
                slot,
                len(active_chats),
            )
            return True

        await self._stop_session(slot)
        await db.release_assistant_slot(slot)
        logger.info("Assistant session %s disabled", slot)
        return False

    async def finish_draining(self, slot: int) -> bool:
        """Disconnect a locked session after its final call has ended."""
        from anony import db

        session = await db.get_assistant_session(slot)
        if (
            not session
            or session["enabled"]
            or db.active_chats_for_assistant(slot)
        ):
            return False
        await self._stop_session(slot)
        await db.release_assistant_slot(slot)
        logger.info("Assistant session %s finished draining and disconnected", slot)
        return True

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
