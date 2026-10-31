"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.

Small actions (snooze, book, plan, related, remove) also answer JSON when the page's script asks with
`Accept: application/json` (static/ui.js): `{"ok": true, ...}`, or the same 4xx status the page would get
with `{"ok": false, "errors": [...]}`. Without that header they redirect or re-render exactly as before.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from ptopilot import config
from ptopilot.core.airports import AirportCatalog, PlaceMatch
from ptopilot.core.calendar import WorkCalendar, calendar_codes, upcoming_holiday_names
from ptopilot.core.geo import Geo, UnknownCodeError, palette
from ptopilot.core.seasons import SeasonTable, trip_month
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Candidate, Invite, PlannedTrip, PlanningYear, RelatedLink, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.destinations import add_destination, prefetch_climate, remove_destination
from ptopilot.digest.render import banner_text, date_range, day, money, stops
from ptopilot.digest.select import latest_run_date
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.photos import all_photos, photo_urls, photos_for
from ptopilot.plan_totals import year_totals
from ptopilot.planning import (
    book_from_candidate,
    book_trip,
    booked_trips,
    cancel_booking,
    current_year,
    default_new_year,
    planning_years,
    set_ranges,
    set_target,
    set_year_pto,
    start_year,
    unplan_trip,
)
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.related_links import accept as accept_related
from ptopilot.related_links import dismiss as dismiss_related
from ptopilot.related_links import place_for, refresh_missing_seasons, suggestions_for
from ptopilot.settings import Settings
from ptopilot.sources.climate import fetch_climate
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web import api, onboarding
from ptopilot.web.forms import SECTIONS, explain_errors, form_to_profile, merge_section, profile_to_form
from ptopilot.web.grid import date_grid, grid_band
from ptopilot.web.history import (
    destination_summaries,
    hero_deal,
    last_scan,
    related_deals,
    trend,
    trends,
    trip_options,
    typical_band,
)
from ptopilot.web.planner_view import months_ahead, plan_context, too_short
from ptopilot.web.samples import landing
from ptopilot.web.viz import sparkline, trend_chart, trend_direction

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def css_url(url: str) -> str:
    """A URL safe inside an unquoted CSS url(): characters that could end it are percent-encoded."""
    return re.sub(r"""[\s'"()\\;<>]""", lambda m: f"%{ord(m.group()):02X}", url)


TEMPLATES.env.filters.update(money=money, day=day, dates=date_range, stops=stops, css_url=css_url)
# The stylesheet's URL changes with its content, so a browser never keeps an old copy after a deploy.
CSS_VERSION = hashlib.sha1((WEB_DIR / "static" / "app.css").read_bytes()).hexdigest()[:10]
TEMPLATES.env.globals["css_version"] = CSS_VERSION
# Postgres int4 range: anything inside it is looked up (0 or negative are simply not found, a 404); ids
# beyond it would make the database raise, so they're a styled 400 instead.
TRACKER_ID = Annotated[int, PathParam(ge=-(2**31), le=2**31 - 1)]
MAX_RANGE_ROWS = 50
PLAN_YEAR = Annotated[int, PathParam(ge=1900, le=2200)]
WELCOME_STEP = Annotated[int, PathParam(ge=1, le=onboarding.LAST_STEP)]
TRACKER_URL = re.compile(r"/trackers/\d+")
SESSION_MAX_AGE_S = 30 * 24 * 3600
LOGIN_COOLDOWN_S = 120  # at most one sign-in email per address per 2 minutes
SIGN_IN_AGAIN = "Your session has ended. Sign in again."


def wants_json(request: Request) -> bool:
    """The page's script asked for JSON (static/ui.js sends Accept: application/json)."""
    return "application/json" in request.headers.get("accept", "")


def json_or_redirect(request: Request, url: str, **payload) -> Response:
    """Success: {"ok": true, **payload} for the script, else the usual redirect after a POST."""
    if wants_json(request):
        return JSONResponse({"ok": True, **payload})
    return RedirectResponse(url, status_code=303)


