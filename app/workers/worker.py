"""ARQ worker (CLAUDE.md §2, §5): heartbeat, mail sync — IDLE watcher on INBOX per mailbox and a poll of the other
subscribed folders every MAIL_POLL_SECONDS (default 2 min).

Run: arq app.workers.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

import structlog
from arq import cron, func
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.mail.idle import InboxWatcher
from app.mail.models import Mailbox
from app.mail.sync import Scope, credentials_for, mark_auth_failed, server_of, sync_mailbox

log = structlog.get_logger(__name__)
HEARTBEAT_KEY = "smartmail:worker:heartbeat"
LAST_POLL_KEY = "smartmail:worker:mail-poll"


async def heartbeat(ctx: dict[str, Any]) -> str:
    now = datetime.now(UTC).isoformat()
    await ctx["redis"].set(HEARTBEAT_KEY, now, ex=300)
    return now


async def sync_mailbox_job(ctx: dict[str, Any], mailbox_id: str, scope: Scope = "all") -> str:
    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as db:
        mailbox = await db.get(Mailbox, uuid.UUID(mailbox_id))
        if mailbox is None:
            return "missing"
        return await sync_mailbox(db, mailbox, settings, scope=scope, redis=ctx["redis"])


async def process_mailbox_ai_job(ctx: dict[str, Any], mailbox_id: str) -> dict[str, int]:
    """AI pipeline: eligibility + Message-ID idempotency, classify (2b), then reply suggestions (2c)."""
    from app.ai.conformity_suggest import suggest_conformity
    from app.ai.service import daily_spend_usd, process_mailbox_ai, shadow_mode_enabled, suggest_replies_for_mailbox

    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as db:
        mailbox = await db.get(Mailbox, uuid.UUID(mailbox_id))
        if mailbox is None:
            return {"seen": 0}
        stats = await process_mailbox_ai(db, mailbox, settings)
        await db.commit()
        replies = await suggest_replies_for_mailbox(db, mailbox, settings)
        await db.commit()
        # #139 part C: an atest 2.1 request also gets a prefilled „Prehlásenie o zhode“ card (never issued by AI)
        conformity = await suggest_conformity(
            db, mailbox, settings, spent_usd=await daily_spend_usd(db), shadow=await shadow_mode_enabled(db)
        )
        await db.commit()
        return {
            **stats,
            **{f"reply_{k}": v for k, v in replies.items()},
            **{f"conformity_{k}": v for k, v in conformity.items()},
        }


async def send_compose_draft(ctx: dict[str, Any], draft_id: str) -> str:
    """Finish a queued send after the undo window (Phase 1e)."""
    from app.mail.compose import execute_send

    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as db:
        return await execute_send(db, settings, uuid.UUID(draft_id))


async def flush_scheduled_sends(ctx: dict[str, Any]) -> int:
    """W4c: enqueue drafts whose scheduled_at has passed (every minute)."""
    from app.mail.compose_models import ComposeDraft

    now = datetime.now(UTC)
    async with ctx["sessionmaker"]() as db:
        rows = await db.execute(
            select(ComposeDraft).where(
                ComposeDraft.status == "scheduled",
                ComposeDraft.scheduled_at.is_not(None),
                ComposeDraft.scheduled_at <= now,
            )
        )
        drafts = list(rows.scalars())
        for draft in drafts:
            draft.status = "queued"
            draft.undo_until = None
            await db.flush()
            await ctx["redis"].enqueue_job(
                "send_compose_draft",
                str(draft.id),
                _job_id=f"compose-scheduled:{draft.id}",
            )
        if drafts:
            await db.commit()
        return len(drafts)


async def rescan_clamav_attachments(ctx: dict[str, Any]) -> dict[str, int]:
    """Every 15 min: re-scan attachments left skipped/error while ClamAV was down."""
    from app.mail.av_rescan import rescan_pending_attachments

    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as db:
        return await rescan_pending_attachments(db, settings)


async def reparse_attachment_messages(ctx: dict[str, Any]) -> dict[str, int]:
    """One-shot / cron: re-parse stored raw for has_attachments after B9/B10 parse fixes."""
    from app.mail.reparse import reparse_messages_with_attachments

    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as db:
        return await reparse_messages_with_attachments(db, settings)


async def _syncable(ctx: dict[str, Any]) -> list[Mailbox]:
    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as db:
        rows = await db.execute(select(Mailbox).where(Mailbox.sync_state != "auth_failed"))
        return [m for m in rows.scalars() if settings.sync_host_allowed(m.imap_host)]


async def poll_mailboxes(ctx: dict[str, Any]) -> int:
    """Every minute: keep one IDLE watcher per mailbox; every MAIL_POLL_SECONDS: sync the other folders (and INBOX
    too where no watcher runs)."""
    settings: Settings = ctx["settings"]
    if not settings.mail_sync_enabled:
        return 0
    mailboxes = await _syncable(ctx)
    await ensure_watchers(ctx, mailboxes)
    now = datetime.now(UTC).timestamp()
    last = await ctx["redis"].get(LAST_POLL_KEY)
    if last is not None and now - float(last) < settings.mail_poll_seconds - 5:
        return 0
    await ctx["redis"].set(LAST_POLL_KEY, str(now), ex=settings.mail_poll_seconds * 3)
    watchers: dict[str, InboxWatcher] = ctx["watchers"]
    for mailbox in mailboxes:
        watcher = watchers.get(str(mailbox.id))
        scope: Scope = "others" if watcher is not None and watcher.alive else "all"
        await ctx["redis"].enqueue_job(
            "sync_mailbox_job", str(mailbox.id), scope, _job_id=f"mail-sync:{mailbox.id}:{scope}"
        )
    return len(mailboxes)


async def ensure_watchers(ctx: dict[str, Any], mailboxes: list[Mailbox]) -> None:
    settings: Settings = ctx["settings"]
    watchers: dict[str, InboxWatcher] = ctx["watchers"]
    wanted = {str(m.id): m for m in mailboxes}
    for mailbox_id in list(watchers):
        if mailbox_id not in wanted or not watchers[mailbox_id].alive:
            watchers.pop(mailbox_id).stop()
    loop = asyncio.get_running_loop()
    for mailbox_id, mailbox in wanted.items():
        if mailbox_id in watchers:
            continue
        async with ctx["sessionmaker"]() as db:
            creds = await credentials_for(db, mailbox, settings)
        if creds is None:
            continue

        def on_change(mid: str = mailbox_id) -> None:
            asyncio.run_coroutine_threadsafe(
                ctx["redis"].enqueue_job("sync_mailbox_job", mid, "inbox", _job_id=f"mail-sync:{mid}:inbox"), loop
            )

        def on_auth_failed(mid: str = mailbox_id) -> None:
            asyncio.run_coroutine_threadsafe(_auth_failed(ctx, mid), loop)

        watcher = InboxWatcher(
            mailbox_id,
            server_of(mailbox, settings),
            creds,
            on_change=on_change,
            on_auth_failed=on_auth_failed,
            renew_s=settings.mail_idle_renew_seconds,
        )
        watcher.start()
        watchers[mailbox_id] = watcher


async def _auth_failed(ctx: dict[str, Any], mailbox_id: str) -> None:
    async with ctx["sessionmaker"]() as db:
        mailbox = await db.get(Mailbox, uuid.UUID(mailbox_id))
        if mailbox is not None and mailbox.sync_state != "auth_failed":
            await mark_auth_failed(db, mailbox, now=datetime.now(UTC))
            await db.commit()


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["settings"] = settings
    ctx["engine"] = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["sessionmaker"] = async_sessionmaker(ctx["engine"], expire_on_commit=False)
    ctx["watchers"] = {}
    log.info("worker.started", mail_sync=settings.mail_sync_enabled)


async def shutdown(ctx: dict[str, Any]) -> None:
    for watcher in ctx.get("watchers", {}).values():
        watcher.stop()
    if "engine" in ctx:
        await ctx["engine"].dispose()


async def backfill_attachment_flags(ctx: dict[str, Any]) -> dict[str, int | None]:
    """#52: paperclip for messages synced before BODYSTRUCTURE was fetched — one mailbox per run, once per mailbox."""
    from app.mail.attachment_backfill import backfill_mailbox, done_key

    settings: Settings = ctx["settings"]
    if not settings.mail_sync_enabled:
        return {}
    async with ctx["sessionmaker"]() as db:
        for mailbox in (await db.execute(select(Mailbox).where(Mailbox.sync_state == "ok"))).scalars():
            if await ctx["redis"].exists(done_key(mailbox.id)):
                continue
            return {str(mailbox.id): await backfill_mailbox(db, ctx["redis"], mailbox, settings)}
    return {}


