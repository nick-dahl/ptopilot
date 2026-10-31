"""The guided /welcome flow (spec §3.2): four short steps that build a new traveler's profile.

1. airports, 2. time off, 3. travel style, 4. destinations, then "Start planning" opens the planner.
Each step saves when Next is pressed. How far someone got is stored on the user (users.welcome_step, the
furthest step finished), so leaving halfway and coming back on another browser resumes at the next step.
Finishing (Start planning, or Skip for now on steps 2-4) sets users.onboarded_at; until then / and
/profile send the person here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, null, select
from sqlalchemy.orm import Session

from ptopilot.db.models import Tracker, User
from ptopilot.planning import current_year, default_new_year, start_year

LAST_STEP = 4
MAX_PLACES = 5  # step 4 starts small; Destinations takes more any time
# A new user's starting values (everything else takes the users table's server defaults).
START_PTO_DAYS = 15
START_MAX_TRIP_DAYS = 14


@dataclass(frozen=True)
class Step:
    n: int
    short: str  # the progress bar's label
    heading: str
    why: str


STEPS = (
    Step(
        1, "Airports", "Where do you fly from?",
        "Your home airport goes first, then any others you'd happily get to. We search them all.",
    ),
    Step(
        2, "Time off", "Your time off",
        "We count your PTO and holidays, so every trip we find fits the days you really have.",
    ),
    Step(
        3, "Travel style", "How you like to travel",
        "So we only bring you trips you'd actually take: the right length, weather and stops.",
    ),
    Step(
        4, "Places", "Where would you love to go?",
        "Pick one to five places to start. ptopilot watches their fares for you.",
    ),
)  # fmt: skip


def needs_welcome(user: User | None) -> bool:
    """No profile yet, or one the welcome flow started and nobody finished."""
    return user is None or user.onboarded_at is None


def first_unfinished(user: User | None) -> int:
    return 1 if user is None else min(user.welcome_step + 1, LAST_STEP)


def reachable(user: User | None, n: int) -> bool:
    """A step can be opened once the ones before it are done; a finished profile opens any step."""
    if user is None:
        return n == 1
    return user.onboarded_at is not None or n <= first_unfinished(user)


def airport_codes(raw: str) -> list[str]:
    """The step-1 chips as codes, in order and each once: the first is the home airport."""
    return list(dict.fromkeys(part.strip().upper() for part in (raw or "").split(",") if part.strip()))


def new_user(email: str, home: str, nearby: list[str], country: str, calendar: str) -> User:
    """Step 1's user: the airports, the home airport's country and calendar, and the starting numbers."""
    return User(
        email=email,
        home_airport=home,
        nearby_airports=nearby,
        country=country,
        holiday_calendar=calendar,
        pto_days_total=START_PTO_DAYS,
        max_trip_days=START_MAX_TRIP_DAYS,
        onboarded_at=null(),  # NULL outright: a plain None would let the model's "onboarded now" default in
        welcome_step=1,
    )


def step_done(user: User, n: int) -> None:
    user.welcome_step = max(user.welcome_step, n)


def finish(user: User) -> None:
    if user.onboarded_at is None:
        user.onboarded_at = func.now()


def active_tracker_ids(s: Session, user: User) -> list[int]:
    return list(
        s.scalars(
            select(Tracker.id)
            .where(Tracker.user_id == user.id, Tracker.active.is_(True))
            .order_by(Tracker.id)
        )
    )


def start_planning(s: Session, user: User, today: date) -> int:
    """Step 4's finish: the planning year /plan/new would start, with every place added, made the same way.

    Raises ValueError (planning.start_year's) if the year can't be started."""
    existing = current_year(s, user, today)
    year = existing.year if existing else default_new_year(s, user, today)
    start_year(s, user, year, user.pto_days_total, 0, active_tracker_ids(s, user), today=today)
    step_done(user, LAST_STEP)
    finish(user)
    s.flush()
    return year