def json_error(status: int, *errors: str) -> JSONResponse:
    return JSONResponse({"ok": False, "errors": list(errors)}, status_code=status)


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
    now: Callable[[], float] | None = None,
    climate: Callable[[float, float], dict] = fetch_climate,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    # Places users add live in the database, so geography and seasons are read per request (the YAML and
    # airport catalog parts are cached; only the small query for added places runs each time).
    # An injected geo or season table (tests) is used as given.
    fixed_geo, fixed_seasons = geo, seasons
    catalog = AirportCatalog.load()
    today = today or (lambda: datetime.now(UTC).date())
    now = now or time.monotonic
    last_link_sent: dict[str, float] = {}  # per process; enough for one small instance
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="ptopilot_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.app_base_url.startswith("https://"),
    )

    def current_geo() -> Geo:
        return fixed_geo or load_geo(engine)

    def current_seasons() -> SeasonTable:
        return fixed_seasons or load_seasons(engine)

    def page(request: Request, name: str, status: int = 200, **context):
        context = {"signed_in": request.session.get("email"), **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def signed_out(request: Request) -> Response:
        """In-place endpoints are signed-in only: home for a page, 401 for the script."""
        return json_error(401, SIGN_IN_AGAIN) if wants_json(request) else redirect("/")

    def needs_profile(request: Request) -> Response:
        """Signed in, but no profile saved yet: the welcome steps make one."""
        if wants_json(request):
            return json_error(403, "Save your profile first.")
        return redirect("/welcome")

    def missing(request: Request, message: str) -> Response:
        if wants_json(request):
            return json_error(404, message)
        return page(request, "message.html", 404, title="Not found", message=message)

    def rejected(request: Request, message: str, html: Callable[[], Response]) -> Response:
        """A 400 the user can fix: the message for the script, else the page re-rendered with it."""
        return json_error(400, message) if wants_json(request) else html()

    def is_invited(email: str) -> bool:
        with session_scope(engine) as s:
            return s.scalar(select(Invite.email).where(Invite.email == email)) is not None

    def current_email(request: Request) -> str | None:
        """The signed-in email, as long as it is still invited; removing an invite ends the session."""
        email = request.session.get("email")
        if email and not is_invited(email):
            request.session.clear()
            return None
        return email

    def signed_in_user(s, request: Request) -> User | None:
        email = current_email(request)
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

    @app.exception_handler(RequestValidationError)
    def bad_request(request: Request, exc: RequestValidationError):
        """Malformed form fields or URLs (e.g. a non-numeric id) get a page, not FastAPI's JSON."""
        message = "Something in that request didn't look right. Go back and try again."
        if wants_json(request):
            return json_error(400, message)
        return page(request, "message.html", 400, title="That didn't work", message=message)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException):
        """Unknown URLs and other HTTP errors get a page, not FastAPI's JSON (headers such as Allow kept)."""
        if wants_json(request):
            response = json_error(exc.status_code, "That didn't work.")
        elif exc.status_code == 404:
            response = page(
                request, "message.html", 404, title="Not found", message="There's nothing at this address."
            )
        else:
            try:
                title = HTTPStatus(exc.status_code).phrase
            except ValueError:
                title = "Error"
            response = page(
                request, "message.html", exc.status_code, title=title, message="That didn't work."
            )
        response.headers.update(exc.headers or {})
        return response

    app.include_router(
        api.router(
            catalog,
            today,
            lambda r: bool(current_email(r)),
            signed_out,
            lambda airport_sets: photo_urls(engine, airport_sets),
        )
    )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    # --- sign-in ---------------------------------------------------------------------------------

    @app.get("/login")
    def login_form():
        return redirect("/")  # the sign-in form lives on the landing page

    def send_link(email: str, link: str) -> None:
        if emailer is None:
            log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            return
        try:
            emailer.send(
                email,
                "Your ptopilot sign-in link",
                f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                f"Sign in to ptopilot (link works for 15 minutes): {link}",
            )
        except EmailError as exc:
            log.error("sign-in email not sent: %s", exc)

    @app.post("/login")
    def login(request: Request, background: BackgroundTasks, email: str = Form("")):
        email = email.strip().lower()
        cooled_down = now() - last_link_sent.get(email, float("-inf")) >= LOGIN_COOLDOWN_S
        if email and cooled_down and is_invited(email):
            last_link_sent[email] = now()
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            # Sent after the response, so invited and uninvited addresses answer equally fast.
            background.add_task(send_link, email, link)
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
        if not is_invited(email):
            message = "this address is no longer invited."
            return page(request, "message.html", 400, title="Sign-in link problem", message=message)
        request.session.clear()
        request.session["email"] = email
        return redirect("/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/")

    # --- dashboard -------------------------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request, saved: int = 0):
        if not current_email(request):
            return page(request, "landing.html", ex=landing(fixed_geo or load_geo(), today()))
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if onboarding.needs_welcome(user):
                return redirect("/welcome")
            user_id = user.id
            py = current_year(s, user, today())
            pto_total, pto_committed = (
                (py.pto_days, py.other_time_off) if py else (user.pto_days_total, user.pto_committed)
            )
            geo = current_geo()
            totals = year_totals(s, user, py.year, geo, current_seasons()) if py else None
            scanned_at, checked = last_scan(s, user, today())
        # Every current trip counts, including deals already emailed.
        summaries = destination_summaries(engine, geo, current_seasons(), user_id, today())
        with session_scope(engine) as s:
            photos = photos_for({c.code for c in summaries}, s)
        hero = hero_deal(summaries)
        card_trends = trends(engine, [x.tracker_id for x in summaries], today())
        return page(
            request,
            "dashboard.html",
            active="dashboard",
            summaries=summaries,
            photos=photos,
            hero=hero,
            hero_arrival=airport_city(hero.headline.dest_airport) if hero else None,
            hero_spark=sparkline(card_trends.get(hero.tracker_id, [])) if hero else None,
            directions={k: trend_direction(v) for k, v in card_trends.items()},
            scanned_at=scanned_at,
            checked=checked,
            run_date=latest_run_date(engine, today()),
            pto_total=pto_total,
            pto_committed=pto_committed,
            totals=totals,
            banner=banner_text(totals) if totals else None,
            saved=bool(saved),
        )

    @app.get("/credits")
    def credits(request: Request):
        """Every cover photo the site shows, with its attribution. Public, like the landing page."""
        geo = current_geo()
        with session_scope(engine) as s:
            photos = all_photos(s)
        names = {d.code: d.name for d in geo.destinations()}
        rows = sorted(
            ((names.get(code, code), photo) for code, photo in photos.items()), key=lambda r: r[0].casefold()
        )
        return page(request, "credits.html", rows=rows)

    def destination_view(request: Request, tracker_id: int, status: int = 200, error: str | None = None):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None or not tracker.active:  # someone else's, removed or missing: same answer
                return page(request, "message.html", 404, title="Not found", message="No such destination.")
            code, stay = tracker.destination_code, (tracker.min_stay_days, tracker.max_stay_days)
            snoozed = tracker.snoozed_until
            user = signed_in_user(s, request)
            target = tracker.target_days or user.ideal_trip_days
            bookings = [
                b
                for b in booked_trips(s, user, geo=current_geo())
                if b.tracker_id == tracker_id and b.year >= today().year
            ]
        if snoozed is not None and snoozed < today():
            snoozed = None
        geo, seasons = current_geo(), current_seasons()
        dest = geo.destination(code)
        options = trip_options(engine, geo, seasons, tracker_id, today())
        band = typical_band(options)
        run_date = latest_run_date(engine, today())
        with session_scope(engine) as s:
            related = related_deals(s, tracker_id, run_date, geo, today()) if run_date else []
            photos = photos_for({code, *(r.code for r in related)}, s)
        # The header's season: the month of the best trip on show, else this month.
        best = next((o for o in options if not o.dimmed), None)
        month = trip_month(best.depart_date, best.return_date) if best else today().month
        return page(
            request,
            "destination.html",
            status,
            tracker_id=tracker_id,
            dest=dest,
            palette=palette(dest),
            photo=photos.get(code),
            stay=stay,
            target=target,
            season_rating=seasons.rating((dest.code, dest.country), month),
            season_month=date(2000, month, 1).strftime("%B"),
            snoozed_until=snoozed,
            bookings=bookings,
            options=options,
            grid=date_grid(options, grid_band(options, target)),
            run_date=run_date,
            related=related,
            related_palettes={r.code: palette(geo.destination(r.code)) for r in related},
            photos=photos,
            band=band,
            chart=trend_chart(trend(engine, tracker_id, today()), band, palette(dest)),
            error=error,
        )

    @app.get("/trackers/{tracker_id}")
    def destination_page(request: Request, tracker_id: TRACKER_ID):
        if not current_email(request):
            return redirect("/")
        return destination_view(request, tracker_id)

    @app.post("/trackers/{tracker_id}/book")
    def book_deal(request: Request, tracker_id: TRACKER_ID, candidate_id: int = Form(...)):
        if not current_email(request):
            return signed_out(request)
        not_found = lambda: missing(request, "No such trip.")  # noqa: E731
        try:
            with session_scope(engine) as s:
                user = signed_in_user(s, request)
                candidate = s.get(Candidate, candidate_id)
                tracker = s.get(Tracker, tracker_id)
                if (
                    user is None
                    or candidate is None
                    or candidate.tracker_id != tracker_id
                    or tracker is None
                    or not tracker.active
                ):
                    return not_found()
                trip = book_from_candidate(s, user, candidate_id, geo=current_geo())
                year = trip.year
        except LookupError:
            return not_found()
        except ValueError as exc:
            message = str(exc)
            return rejected(request, message, lambda: destination_view(request, tracker_id, 400, message))
        return json_or_redirect(request, f"/plan/{year}?saved=booked", year=year)

    def back_to(next_url: str) -> str:
        """The page the form was on, if that is a destination page of ours; never off-site."""
        return next_url if TRACKER_URL.fullmatch(next_url) else "/"

    @app.post("/trackers/{tracker_id}/snooze")
    def snooze_tracker(request: Request, tracker_id: TRACKER_ID, days: int = Form(30), next: str = Form("")):
        if not current_email(request):
            return signed_out(request)
        until = date.fromordinal(today().toordinal() + max(days, 1))
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return missing(request, "No such tracker.")
            snooze(tracker, until)
        return json_or_redirect(request, back_to(next), snoozed_until=until.isoformat())

    @app.post("/trackers/{tracker_id}/unsnooze")
    def unsnooze_tracker(request: Request, tracker_id: TRACKER_ID, next: str = Form("")):
        if not current_email(request):
            return signed_out(request)
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return missing(request, "No such tracker.")
            unsnooze(tracker)
        return json_or_redirect(request, back_to(next))

    # --- destinations -----------------------------------------------------------------------------

    def airport_city(code: str) -> str:
        found = catalog.get(code)
        return found.city if found else code

    def place_name(geo: Geo, place_code: str, airport: str) -> str:
        try:
            return geo.destination(place_code).name
        except UnknownCodeError:
            return airport_city(airport)

    def destinations_page(
        request: Request, user_id: int, q: str, error: str | None = None, status: int = 200
    ):
        geo = current_geo()
        with session_scope(engine) as s:
            user = s.get(User, user_id)
            homes = [user.home_airport, *user.nearby_airports]
            trackers = s.scalars(
                select(Tracker).where(Tracker.user_id == user_id, Tracker.active.is_(True))
            ).all()
            rows = []
            for t in trackers:
                try:
                    dest = geo.destination(t.destination_code)
                except UnknownCodeError:
                    continue
                links = {
                    link.airport: link
                    for link in s.scalars(select(RelatedLink).where(RelatedLink.tracker_id == t.id))
                }
                rows.append(
                    {
                        "id": t.id,
                        "name": dest.name,
                        "suggestions": [
                            {"airport": g.airport, "name": airport_city(g.airport), "label": g.label}
                            for g in suggestions_for(s, user, t, geo, catalog)
                        ],
                        "related": [
                            {"airport": a, "name": place_name(geo, link.place_code, a)}
                            for a, link in links.items()
                            if link.status == "accepted"
                        ],
                        "palette": palette(dest),
                        "target_days": t.target_days,
                        "stay": (t.min_stay_days, t.max_stay_days),
                        "min_trip": too_short(geo, homes, dest, t.target_days),
                    }
                )
        rows.sort(key=lambda r: r["name"])
        q = q.strip()
        return page(
            request,
            "destinations.html",
            status,
            active="destinations",
            rows=rows,
            q=q,
            matches=catalog.search(q) if q else [],
            error=error,
        )

    def destinations_user_id(request: Request) -> int | Response:
        if not current_email(request):
            return signed_out(request)
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            return user.id if user else needs_profile(request)

    @app.get("/destinations")
    def destinations(request: Request, q: str = ""):
        user_id = destinations_user_id(request)
        if not isinstance(user_id, int):
            return user_id
        refresh_missing_seasons(engine, user_id, catalog, climate)
        return destinations_page(request, user_id, q)

    @app.post("/destinations/{tracker_id}/related")
    def related_place(
        request: Request, tracker_id: TRACKER_ID, airport: str = Form(""), action: str = Form("")
    ):
        user_id = destinations_user_id(request)
        if not isinstance(user_id, int):
            return user_id
        airport = airport.strip().upper()
        with session_scope(engine) as s:
            tracker = s.get(Tracker, tracker_id)
            if tracker is None or tracker.user_id != user_id:
                return missing(request, "No such destination.")
            if action not in ("accept", "dismiss") or catalog.get(airport) is None:
                message = "Pick a related place to accept or dismiss."
                return rejected(
                    request, message, lambda: destinations_page(request, user_id, "", message, 400)
                )
            fetched = climate
            if action == "accept":  # the slow climate lookup holds no transaction
                code, match = place_for(s, airport, catalog)
                if code is None:
                    fetched = prefetch_climate(s, match, [airport], climate)
        with session_scope(engine) as s:
            user = s.get(User, user_id)
            if action == "accept":
                accept_related(s, user, tracker_id, airport, climate=fetched, catalog=catalog)
            else:
                dismiss_related(s, user, tracker_id, airport)
        return json_or_redirect(request, "/destinations")

    def add_place_for(user_id: int, code: str, airports: list[str] | None, target_days: int) -> int | str:
        """Track a place picked in "Add a place": the new tracker's id, or a message saying what to fix."""
        picked = catalog.get(code)
        chosen = list(dict.fromkeys(a.strip().upper() for a in airports or [] if a.strip()))
        allowed = {picked.code, *(a.code for a in catalog.nearby(picked.code))} if picked else set()
        if picked is None or picked.code not in chosen or not set(chosen) <= allowed:
            return "Pick a place and at least one airport."
        if not 2 <= target_days <= 60:
            return "Days away must be between 2 and 60."
        match = PlaceMatch(picked, (), catalog.country_name(picked.country))
        with session_scope(engine) as s:  # a short read first: the slow climate lookup holds no transaction
            fetched = prefetch_climate(s, match, chosen, climate)
        with session_scope(engine) as s:
            tracker = add_destination(
                s, s.get(User, user_id), match, chosen, target_days, climate=fetched, today=today()
            )
            return tracker.id

    @app.post("/destinations")
    def add_place(
        request: Request,
        code: str = Form(""),
        airports: Annotated[list[str] | None, Form()] = None,
        target_days: int = Form(10),
    ):
        user_id = destinations_user_id(request)
        if not isinstance(user_id, int):
            return user_id
        added = add_place_for(user_id, code, airports, target_days)
        if isinstance(added, str):
            return rejected(request, added, lambda: destinations_page(request, user_id, code, added, 400))
        return json_or_redirect(request, "/destinations", tracker_id=added)

    @app.post("/destinations/{tracker_id}/remove")
    def remove_place(request: Request, tracker_id: TRACKER_ID):
        if not current_email(request):
            return signed_out(request)
        user_id = None
        try:
            with session_scope(engine) as s:
                user = signed_in_user(s, request)
                user_id = user.id if user else None
                if user is None or not remove_destination(s, user, tracker_id, today=today()):
                    return missing(request, "No such destination.")
        except ValueError as exc:
            message = str(exc)
            return rejected(request, message, lambda: destinations_page(request, user_id, "", message, 400))
        return json_or_redirect(request, "/destinations")

    # --- the year planner ---------------------------------------------------------------------------

    def plan_page(request: Request, user_id: int, year: int, status: int = 200, error=None, ranges=None):
        ctx = plan_context(engine, current_geo(), current_seasons(), user_id, year, today())
        if ctx is None:
            return page(request, "message.html", 404, title="Not found", message="No such planning year.")
        if ranges is not None:
            ctx["ranges"] = ranges
        saved = request.query_params.get("saved")
        return page(request, "plan.html", status, active="plan", error=error, saved=saved, **ctx)

    def plan_user_id(request: Request, year: int) -> int | Response:
        """The signed-in user's id when they have this planning year; else a redirect or a 404 page."""
        if not current_email(request):
            return signed_out(request)
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return needs_profile(request)
            if s.get(PlanningYear, (user.id, year)) is None:
                return missing(request, "No such planning year.")
            return user.id

    @app.get("/plan")
    def plan_home(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/welcome")
            py = current_year(s, user, today())
            return redirect(f"/plan/{py.year}" if py else "/plan/new")

    def new_year_page(request: Request, user_id: int, status: int = 200, error=None, form=None):
        with session_scope(engine) as s:
            user = s.get(User, user_id)
            taken = {py.year for py in planning_years(s, user)}
            years = [
                y for y in range(today().year, today().year + config.PLAN_YEARS_AHEAD + 1) if y not in taken
            ]
            if not years:
                return redirect("/plan")
            default_year = default_new_year(s, user, today())
            latest = max(taken, default=None)
            pto_days = s.get(PlanningYear, (user_id, latest)).pto_days if latest else user.pto_days_total
            geo = current_geo()
            # Last year's booked trips are done, so they start unchecked: the latest year before the new one.
            new_year = int((form or {}).get("year", default_year if default_year in years else years[0]))
            earlier = [y for y in taken if y < new_year]
            booked_in = (
                {b.tracker_id: b.year for b in booked_trips(s, user, [max(earlier)], geo=geo)}
                if earlier
                else {}
            )
            trips = []
            for t in s.scalars(
                select(Tracker)
                .where(Tracker.user_id == user_id, Tracker.active.is_(True))
                .order_by(Tracker.id)
            ):
                try:
                    name = geo.destination(t.destination_code).name
                except UnknownCodeError:
                    continue
                target = (
                    f"~{t.target_days} days" if t.target_days else f"{t.min_stay_days}–{t.max_stay_days} days"
                )
                trips.append(
                    {
                        "id": t.id,
                        "name": name,
                        "target": target,
                        "booked_year": booked_in.get(t.id),
                    }
                )
        form = form or {}
        year = int(form.get("year", default_year if default_year in years else years[0]))
        return page(
            request,
            "plan_new.html",
            status,
            active="plan",
            error=error,
            years=years,
            year=year,
            pto_days=form.get("pto_days", pto_days),
            other_time_off=form.get("other_time_off", 0),
            trips=trips,
            checked=form.get("checked", {t["id"] for t in trips if t["booked_year"] is None}),
        )

    @app.get("/plan/new")
    def plan_new_form(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/welcome")
            user_id = user.id
        return new_year_page(request, user_id)

    @app.post("/plan/new")
    def plan_new_start(
        request: Request,
        year: int = Form(...),
        pto_days: int = Form(...),
        other_time_off: int = Form(...),
        tracker_ids: Annotated[list[int] | None, Form()] = None,
    ):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/welcome")
            user_id = user.id
            try:
                start_year(s, user, year, pto_days, other_time_off, tracker_ids or [], today=today())
            except ValueError as exc:
                s.rollback()
                error = str(exc)
            else:
                error = None
        if error is None:
            return redirect(f"/plan/{year}")
        form = {
            "year": year,
            "pto_days": pto_days,
            "other_time_off": other_time_off,
            "checked": set(tracker_ids or []),
        }
        return new_year_page(request, user_id, 400, error, form)

    @app.get("/plan/{year}")
    def plan_view(request: Request, year: PLAN_YEAR):
        user_id = plan_user_id(request, year)
        return plan_page(request, user_id, year) if isinstance(user_id, int) else user_id

    @app.post("/plan/{year}/ranges")
    async def plan_save_ranges(request: Request, year: PLAN_YEAR):
        user_id = plan_user_id(request, year)
        if not isinstance(user_id, int):
            return user_id
        form = await request.form()
        indexes = sorted({int(m[1]) for k in form if (m := re.fullmatch(r"range_start_(\d+)", k))})
        if len(indexes) > MAX_RANGE_ROWS:
            return plan_page(request, user_id, year, 400, "Too many ranges.")
        rows = [
            {
                "start": str(form.get(f"range_start_{i}", "")).strip(),
                "end": str(form.get(f"range_end_{i}", "")).strip(),
            }
            for i in indexes
        ]
        parsed, labels = [], []
        try:
            for i, row in zip(indexes, rows, strict=True):
                if not row["start"] and not row["end"]:
                    continue
                if not row["start"] or not row["end"]:
                    raise ValueError(f"range {i + 1}: enter both a start and an end date")
                try:
                    parsed.append((date.fromisoformat(row["start"]), date.fromisoformat(row["end"])))
                except ValueError:
                    raise ValueError(f"range {i + 1}: those dates aren't valid") from None
                labels.append(i + 1)
            with session_scope(engine) as s:
                try:
                    set_ranges(s, signed_in_user(s, request), year, parsed)
                except ValueError as exc:  # name the row as the form showed it, blank rows included
                    raise ValueError(
                        re.sub(
                            r"range (\d+)",
                            lambda m: (
                                f"range {(labels[int(m[1]) - 1] if 0 < int(m[1]) <= len(labels) else m[1])}"
                            ),
                            str(exc),
                            count=1,
                        )
                    ) from None
        except ValueError as exc:
            return plan_page(request, user_id, year, 400, str(exc), rows)
        return redirect(f"/plan/{year}?saved=ranges")

    @app.post("/plan/{year}/pto")
    def plan_save_pto(
        request: Request, year: PLAN_YEAR, pto_days: int = Form(...), other_time_off: int = Form(...)
    ):
        user_id = plan_user_id(request, year)
        if not isinstance(user_id, int):
            return user_id
        try:
            with session_scope(engine) as s:
                set_year_pto(s, s.get(User, user_id), year, pto_days, other_time_off)
        except ValueError as exc:
            message = str(exc)
            return rejected(request, message, lambda: plan_page(request, user_id, year, 400, message))
        return json_or_redirect(request, f"/plan/{year}?saved=pto")

    def planned_tracker(s, user_id: int, year: int, tracker_id: int) -> bool:
        return (
            s.scalar(
                select(PlannedTrip.id)
                .join(Tracker, Tracker.id == PlannedTrip.tracker_id)
                .where(
                    PlannedTrip.tracker_id == tracker_id,
                    PlannedTrip.year == year,
                    PlannedTrip.user_id == user_id,
                    Tracker.active.is_(True),
                )
            )
            is not None
        )

    @app.post("/plan/{year}/trips/{tracker_id}")
    def plan_edit_trip(
        request: Request, year: PLAN_YEAR, tracker_id: TRACKER_ID, target_days: int = Form(...)
    ):
        user_id = plan_user_id(request, year)
        if not isinstance(user_id, int):
            return user_id
        try:
            with session_scope(engine) as s:
                if not planned_tracker(s, user_id, year, tracker_id):
                    return missing(request, "No such trip.")
                set_target(s, s.get(User, user_id), tracker_id, target_days)
        except ValueError as exc:
            message = str(exc)
            return rejected(request, message, lambda: plan_page(request, user_id, year, 400, message))
        return json_or_redirect(request, f"/plan/{year}?saved=trip")

    @app.post("/plan/{year}/trips/{tracker_id}/remove")
    def plan_remove_trip(request: Request, year: PLAN_YEAR, tracker_id: TRACKER_ID):
        user_id = plan_user_id(request, year)
        if not isinstance(user_id, int):
            return user_id
        with session_scope(engine) as s:
            if not planned_tracker(s, user_id, year, tracker_id):
                return missing(request, "No such trip.")
            try:
                unplan_trip(s, s.get(User, user_id), tracker_id, year, today=today())
            except ValueError as exc:
                error = str(exc)
            else:
                error = None
        if error:
            return rejected(request, error, lambda: plan_page(request, user_id, year, 400, error))
        return json_or_redirect(request, f"/plan/{year}?saved=removed")

    PRICE_HELP = "Enter a price like 802, or leave it blank."

    def parse_price(raw: str) -> Decimal | None:
        text = raw.strip().replace("$", "").replace(",", "").strip()
        if not text:
            return None
        if not re.fullmatch(r"\d{1,7}(\.\d{1,2})?", text):
            raise ValueError(PRICE_HELP)
        return Decimal(text)

    @app.post("/plan/{year}/trips/{tracker_id}/book")
    def plan_book_trip(
        request: Request,
        year: PLAN_YEAR,
        tracker_id: TRACKER_ID,
        depart: str = Form(""),
        return_: str = Form("", alias="return"),
        price: str = Form(""),
    ):
        user_id = plan_user_id(request, year)
        if not isinstance(user_id, int):
            return user_id
        try:
            with session_scope(engine) as s:
                if not planned_tracker(s, user_id, year, tracker_id):
                    return missing(request, "No such trip.")
                user = s.get(User, user_id)
                try:
                    start, end = date.fromisoformat(depart.strip()), date.fromisoformat(return_.strip())
                except ValueError:
                    raise ValueError("Enter valid depart and return dates.") from None
                book_trip(
                    s,
                    user,
                    tracker_id,
                    year,
                    start,
                    end,
                    price=parse_price(price),
                    currency=user.currency,
                    geo=current_geo(),
                )
        except ValueError as exc:
            message = str(exc)
            return rejected(request, message, lambda: plan_page(request, user_id, year, 400, message))
        return json_or_redirect(request, f"/plan/{year}?saved=booked")

    @app.post("/plan/{year}/trips/{tracker_id}/cancel")
    def plan_cancel_booking(request: Request, year: PLAN_YEAR, tracker_id: TRACKER_ID):
        user_id = plan_user_id(request, year)
        if not isinstance(user_id, int):
            return user_id
        with session_scope(engine) as s:
            if not planned_tracker(s, user_id, year, tracker_id):
                return missing(request, "No such trip.")
            cancel_booking(s, s.get(User, user_id), tracker_id, year)
        return json_or_redirect(request, f"/plan/{year}?saved=cancelled")

    # --- profile / onboarding --------------------------------------------------------------------

    def chip_items(raw: str, kind: str) -> list[dict]:
        """A comma list from the form as chips: {value, label} plus the bold code for airports."""
        items = []
        for value in (part.strip() for part in (raw or "").split(",")):
            if not value:
                continue
            if kind == "airports":
                items.append({"value": value.upper(), "code": value.upper(), "label": airport_city(value)})
            elif kind == "dates":
                try:
                    d = date.fromisoformat(value)
                    items.append({"value": value, "label": f"{day(d)}, {d.year}"})
                except ValueError:
                    items.append({"value": value, "label": value})
            else:
                items.append({"value": value, "label": value})
        return items

    def calendar_choices(current: str) -> list[tuple[str, str]]:
        def label(code: str) -> str:
            country, _, sub = code.partition("-")
            return f"{catalog.country_name(country)} · {sub}" if sub else catalog.country_name(country)

        codes = calendar_codes(current)
        if current and current not in codes:
            codes.append(current)  # keep what was typed, so the page shows it and validation explains it
        return sorted(((code, label(code)) for code in codes), key=lambda c: (c[1].casefold(), c[0]))

    def days_off_calendar(code: str, days_off: list[dict]):
        """The coming year as the planner's tap-calendar, with the company days off marked."""
        picked = []
        for item in days_off:
            try:
                picked.append(date.fromisoformat(item["value"]))
            except ValueError:
                pass  # a mistyped date is explained beside the field; the calendar just can't show it
        try:
            cal = WorkCalendar.from_code(code or "US", picked)
        except ValueError:  # an unknown calendar is explained beside its field
            cal = WorkCalendar.from_code("US", picked)
        return months_ahead(today(), cal)

    def profile_context(form: dict, errors: list[dict]) -> dict:
        """What the profile's sections render from; the profile page and the welcome steps share them.

        errors: [{"field", "message"}] (forms.explain_errors); each is also shown beside its field."""
        calendar = form.get("holiday_calendar", "")
        by_field: dict[str, list[str]] = {}
        for e in errors:
            by_field.setdefault(e["field"] or "", []).append(e["message"])
        days_off = chip_items(form.get("extra_days_off", ""), "dates")
        return {
            "form": form,
            "errors": [e["message"] for e in errors],
            "field_errors": by_field,
            "home": chip_items(form.get("home_airport", ""), "airports"),
            "nearby": chip_items(form.get("nearby_airports", ""), "airports"),
            "ignored": chip_items(form.get("ignored_holidays", ""), "holidays"),
            "days_off": days_off,
            "days_off_months": days_off_calendar(calendar, days_off),
            "calendars": calendar_choices(calendar),
            "holiday_names": upcoming_holiday_names(calendar, today()) if calendar else [],
        }

    def profile_page(request: Request, form: dict, errors: list[dict], status: int = 200):
        saved = request.query_params.get("saved") == "1" and not errors
        context = profile_context(form, errors)
        return page(request, "profile.html", status, active="profile", saved=saved, **context)

    @app.get("/profile")
    def profile_form(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if onboarding.needs_welcome(user):
                return redirect("/welcome")
            form = profile_to_form(s, user)
        return profile_page(request, form, [])

    def section_form(email: str, submitted: dict[str, str]) -> dict[str, str]:
        """The submitted fields laid over the saved profile (forms.merge_section)."""
        with session_scope(engine) as s:
            user = s.scalar(select(User).where(User.email == email))
            form = merge_section(profile_to_form(s, user), submitted)
        form.pop("pto_committed", None)  # lives on the planner now; saving the profile never changes it
        return form

    def checked_profile(form: dict[str, str], email: str):
        """(the parsed profile, []), or (None, its problems as forms.explain_errors gives them)."""
        try:
            return parse_profile(form_to_profile(form, email), current_geo(), require_plan=False), []
        except ValueError as exc:
            problems = [line.removeprefix("  - ") for line in str(exc).splitlines()[1:]]
            return None, explain_errors(problems, form)

    def field_errors_json(errors: list[dict]) -> JSONResponse:
        body = {"ok": False, "errors": [e["message"] for e in errors], "field_errors": errors}
        return JSONResponse(body, status_code=400)

    @app.post("/profile")
    async def save_profile(request: Request):
        """The whole profile (the page without JS, or an old full form), or one section of it.

        Whatever is sent is laid over the saved profile (forms.merge_section), so a section, or a script
        sending only the field that changed, leaves the rest alone; then the usual validation runs."""
        email = current_email(request)
        if not email:
            return signed_out(request)
        submitted = {k: str(v) for k, v in (await request.form()).items()}
        for key in ("home_airport", "nearby_airports"):  # a city typed without JS counts when it's clear
            if key in submitted:
                submitted[key] = api.resolve_airports(catalog, submitted[key])
        section = submitted.get("section", "")
        if section not in SECTIONS:
            section = submitted["section"] = "" if wants_json(request) else "all"
        form = section_form(email, submitted)
        profile, errors = checked_profile(form, email)
        if profile is None:
            if wants_json(request):
                return field_errors_json(errors)
            return profile_page(request, form, errors, 400)
        with session_scope(engine) as s:
            # A whole profile from someone without one (the old single form) is still taken, and counts
            # as onboarded (models.User.onboarded_at); new people start at /welcome instead.
            is_new = s.scalar(select(User.id).where(User.email == profile.email)) is None
            apply_profile(s, profile, replace_plan=False)
        if is_new:
            return json_or_redirect(request, "/plan/new", next="/plan/new")
        return json_or_redirect(request, "/?saved=1" if section == "all" else "/profile?saved=1")

    # --- welcome: the guided first run (web/onboarding.py) ------------------------------------------

    def welcome_places(user_id: int) -> list[dict]:
        geo = current_geo()
        with session_scope(engine) as s:
            trackers = s.scalars(
                select(Tracker)
                .where(Tracker.user_id == user_id, Tracker.active.is_(True))
                .order_by(Tracker.id)
            ).all()
            places = []
            for t in trackers:
                try:
                    dest = geo.destination(t.destination_code)
                except UnknownCodeError:
                    continue
                places.append(
                    {"id": t.id, "name": dest.name, "target_days": t.target_days, "palette": palette(dest)}
                )
        return places

    def welcome_page(
        request: Request,
        n: int,
        form: dict[str, str],
        errors: list[dict] = (),
        status: int = 200,
        *,
        q: str = "",
        error: str | None = None,
    ):
        """Step n. Steps 1-3 render the profile's own fields (the same partials); step 4 the add-place box."""
        context = {"step": onboarding.STEPS[n - 1], "steps": onboarding.STEPS, "error": error}
        if n < onboarding.LAST_STEP:
            context |= profile_context(form, list(errors))
            homes = [form.get("home_airport", ""), form.get("nearby_airports", "")]
            context["airports"] = chip_items(", ".join(h for h in homes if h), "airports")
        else:
            with session_scope(engine) as s:
                user = signed_in_user(s, request)
                user_id = user.id
            places = welcome_places(user_id)
            q = q.strip()
            context |= {
                "places": places,
                "full": len(places) >= onboarding.MAX_PLACES,
                "q": q,
                "matches": catalog.search(q) if q else [],
                "place_action": "/welcome/4",
                "search_action": "/welcome/4",
            }
        return page(request, "welcome.html", status, **context)

    @app.get("/welcome")
    def welcome(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            n = onboarding.first_unfinished(signed_in_user(s, request))
        return redirect(f"/welcome/{n}")

    @app.get("/welcome/{n}")
    def welcome_step(request: Request, n: WELCOME_STEP, q: str = ""):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if not onboarding.reachable(user, n):
                return redirect(f"/welcome/{onboarding.first_unfinished(user)}")
            form = profile_to_form(s, user)
        return welcome_page(request, n, form, q=q)

    @app.post("/welcome/{n}")
    async def welcome_save(request: Request, n: WELCOME_STEP):
        """Next on step n saves that step; "skip" (steps 2-4) finishes onboarding as things stand."""
        email = current_email(request)
        if not email:
            return signed_out(request)
        raw = await request.form()
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if not onboarding.reachable(user, n):
                if wants_json(request):
                    return json_error(409, "Finish the earlier steps first.")
                return redirect(f"/welcome/{onboarding.first_unfinished(user)}")
            skip = n > 1 and "skip" in raw
            if skip:
                onboarding.finish(user)
        if skip:
            return json_or_redirect(request, "/", next="/")
        if n == 1:
            return welcome_airports(request, email, str(raw.get("airports", "")))
        if n == onboarding.LAST_STEP:
            return welcome_places_step(request, email, raw)
        # Steps 2 and 3 are the profile's Time off and Travel style sections, saved the same way.
        section = "time_off" if n == 2 else "travel"
        fields = {k: str(v) for k, v in raw.items() if k in SECTIONS[section]}
        return welcome_saved(request, email, n, section_form(email, {**fields, "section": section}))

    def welcome_saved(request: Request, email: str, n: int, form: dict[str, str]) -> Response:
        """Validate the step's merged profile like the profile page does; save it and go to the next step."""
        profile, errors = checked_profile(form, email)
        if profile is None:
            if wants_json(request):
                return field_errors_json(errors)
            return welcome_page(request, n, form, errors, 400)
        try:
            with session_scope(engine) as s:
                user = s.scalar(select(User).where(User.email == email))
                if user is None:  # step 1 makes the user
                    u = profile.user
                    home, country, calendar = u["home_airport"], u["country"], u["holiday_calendar"]
                    user = onboarding.create_user(s, email, home, profile.nearby_airports, country, calendar)
                else:
                    apply_profile(s, profile, replace_plan=False)
                onboarding.step_done(user, n)
        except IntegrityError as exc:  # validated, so not expected: say so rather than move on unsaved
            # Only the constraint's name: the error's detail can quote the row, email and all.
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            log.error("welcome step %s not saved: constraint %s", n, constraint)
            message = "That didn't save. Check your choices and try again."
            html = lambda: welcome_page(request, n, form, status=400, error=message)  # noqa: E731
            return rejected(request, message, html)
        url = f"/welcome/{n + 1}"
        return json_or_redirect(request, url, next=url)

    def welcome_airports(request: Request, email: str, raw: str) -> Response:
        """Step 1: one chip list, the home airport first. A new home country brings its holiday calendar."""
        codes = onboarding.airport_codes(api.resolve_airports(catalog, raw))
        fields = {
            "section": "airports",
            "home_airport": codes[0] if codes else "",
            "nearby_airports": ", ".join(codes[1:]),
        }
        found = catalog.get(codes[0]) if codes else None
        with session_scope(engine) as s:
            user = s.scalar(select(User).where(User.email == email))
            country = user.country if user else None
        if found and found.country != country:
            home_country, calendar = onboarding.home_country(found.country, calendar_codes())
            fields |= {"country": home_country, "holiday_calendar": calendar}
        if country is None:
            fields |= {
                "pto_days_total": str(onboarding.START_PTO_DAYS),
                "max_trip_days": str(onboarding.START_MAX_TRIP_DAYS),
            }
        return welcome_saved(request, email, 1, section_form(email, fields))

    def welcome_places_step(request: Request, email: str, raw) -> Response:
        """Step 4: add a place (code + airports + target_days), remove one, or Start planning."""
        with session_scope(engine) as s:
            user = s.scalar(select(User).where(User.email == email))
            user_id = user.id
            count = len(onboarding.active_tracker_ids(s, user))

        def again(message: str) -> Response:
            return rejected(request, message, lambda: welcome_page(request, 4, {}, status=400, error=message))

        if "code" in raw:
            if count >= onboarding.MAX_PLACES:
                return again("That's five places, plenty to start. Add more any time from Destinations.")
            try:
                target_days = int(str(raw.get("target_days") or 10))
            except ValueError:
                target_days = 0  # explained as out of range
            airports = [str(a) for a in raw.getlist("airports")]
            added = add_place_for(user_id, str(raw["code"]), airports, target_days)
            if isinstance(added, str):
                return again(added)
            return json_or_redirect(request, "/welcome/4", tracker_id=added)
        if "remove" in raw:
            tracker_id = int(raw["remove"]) if str(raw["remove"]).isdigit() else 0
            try:
                with session_scope(engine) as s:
                    ok = 0 < tracker_id < 2**31 and remove_destination(
                        s, s.get(User, user_id), tracker_id, today=today()
                    )
            except ValueError as exc:
                return again(str(exc))
            if not ok:
                return missing(request, "No such destination.")
            return json_or_redirect(request, "/welcome/4")
        if count == 0:
            return again("Add at least one place to start planning.")
        try:
            with session_scope(engine) as s:
                year = onboarding.start_planning(s, s.get(User, user_id), today())
        except ValueError as exc:
            return again(str(exc))
        return json_or_redirect(request, f"/plan/{year}", year=year)

    # --- snooze links from the digest ------------------------------------------------------------

    def action_context(s, token: str):
        action = read_action_token(settings.secret_key, token)
        tracker = s.get(Tracker, action.tracker_id)
        if tracker is None:
            raise TokenError("this tracker no longer exists")
        return action, tracker, current_geo().destination(tracker.destination_code).name

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
