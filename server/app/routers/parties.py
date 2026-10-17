"""Watch parties: create, schedule, invite, RSVP, chat history, and the live WebSocket."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session, sessionmaker
from ..models import MediaItem, PartyMember, PartyMessage, Series, User, WatchParty, utcnow
from ..schemas import ChatOut, InviteIn, PartyIn, PartyMemberOut, PartyOut, PartyUpdateIn, RsvpIn
from ..security import current_user, decode_token, session_cookie
from ..services.events import audit, notify
from ..services.party_rooms import MAX_CHAT, rooms
from .media import gate_for

MAX_SIGNAL = 64_000  # one SDP offer is a few KB


def ice_servers() -> list[dict]:
    """STUN/TURN servers for voice chat. At home and over Tailscale none are needed: devices reach
    each other directly. ZIRAHIVE_ICE_SERVERS adds some, e.g. stun:stun.l.google.com:19302."""
    from ..config import get_settings

    urls = [u.strip() for u in get_settings().ice_servers.split(",") if u.strip()]
    return [{"urls": urls}] if urls else []


router = APIRouter(prefix="/api/parties", tags=["parties"])


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def _when(dt: datetime | None) -> str:
    return "now" if dt is None else _aware(dt).strftime("%a %d %b, %H:%M UTC")


async def _media_label(session: AsyncSession, item: MediaItem) -> tuple[str, str | None]:
    if item.series_id:
        series = await session.get(Series, item.series_id)
        code = f"S{item.season or 1} E{item.episode}" if item.episode is not None else ""
        return f"{series.title} {code}".strip() if series else item.title, series.title if series else None
    return item.title, None


async def _can_watch(session: AsyncSession, user: User, item: MediaItem) -> bool:
    return (await gate_for(session, user)).ok_item(item)


async def _get_party(session: AsyncSession, party_id: str, user: User) -> tuple[WatchParty, PartyMember | None]:
    party = await session.get(WatchParty, party_id)
    if party is None:
        raise HTTPException(404, "Watch party not found")
    member = await session.scalar(select(PartyMember).where(
        PartyMember.party_id == party.id, PartyMember.user_id == user.id))
    if party.host_id != user.id and member is None:
        raise HTTPException(404, "Watch party not found")
    return party, member


async def _out(session: AsyncSession, party: WatchParty, user: User) -> PartyOut:
    item = await session.get(MediaItem, party.media_id)
    host = await session.get(User, party.host_id)
    label, series_title = await _media_label(session, item) if item else ("(removed)", None)
    online = rooms.online(party.id)
    rows = (await session.execute(select(PartyMember, User.username).join(User, User.id == PartyMember.user_id)
                                  .where(PartyMember.party_id == party.id).order_by(User.username))).all()
    members = [PartyMemberOut(user_id=m.user_id, username=name, rsvp=m.rsvp, online=m.user_id in online)
               for m, name in rows]
    mine = next((m.rsvp for m in members if m.user_id == user.id), None)
    return PartyOut(id=party.id, title=party.title, host_id=party.host_id, host=host.username if host else "?",
                    is_host=party.host_id == user.id, media_id=party.media_id, media_title=label,
                    series_title=series_title, poster_ready=bool(item and item.poster_ready),
                    scheduled_at=party.scheduled_at, control=party.control, wait_for_all=party.wait_for_all,
                    ended_at=party.ended_at, created_at=party.created_at, my_rsvp=mine, members=members,
                    online=len(online))


async def _invite(session: AsyncSession, party: WatchParty, host: User, item: MediaItem,
                  user_ids: list[str]) -> list[str]:
    """Adds members; returns the names of people the title isn't suitable for."""
    too_young = []
    existing = set((await session.scalars(select(PartyMember.user_id).where(
        PartyMember.party_id == party.id))).all())
    for uid in dict.fromkeys(user_ids):
        if uid == host.id or uid in existing:
            continue
        person = await session.get(User, uid)
        if person is None:
            raise HTTPException(400, "Unknown person")
        if not await _can_watch(session, person, item):
            too_young.append(person.username)
            continue
        session.add(PartyMember(party_id=party.id, user_id=uid))
        when = "now" if party.scheduled_at is None else _when(party.scheduled_at)
        await notify(session, person, "party", f"{host.username} invited you to watch {party.title}",
                     f"Starts {when}.", link=f"/party/{party.id}")
    return too_young