async def reclassify_messages_job(
    ctx: dict[str, Any], mailbox_id: str, message_ids: list[str], person_id: str, account_id: str
) -> dict[str, int]:
    """#143 bulk „Znova zaradiť (AI)“ from an AI view: one message after another, stops when the budget is spent;
    manually corrected messages and mail the AI may not read (private folder, …) are skipped."""
    from app.ai.reclassify import ReclassifyError, reclassify
    from app.mail.models import Message

    stats = {"reclassified": 0, "skipped_corrected": 0, "skipped": 0, "failed": 0, "stopped_budget": 0}
    async with ctx["sessionmaker"]() as db:
        mailbox = await db.get(Mailbox, uuid.UUID(mailbox_id))
        if mailbox is None:
            return stats
        for raw in message_ids[:50]:
            message = await db.get(Message, uuid.UUID(raw))
            if message is None or message.mailbox_id != mailbox.id:
                continue
            try:
                await reclassify(
                    db,
                    mailbox,
                    message,
                    ctx["settings"],
                    person_id=uuid.UUID(person_id),
                    account_id=uuid.UUID(account_id),
                )
                stats["reclassified"] += 1
            except ReclassifyError as exc:
                if exc.code == "category_corrected_manually":
                    stats["skipped_corrected"] += 1
                elif exc.code == "ai_not_allowed_here":
                    stats["skipped"] += 1
                elif exc.code in ("ai_budget_exceeded", "ai_unavailable"):
                    stats["stopped_budget"] += 1
                    await db.commit()
                    break
                else:
                    stats["failed"] += 1
            await db.commit()
    return stats


