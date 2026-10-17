"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from starlette.middleware.sessions import SessionMiddleware

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.digest.render import day, money
from ptopilot.digest.select import TrackerRow, build_digests
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web.forms import form_to_profile, profile_to_form, row_count

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters.update(money=money, day=day)
SESSION_MAX_AGE_S = 30 * 24 * 3600


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    geo = geo or load_geo()
    seasons = seasons or load_seasons()
    today = today or (lambda: datetime.now(UTC).date())
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="ptopilot_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.app_base_url.startswith("https://"),
    )

    def page(request: Request, name: str, status: int = 200, **context):
        context = {"signed_in": request.session.get("email"), **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def signed_in_user(s, request: Request) -> User | None:
        email = request.session.get("email")
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    # --- sign-in ---------------------------------------------------------------------------------

    @app.get("/login")
    def login_form(request: Request):
        return page(request, "login.html")

    @app.post("/login")
    def login(request: Request, email: str = Form("")):
        email = email.strip().lower()
        with session_scope(engine) as s:
            invited = s.scalar(select(Invite.email).where(Invite.email == email)) if email else None
        if invited:
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            if emailer is None:
                log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            else:
                try:
                    emailer.send(
                        email,
                        "Your ptopilot sign-in link",
                        f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                        f"Sign in to ptopilot (link works for 15 minutes): {link}",
                    )
                except EmailError as exc:
                    log.error("sign-in email not sent: %s", exc)
        # Same answer either way, so the form doesn't reveal who is invited.
        return page(request, "login_sent.html")

    @app.get("/auth")
    def auth(request: Request, token: str = ""):
        try:
            email = read_login_token(settings.secret_key, token)
        except TokenError as exc:
            return page(
                request, "message.html", 400, title="Sign-in link problem", message=f"{exc}.", login=True
            )
        request.session.clear()
        request.session["email"] = email
        return redirect("/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/login")

    # --- dashboard -------------------------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request, saved: int = 0):
        if not request.session.get("email"):
            return redirect("/login")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/profile")
            user_id, pto_total, pto_committed = user.id, user.pto_days_total, user.pto_committed
        digests = build_digests(engine, geo, seasons, today(), "none", user_id=user_id)
        digest = digests[0] if digests else None
        trackers = digest.trackers if digest else []
        if digest is None:  # no scan has priced anything yet: list the trackers without prices
            with session_scope(engine) as s:
                rows = s.scalars(
                    select(Tracker)
                    .where(Tracker.user_id == user_id, Tracker.active.is_(True))
                    .order_by(Tracker.id)
                )
                trackers = [
                    TrackerRow(t.id, geo.destination(t.destination_code).name, None, None, "new", None,
                               t.snoozed_until if t.snoozed_until and t.snoozed_until >= today() else None)
                    for t in rows
                ]  # fmt: skip
        return page(
            request,
            "dashboard.html",
            digest=digest,
            deals=(digest.deals[:5] if digest else []),
            trackers=trackers,
            pto_total=pto_total,
            pto_committed=pto_committed,
            saved=bool(saved),
        )

    @app.post("/trackers/{tracker_id}/snooze")
    def snooze_tracker(request: Request, tracker_id: int, days: int = Form(30)):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            snooze(tracker, date.fromordinal(today().toordinal() + max(days, 1)))
        return redirect("/")

    @app.post("/trackers/{tracker_id}/unsnooze")
    def unsnooze_tracker(request: Request, tracker_id: int):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            unsnooze(tracker)
        return redirect("/")

    # --- profile / onboarding --------------------------------------------------------------------

    def profile_page(request: Request, form: dict, errors: list[str], status: int = 200):
        return page(
            request,
            "profile.html",
            status,
            form=form,
            errors=errors,
            destinations=geo.destinations(),
            windows=row_count(form, "window"),
            trackers=row_count(form, "tracker"),
        )

    @app.get("/profile")
    def profile_form(request: Request):
        if not request.session.get("email"):
            return redirect("/login")
        with session_scope(engine) as s:
            form = profile_to_form(s, signed_in_user(s, request))
        return profile_page(request, form, [])

    @app.post("/profile")
    async def save_profile(request: Request):
        email = request.session.get("email")
        if not email:
            return redirect("/login")
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            profile = parse_profile(form_to_profile(form, email), geo)
        except ValueError as exc:
            errors = [line.removeprefix("  - ") for line in str(exc).splitlines()[1:]]
            return profile_page(request, form, errors, 400)
        with session_scope(engine) as s:
            apply_profile(s, profile)
        return redirect("/?saved=1")

    # --- snooze links from the digest ------------------------------------------------------------

    def action_context(s, token: str):
        action = read_action_token(settings.secret_key, token)
        tracker = s.get(Tracker, action.tracker_id)
        if tracker is None:
            raise TokenError("this tracker no longer exists")
        return action, tracker, geo.destination(tracker.destination_code).name

    @app.get("/s/{token}")
    def confirm_action(request: Request, token: str):
        with session_scope(engine) as s:
            try:
                action, _, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
        return page(
            request,
            "action_confirm.html",
            action=action,
            label=ACTION_LABELS[action.kind],
            destination=destination,
        )

    @app.post("/s/{token}")
    def do_action(request: Request, token: str, price: str = Form("")):
        with session_scope(engine) as s:
            try:
                action, tracker, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
            amount = None
            if action.kind == "under":
                try:
                    amount = Decimal(price.replace("$", "").replace(",", "").strip())
                except InvalidOperation:
                    amount = None
            try:
                message = apply_action(s, tracker, action, today(), price=amount)
            except ValueError as exc:
                return page(
                    request,
                    "action_confirm.html",
                    400,
                    action=action,
                    label=ACTION_LABELS[action.kind],
                    destination=destination,
                    error=str(exc),
                )
        return page(request, "message.html", title=f"Done: {destination}", message=message)

    return app