# --------------------------------------------------------------------- REST

@router.post("", response_model=PartyOut, status_code=201)
async def create_party(body: PartyIn, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item = await session.get(MediaItem, body.media_id)
    if item is None or item.missing or not await _can_watch(session, user, item):
        raise HTTPException(404, "Not found")
    label, _ = await _media_label(session, item)
    party = WatchParty(host_id=user.id, media_id=item.id, title=label, control=body.control,
                       wait_for_all=body.wait_for_all,
                       scheduled_at=_aware(body.scheduled_at) if body.scheduled_at else None)
    session.add(party)
    await session.flush()
    too_young = await _invite(session, party, user, item, body.invite)
    if too_young:
        await session.rollback()
        raise HTTPException(400, f"{label} isn't suitable for {', '.join(too_young)} (age limit)")
    await audit(session, "party_created", user, detail=label, request=request)
    await session.commit()
    from ..services.plugins import emit

    await emit("party.created", {"host": user.username, "title": label, "party_id": party.id,
                                 "scheduled_at": party.scheduled_at.isoformat() if party.scheduled_at else None})
    return await _out(session, party, user)


@router.get("", response_model=list[PartyOut])
async def my_parties(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Parties you host or were invited to that haven't ended, soonest first."""
    member_of = select(PartyMember.party_id).where(PartyMember.user_id == user.id)
    parties = (await session.scalars(select(WatchParty).where(
        or_(WatchParty.host_id == user.id, WatchParty.id.in_(member_of)), WatchParty.ended_at.is_(None)))).all()
    out = [await _out(session, p, user) for p in parties]
    far = datetime(9999, 1, 1, tzinfo=timezone.utc)
    return sorted(out, key=lambda p: (_aware(p.scheduled_at) or _aware(p.created_at) or far))


@router.get("/{party_id}", response_model=PartyOut)
async def get_party(party_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    party, _ = await _get_party(session, party_id, user)
    return await _out(session, party, user)


@router.get("/{party_id}/chat", response_model=list[ChatOut])
async def chat_history(party_id: str, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    party, _ = await _get_party(session, party_id, user)
    msgs = (await session.scalars(select(PartyMessage).where(PartyMessage.party_id == party.id)
                                  .order_by(PartyMessage.created_at.desc()).limit(100))).all()
    return list(reversed(msgs))


@router.patch("/{party_id}", response_model=PartyOut)
async def update_party(party_id: str, body: PartyUpdateIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    party, _ = await _get_party(session, party_id, user)
    if party.host_id != user.id:
        raise HTTPException(403, "Only the host can change the party")
    if body.clear_schedule:
        party.scheduled_at = None
    elif body.scheduled_at:
        party.scheduled_at, party.reminded_at, party.started_notice_at = _aware(body.scheduled_at), None, None
    if body.control:
        party.control = body.control
    if body.wait_for_all is not None:
        party.wait_for_all = body.wait_for_all
    room = rooms.get(party.id)
    if room:
        room.control, room.wait_for_all = party.control, party.wait_for_all
        await room.broadcast(room.state())
    await session.commit()
    return await _out(session, party, user)


@router.put("/{party_id}/rsvp", response_model=PartyOut)
async def rsvp(party_id: str, body: RsvpIn, user: User = Depends(current_user),
               session: AsyncSession = Depends(get_session)):
    party, member = await _get_party(session, party_id, user)
    if member is None:
        raise HTTPException(400, "The host doesn't need to reply")
    member.rsvp = body.rsvp
    host = await session.get(User, party.host_id)
    if host:
        verb = "is coming to" if body.rsvp == "going" else "can't make"
        await notify(session, host, "party", f"{user.username} {verb} {party.title}", link=f"/party/{party.id}")
    await session.commit()
    return await _out(session, party, user)


@router.post("/{party_id}/invite", response_model=PartyOut)
async def invite_more(party_id: str, body: InviteIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    party, _ = await _get_party(session, party_id, user)
    if party.host_id != user.id:
        raise HTTPException(403, "Only the host can invite people")
    item = await session.get(MediaItem, party.media_id)
    too_young = await _invite(session, party, user, item, body.user_ids)
    if too_young:
        await session.rollback()
        raise HTTPException(400, f"{party.title} isn't suitable for {', '.join(too_young)} (age limit)")
    await session.commit()
    return await _out(session, party, user)


@router.post("/{party_id}/end", response_model=PartyOut)
async def end_party(party_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    party, _ = await _get_party(session, party_id, user)
    if party.host_id != user.id:
        raise HTTPException(403, "Only the host can end the party")
    party.ended_at = utcnow()
    room = rooms.get(party.id)
    if room:
        party.position = room.current()
        await room.broadcast({"type": "ended", "by": user.username})
    await session.commit()
    return await _out(session, party, user)


# ---------------------------------------------------------------- reminders

async def send_reminders(session: AsyncSession) -> int:
    """Runs every minute in the worker: '10 minutes to go' and 'starting now'."""
    from datetime import timedelta
    t = utcnow()
    sent = 0
    soon = (await session.scalars(select(WatchParty).where(
        WatchParty.ended_at.is_(None), WatchParty.reminded_at.is_(None),
        WatchParty.scheduled_at > t, WatchParty.scheduled_at <= t + timedelta(minutes=10)))).all()
    starting = (await session.scalars(select(WatchParty).where(
        WatchParty.ended_at.is_(None), WatchParty.started_notice_at.is_(None),
        WatchParty.scheduled_at <= t, WatchParty.scheduled_at > t - timedelta(minutes=30)))).all()
    for party, starting_now in [(p, False) for p in soon] + [(p, True) for p in starting]:
        people = [await session.get(User, party.host_id)]
        for m in (await session.scalars(select(PartyMember).where(
                PartyMember.party_id == party.id, PartyMember.rsvp != "declined"))).all():
            people.append(await session.get(User, m.user_id))
        if starting_now:
            title, party.started_notice_at = f"{party.title} is starting now", t
        else:
            mins = max(1, round((_aware(party.scheduled_at) - t).total_seconds() / 60))
            title, party.reminded_at = f"{party.title} starts in {mins} minutes", t
        for person in filter(None, people):
            await notify(session, person, "party", title, "Join the watch party.", link=f"/party/{party.id}")
            sent += 1
    await session.commit()
    return sent


# ---------------------------------------------------------------- WebSocket

async def _ws_user(ws: WebSocket) -> User | None:
    auth = ws.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else session_cookie(ws.cookies)
    payload = decode_token(token) if token else None
    if not payload or "sub" not in payload:
        return None
    async with sessionmaker()() as session:
        user = await session.get(User, payload["sub"])
        if user is None or payload.get("v", 0) != (user.token_version or 0):
            return None
        session.expunge(user)
        return user


def _same_origin(ws: WebSocket) -> bool:
    """Browsers send Origin on WebSockets; refuse pages from other sites (cookie hijacking)."""
    origin = ws.headers.get("origin")
    return origin is None or urlparse(origin).netloc == ws.headers.get("host")


@router.websocket("/{party_id}/ws")
async def party_socket(ws: WebSocket, party_id: str):
    if ws.headers.get("x-zirahive-gateway") == "public" or not _same_origin(ws):
        await ws.close(code=4403)
        return
    user = await _ws_user(ws)
    if user is None:
        await ws.close(code=4401)
        return
    async with sessionmaker()() as session:
        party = await session.get(WatchParty, party_id)
        member = await session.scalar(select(PartyMember).where(
            PartyMember.party_id == party_id, PartyMember.user_id == user.id)) if party else None
        item = await session.get(MediaItem, party.media_id) if party else None
        allowed = party and (party.host_id == user.id or member) and item and await _can_watch(session, user, item)
        if not allowed or party.ended_at:
            await ws.close(code=4404)
            return
        room = rooms.open(party.id, party.host_id, party.media_id, party.position, party.control, party.wait_for_all)
        history = (await session.scalars(select(PartyMessage).where(PartyMessage.party_id == party.id)
                                         .order_by(PartyMessage.created_at.desc()).limit(50))).all()
    await ws.accept()

    async def send(msg: dict) -> None:
        await ws.send_text(json.dumps(msg, ensure_ascii=False))

    viewer = rooms.join(room, user.id, user.username, send)
    await send({"type": "hello", "you": user.username, "host": room.host_id == user.id, "conn": viewer.conn_id,
                "ice": ice_servers(),
                "chat": [{"id": m.id, "username": m.username, "text": m.text,
                          "created_at": _aware(m.created_at).isoformat()} for m in reversed(history)]})
    await send(room.state())
    await send(room.voice_roster())
    await room.broadcast(room.people())
    await room.broadcast({"type": "notice", "text": f"{user.username} joined"}, skip=viewer.conn_id)
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except ValueError:
                continue
            await _handle(room, viewer, user, msg, send)
    except WebSocketDisconnect:
        pass
    finally:
        closed = rooms.leave(room, viewer)
        # saved in the background: a disconnect shouldn't wait on the database
        _background(_save_position(room))
        if not closed:
            if viewer.buffering:
                room.set_buffering(viewer, False)
            if viewer.voice:
                await room.broadcast(room.voice_roster())
            await room.broadcast(room.people())
            await room.broadcast({"type": "notice", "text": f"{user.username} left"})
            await room.broadcast(room.state())


_tasks: set = set()


def _background(coro) -> None:
    import asyncio
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _save_position(room) -> None:
    async with sessionmaker()() as session:
        party = await session.get(WatchParty, room.party_id)
        if party:
            party.position, party.media_id = room.current(), room.media_id
            await session.commit()


async def _handle(room, viewer, user: User, msg: dict, send) -> None:
    kind = msg.get("type")
    if kind == "ping":
        from ..services.party_rooms import now
        await send({"type": "pong", "t0": msg.get("t0"), "server": now()})
        return
    if kind == "report":
        try:
            viewer.position = float(msg.get("position", 0))
        except (TypeError, ValueError):
            pass
        return
    if kind in ("play", "pause", "seek"):
        if not room.may_control(user.id):
            await send({"type": "notice", "text": "Only the host controls playback in this party"})
            await send(room.state())
            return
        try:
            position = float(msg.get("position", room.current()))
        except (TypeError, ValueError):
            return
        async with room.lock:
            if kind == "play":
                room.play(position)
            elif kind == "pause":
                room.pause(position)
            else:
                room.seek(position)
        await room.broadcast(room.state(by=user.username))
        if kind != "play":
            await _save_position(room)
        return
    if kind == "buffering":
        async with room.lock:
            change = room.set_buffering(viewer, bool(msg.get("state")))
        if change:
            await room.broadcast(room.state())
        await room.broadcast(room.people())
        return
    if kind == "chat":
        text = str(msg.get("text", "")).strip()[:MAX_CHAT]
        if not text:
            return
        async with sessionmaker()() as session:
            m = PartyMessage(party_id=room.party_id, user_id=user.id, username=user.username, text=text)
            session.add(m)
            await session.commit()
            await room.broadcast({"type": "chat", "id": m.id, "username": user.username, "text": text,
                                  "created_at": _aware(m.created_at).isoformat()})
        return
    if kind == "voice":  # join, leave or mute the voice chat
        viewer.voice = bool(msg.get("join"))
        viewer.muted = bool(msg.get("muted")) if viewer.voice else False
        await room.broadcast(room.voice_roster())
        await room.broadcast(room.people())
        return
    if kind == "signal":  # WebRTC set-up between two people in the voice chat, passed along as is
        target = room.viewers.get(str(msg.get("to", "")))
        data = msg.get("data")
        if (target is None or not viewer.voice or not target.voice or not isinstance(data, dict)
                or len(json.dumps(data)) > MAX_SIGNAL or not room.allow_signal(viewer)):
            return
        try:
            await target.send({"type": "signal", "from": viewer.conn_id, "username": user.username, "data": data})
        except Exception:  # that device just left
            pass
        return
    if kind == "react":
        emoji = str(msg.get("emoji", ""))
        if room.allow_reaction(viewer, emoji):
            await room.broadcast({"type": "react", "username": user.username, "emoji": emoji})
        return
    if kind == "media":
        if user.id != room.host_id:
            return
        async with sessionmaker()() as session:
            item = await session.get(MediaItem, str(msg.get("media_id", "")))
            if item is None or item.missing:
                return
            # everyone in the room must be allowed to watch it
            for v in room.viewers.values():
                person = await session.get(User, v.user_id)
                if not await _can_watch(session, person, item):
                    await send({"type": "notice", "text": f"That title isn't suitable for {person.username}"})
                    return
            label, _ = await _media_label(session, item)
            party = await session.get(WatchParty, room.party_id)
            party.media_id, party.title, party.position = item.id, label, 0
            await session.commit()
        room.change_media(item.id)
        await room.broadcast(room.state(by=user.username))
        await room.broadcast({"type": "notice", "text": f"{user.username} started {label}"})