async def ai_catchup(ctx: dict[str, Any]) -> int:
    """#135: every 15 min — enqueue the AI job for mailboxes with unclassified mail or a missing reply draft."""
    from app.ai.catchup import mailboxes_with_work

    async with ctx["sessionmaker"]() as db:
        mailboxes = await mailboxes_with_work(db)
    for mailbox in mailboxes:
        # same job id as after a sync: an already queued or running job is not duplicated
        await ctx["redis"].enqueue_job("process_mailbox_ai_job", str(mailbox.id), _job_id=f"mail-ai:{mailbox.id}")
    return len(mailboxes)


async def money_sync(ctx: dict[str, Any], force: bool = False) -> int:
    """Phase 3b: Money read cache (MONEY_API §4) — checked every 5 min, runs what Settings 13e says is due."""
    from app.money.jobs import run_money_sync

    results = await run_money_sync(ctx["sessionmaker"], ctx["settings"], ctx["redis"], force=force)
    return sum(r.changed for r in results)


async def export_mail_job(ctx: dict[str, Any], export_id: str) -> str | None:
    """#127: back up folders to a ZIP of raw .eml in object storage (BODY.PEEK[], never changes \\Seen)."""
    from app.mail.export import run_export

    async with ctx["sessionmaker"]() as db:
        state = await run_export(ctx["redis"], db, ctx["settings"], export_id)
    return state.status if state else None


async def delete_expired_exports(ctx: dict[str, Any]) -> int:
    """#127: the 24 h download link is over — delete the archive from storage."""
    from app.mail.export import delete_expired

    return await delete_expired(ctx["redis"], ctx["settings"])


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # keep_result=0 frees the job id at once, so the next IDLE push or poll can enqueue the same sync again
    functions: ClassVar[list[Any]] = [
        heartbeat,
        func(sync_mailbox_job, keep_result=0),
        func(process_mailbox_ai_job, keep_result=0),
        func(send_compose_draft, keep_result=0),
        func(flush_scheduled_sends, keep_result=0),
        func(rescan_clamav_attachments, keep_result=0),
        func(reparse_attachment_messages, keep_result=0),
        func(backfill_attachment_flags, keep_result=0),
        # a whole mailbox can take hours; the per-mailbox lock (export.LOCK_TTL_S) has the same bound
        func(export_mail_job, keep_result=0, timeout=6 * 3600, max_tries=1),
        func(delete_expired_exports, keep_result=0),
        func(ai_catchup, keep_result=0),
        func(reclassify_messages_job, keep_result=0, timeout=30 * 60),
        func(money_sync, keep_result=0, timeout=15 * 60, max_tries=1),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, minute=set(range(60)), run_at_startup=True),
        cron(poll_mailboxes, minute=set(range(60)), run_at_startup=True, unique=True),
        cron(flush_scheduled_sends, minute=set(range(60)), run_at_startup=True, unique=True),
        # every 15 minutes (0, 15, 30, 45)
        cron(rescan_clamav_attachments, minute={0, 15, 30, 45}, unique=True),
        # nightly re-parse of stored raw with attachments (pilot #18 B9/B10)
        cron(reparse_attachment_messages, hour={3}, minute={15}, unique=True),
        # #52 one-off paperclip backfill: one mailbox per run until every mailbox is done
        cron(backfill_attachment_flags, minute={5, 35}, unique=True),
        # #127 hourly: archives whose 24 h link expired are deleted
        cron(delete_expired_exports, minute={20}, unique=True),
        # #135 AI catch-up: failed classify/draft calls are retried without waiting for new mail
        cron(ai_catchup, minute={7, 22, 37, 52}, unique=True),
        # Phase 3b Money read cache; the job itself decides what is due (13e interval, nightly full)
        cron(money_sync, minute=set(range(2, 60, 5)), unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
