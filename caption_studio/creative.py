"""Offline copy generation.

Your catalog knows *what* you have (title, year, genre, season/episode counts,
runtimes, resolutions) but nothing about the story.  This module turns those
facts into publishable promo copy using per-genre playbooks.

Every generator is deterministic: the same title always produces the same
caption, so you can regenerate safely.  Pass ``variant=N`` to roll a different
version of the wording.
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Dict, List

from .models import Title

# ---------------------------------------------------------------------------
# Genre playbooks
# ---------------------------------------------------------------------------
# Each entry: hooks (paragraph openers), expects (the ✅ bullets),
# whys (the "why we recommend it" paragraph) and taglines.
# Placeholders: {title} {year} {genres} {seasons} {episodes} {runtime}

PLAYBOOKS: Dict[str, Dict[str, List[str]]] = {
    "Action": {
        "hooks": [
            "{title} runs on pure adrenaline — {year}'s answer to \"hold my drink\" filmmaking, and it never once lets up.",
            "A straightforward job goes sideways, and {title} turns the wreckage into {runtime} minutes of pure momentum.",
            "Bigger stunts, louder engines, and a hero with nothing left to lose — {title} doesn't believe in second gear.",
        ],
        "expects": [
            "Set pieces that escalate instead of repeat",
            "Practical stunts you can actually feel",
            "A lead who does their own damage",
            "A villain worth the bruises",
            "One-liners you'll be quoting tomorrow",
            "A finale that empties the tank",
        ],
        "whys": [
            "{title} is the kind of watch that reminds you why a big screen exists: momentum, noise, and a hero who refuses to stay down.",
            "Action this confident is rare. {title} keeps raising its own bar — then clears it.",
        ],
        "taglines": ["Loud, fast, unmissable.", "Adrenaline start to finish.", "No brakes, no filler."],
    },
    "Adventure": {
        "hooks": [
            "{title} is a proper journey — one wrong turn from disaster, and worth every step.",
            "Maps, motives and one very bad idea: {title} sends its characters somewhere they may not come back from.",
            "Big landscapes, bigger stakes. {title} treats the world itself as the main character.",
        ],
        "expects": [
            "Locations that do half the storytelling",
            "Stakes that keep climbing",
            "A crew you actually care about",
            "Set pieces built around cleverness, not budget",
            "A finale that earns its emotion",
        ],
        "whys": [
            "Adventure done right is rare, and {title} understands that the journey only matters if you care who's taking it.",
            "{title} delivers the sweep and scale you want, without ever losing sight of the people at the centre.",
        ],
        "taglines": ["One journey. Zero regrets.", "Go further.", "Wanderlust, weaponised."],
    },
    "Animation": {
        "hooks": [
            "{title} is proof that animation isn't a genre for kids — it's a genre with no ceiling.",
            "Gorgeous, funny and sneakily mature, {title} hides real feeling underneath all that colour.",
            "{title} builds a whole world from scratch and then invites you to live in it.",
        ],
        "expects": [
            "Animation with a real point of view",
            "Gags for the kids, jokes for the adults",
            "A score that does heavy lifting",
            "Character designs you'll recognise instantly",
            "An ending that lands harder than expected",
        ],
        "whys": [
            "{title} is the rare animated title that works on every level — craft, comedy, and a story with something to say.",
            "Beautiful to look at and sharper than it needs to be, {title} is an easy recommendation for basically anyone.",
        ],
        "taglines": ["Drawn to perfection.", "Not just for the kids.", "A whole world, frame by frame."],
    },
    "Anime": {
        "hooks": [
            "{title} is anime at its most committed — no pacing mercy, no wasted arcs.",
            "Underneath the style is a story that takes itself seriously, and that's exactly why {title} hits.",
            "{title} builds its world patiently, and then cashes in every single thread.",
        ],
        "expects": [
            "World-building that rewards patience",
            "Fight choreography with actual stakes",
            "A soundtrack that refuses to calm down",
            "Characters who grow in uncomfortable ways",
            "Arcs that pay off seasons later",
        ],
        "whys": [
            "{title} respects its audience. Nothing is filler, and the payoffs are worth every episode.",
            "If you want anime with ambition, {title} is the easy pick — style, substance and zero hand-holding.",
        ],
        "taglines": ["Watch it. Trust us.", "No filler. All killer.", "Peak anime energy."],
    },
    "Comedy": {
        "hooks": [
            "{title} understands the oldest rule of comedy: commit fully to the bit.",
            "An ordinary situation, thoroughly ruined — {title} finds the funny in places most films walk past.",
            "{title} is the rare comedy that trusts silence as much as the punchline.",
        ],
        "expects": [
            "Jokes that land fast and often",
            "A cast clearly having the time of their lives",
            "At least one scene you'll rewind",
            "Physical comedy that isn't lazy",
            "A surprisingly soft centre",
        ],
        "whys": [
            "{title} is funny in the way that matters — it earns the laughs instead of buying them.",
            "Comedy ages badly; {title} doesn't. It's still sharp, still warm, still an easy rewatch.",
        ],
        "taglines": ["Genuinely, properly funny.", "Laugh out loud. Literally.", "Good mood, guaranteed."],
    },
    "Crime": {
        "hooks": [
            "{title} treats crime as work — paperwork, patience, and the slow erosion of everyone involved.",
            "Everyone in {title} is lying to somebody. Working out to whom is the whole pleasure.",
            "{title} knows the best crime stories aren't about the job; they're about what the job costs.",
        ],
        "expects": [
            "A case that keeps flipping",
            "Procedure you can actually follow",
            "Morally compromised, deeply watchable characters",
            "Tension built from conversation, not explosions",
            "An interrogation scene you'll replay",
        ],
        "whys": [
            "{title} is crime storytelling with a pulse — smart, patient, and interested in consequences.",
            "The details are right and the characters are messy, which is exactly why {title} holds up.",
        ],
        "taglines": ["Everyone's guilty of something.", "Follow the money.", "Case closed, eventually."],
    },
    "Documentary": {
        "hooks": [
            "{title} doesn't need to invent anything — the truth was already stranger.",
            "Meticulous, unsettling and impossible to look away from, {title} earns every minute.",
            "{title} takes a subject you thought you understood and quietly dismantles it.",
        ],
        "expects": [
            "Access you don't normally get",
            "Interviews that change the story mid-sentence",
            "Archival footage used brilliantly",
            "Zero sensationalism — it doesn't need it",
            "A final act that reframes everything",
        ],
        "whys": [
            "{title} is the definition of a documentary worth your evening: rigorous, human, and genuinely surprising.",
            "It informs and entertains at once, which is the hardest trick in non-fiction — {title} pulls it off.",
        ],
        "taglines": ["Truth, no filler.", "Stranger than fiction.", "Watch it, then talk about it."],
    },
    "Drama": {
        "hooks": [
            "{title} is quiet, patient and devastating in the way only a well-made drama can be.",
            "One decision, years of consequence — {title} understands how ordinary lives come apart.",
            "{title} trusts its characters enough to let them be contradictory, and that's what makes it hurt.",
        ],
        "expects": [
            "Performances that do the heavy lifting",
            "Conflict that comes from character, not coincidence",
            "Dialogue that sounds like actual people",
            "At least one scene you'll sit with afterwards",
            "An ending that respects you",
        ],
        "whys": [
            "{title} earns its emotions. Nothing is manipulated, and that makes the gut-punches land properly.",
            "If you want drama that treats you like an adult, {title} is the one to queue up.",
        ],
        "taglines": ["Quietly devastating.", "Stays with you.", "Acting worth the runtime."],
    },
    "Family": {
        "hooks": [
            "{title} works for the whole room — the kids get the adventure, the adults get the jokes.",
            "Families are complicated, and {title} is honest enough to make that the fun part.",
            "{title} is built for a Friday night where nobody can agree on what to watch.",
        ],
        "expects": [
            "Something in it for every age",
            "Warmth without sentimentality",
            "A soundtrack the whole house will hum",
            "Characters who feel like real relatives",
            "A message that isn't hammered home",
        ],
        "whys": [
            "Genuinely all-ages without being bland — {title} is the rare crowd-pleaser nobody has to sit through.",
            "{title} is the safe pick that never feels like a compromise.",
        ],
        "taglines": ["One for the whole house.", "Warm, funny, real.", "Family night sorted."],
    },
    "Fantasy": {
        "hooks": [
            "{title} builds a world with rules, history and consequences — then dares you to stop exploring.",
            "Magic is expensive in {title}, and every use of it costs somebody something.",
            "{title} remembers that the best fantasy is about people, not prophecies.",
        ],
        "expects": [
            "World-building with internal logic",
            "Creature and set design worth pausing on",
            "A magic system that actually costs something",
            "Political intrigue alongside the wonder",
            "A climax that pays off early promises",
        ],
        "whys": [
            "{title} treats fantasy seriously, and it shows in every detail of the world it builds.",
            "Big imagination, real discipline — {title} is escapism with a spine.",
        ],
        "taglines": ["Another world, fully built.", "Magic with consequences.", "Escape properly."],
    },
    "History": {
        "hooks": [
            "{title} takes real events and refuses to flatten them into a lesson.",
            "The details are meticulous, but {title} never forgets it's telling a human story.",
            "{title} makes the past feel immediate — same ambitions, same mistakes, higher stakes.",
        ],
        "expects": [
            "Period detail that never distracts",
            "Real events, dramatised honestly",
            "Performances grounded in real people",
            "Politics you can follow",
            "A perspective you probably haven't seen",
        ],
        "whys": [
            "{title} is history with a pulse: accurate where it matters and gripping where it counts.",
            "It's genuinely educational and genuinely entertaining — {title} never feels like homework.",
        ],
        "taglines": ["The past, vividly told.", "History without the homework.", "Based on fact. Mostly."],
    },
    "Horror": {
        "hooks": [
            "{title} understands that what you don't see is always worse.",
            "Slow dread, then absolute panic — {title} paces its scares like a professional.",
            "{title} is the horror film you watch with the lights on and still regret at 2am.",
        ],
        "expects": [
            "Dread that builds instead of cheap jump scares",
            "Sound design doing half the work",
            "At least one image you can't unsee",
            "Characters smart enough to be worth following",
            "A third act that commits",
        ],
        "whys": [
            "{title} is scary on craft rather than volume — atmosphere, patience and one hell of a final act.",
            "For horror fans who've seen it all, {title} still finds a way under the skin.",
        ],
        "taglines": ["Sleep is optional.", "Genuinely unsettling.", "Watch it with the lights on."],
    },
    "Kids": {
        "hooks": [
            "{title} is built for short attention spans and long car journeys.",
            "Bright, fast and endlessly rewatchable — {title} knows exactly who it's for.",
            "{title} keeps it simple, silly and completely charming.",
        ],
        "expects": [
            "Pacing that never loses a child",
            "Jokes that work on repeat viewing",
            "Bright, memorable characters",
            "Nothing that'll need explaining afterwards",
            "Songs you'll be stuck with for a week",
        ],
        "whys": [
            "{title} is the rare kids' title that adults won't quietly mute.",
            "Safe, silly and genuinely fun — {title} buys you a peaceful hour.",
        ],
        "taglines": ["Kids approved.", "Silly, bright, fun.", "Rewatch incoming."],
    },
    "K-Drama": {
        "hooks": [
            "{title} does what the best K-dramas do: it makes an ordinary premise feel enormous.",
            "Romance, revenge and immaculate pacing — {title} is binge-engineered.",
            "{title} takes its time, and that patience is exactly why the payoffs wreck you.",
        ],
        "expects": [
            "A premise that hooks in episode one",
            "Chemistry you can measure",
            "A soundtrack that becomes the emotional scoreboard",
            "Twists that actually reframe earlier scenes",
            "An ending that resolves properly",
        ],
        "whys": [
            "{title} is peak binge material — tight arcs, big feelings, and a soundtrack that does damage.",
            "K-drama at its best doesn't waste an episode, and {title} doesn't waste a scene.",
        ],
        "taglines": ["One more episode. Always.", "Feelings, expertly delivered.", "Binge responsibly."],
    },
    "Music": {
        "hooks": [
            "{title} is about the cost of the thing you love most.",
            "The performances are electric and the price is steep — {title} knows both.",
            "{title} treats music as work, as escape, and as the only honest thing in the room.",
        ],
        "expects": [
            "Performances filmed with real care",
            "A soundtrack you'll immediately look up",
            "Backstage detail that feels lived-in",
            "Ambition colliding with reality",
            "At least one scene that gives you chills",
        ],
        "whys": [
            "{title} is genuinely moving about what it costs to make something good.",
            "Even if the subject isn't yours, {title} wins you over on craft and feeling.",
        ],
        "taglines": ["Turn it up.", "Music, and what it costs.", "Soundtrack of the year."],
    },
    "Mystery": {
        "hooks": [
            "{title} plays fair — every clue is on screen, you just have to be quicker than the detective.",
            "A puzzle, a lie, and a reveal you won't see coming: {title} is built for people who guess along.",
            "{title} understands that a mystery is only as good as what's hiding underneath it.",
        ],
        "expects": [
            "Clues you can actually solve yourself",
            "A reveal that recontextualises earlier scenes",
            "Red herrings that feel earned",
            "An investigator worth following",
            "No cheat ending",
        ],
        "whys": [
            "{title} respects the audience — the puzzle is solvable and the payoff is fair.",
            "Clever without being smug, {title} is the kind of mystery that rewards a second watch immediately.",
        ],
        "taglines": ["Everyone's a suspect.", "Guess again.", "The reveal is worth it."],
    },
    "Reality": {
        "hooks": [
            "{title} is the definition of \"just one more episode\" — and then it's 3am.",
            "Big personalities, bigger consequences, zero script — {title} is pure telly.",
            "{title} is chaotic in the exact way that makes a weekend disappear.",
        ],
        "expects": [
            "Personalities who never dial it down",
            "Drama that escalates every episode",
            "Moments you'll describe to people who weren't there",
            "Comfort viewing at its finest",
            "Zero homework required",
        ],
        "whys": [
            "{title} is comfort chaos — nothing to track, everything to react to.",
            "Perfect background or full attention, {title} works either way.",
        ],
        "taglines": ["Chaos, curated.", "Pure comfort telly.", "One more episode. Always."],
    },
    "Romance": {
        "hooks": [
            "{title} earns its romance — the chemistry is built scene by scene, not assumed.",
            "Two people, terrible timing, and {runtime} minutes of wondering if they'll work it out.",
            "{title} is romantic without being dishonest about how messy it all is.",
        ],
        "expects": [
            "Chemistry that carries the whole thing",
            "Obstacles that feel real",
            "A supporting cast worth the detour",
            "At least one scene you'll replay",
            "An ending that actually satisfies",
        ],
        "whys": [
            "{title} is romantic in the way that works: earned, specific, and never saccharine.",
            "If you want something that leaves you warmer than you started, {title} delivers.",
        ],
        "taglines": ["Butterflies, guaranteed.", "Chemistry you can feel.", "Love, honestly told."],
    },
    "Sci-Fi": {
        "hooks": [
            "{title} uses the future to ask an uncomfortable question about right now.",
            "One impossible premise, taken completely seriously — that's why {title} works.",
            "{title} is ideas-first science fiction, and the ideas are genuinely unsettling.",
        ],
        "expects": [
            "A premise with real consequences",
            "World-building that answers your questions",
            "Practical effects and believable design",
            "A philosophical argument hiding in the plot",
            "An ending that commits to its logic",
        ],
        "whys": [
            "{title} is sci-fi that respects the science and the fiction equally.",
            "Smart, strange and completely confident — {title} is the good kind of mind-bender.",
        ],
        "taglines": ["Ideas that stick.", "The future, unsettled.", "Think harder."],
    },
    "Sitcom": {
        "hooks": [
            "{title} is the sitcom that treats chaos as a family value.",
            "Jokes arrive every few seconds and the heart sneaks up on you — {title} plays both games at once.",
            "{title} is comfort viewing with a wicked streak: familiar setup, completely unpredictable execution.",
        ],
        "expects": [
            "Jokes that land fast and often",
            "A cast with perfect comic timing",
            "Running gags that pay off seasons later",
            "Sneaky emotional moments between the laughs",
            "Episodes that work even out of order",
        ],
        "whys": [
            "{title} is the rare sitcom that's as rewatchable as it is quotable — the timing never gets old.",
            "You come for the jokes and stay for the characters, which is exactly how {title} hooks you.",
        ],
        "taglines": ["Comfort comedy at its best.", "Quotable from episode one.", "Funny, then surprisingly moving."],
    },
    "Sport": {
        "hooks": [
            "{title} knows the game is never really about the game.",
            "Underdogs, discipline and one last shot — {title} runs the playbook properly.",
            "{title} captures the part of sport nobody broadcasts: the grind in between.",
        ],
        "expects": [
            "A central performance with real weight",
            "Game sequences shot with clarity",
            "Setbacks that feel unscripted",
            "A mentor worth listening to",
            "A finale that gets you off the sofa",
        ],
        "whys": [
            "{title} is a sports story that works even if you couldn't care less about the sport.",
            "It earns its climax honestly — {title} doesn't hand anybody a shortcut.",
        ],
        "taglines": ["One last shot.", "Earned, not given.", "Get up."],
    },
    "Superhero": {
        "hooks": [
            "{title} remembers that the power is the boring part — the choice is the story.",
            "Origin, consequence and a city that never asked for any of it — {title} does the genre properly.",
            "{title} gives you the spectacle and still finds room for the person underneath the suit.",
        ],
        "expects": [
            "A villain with an actual argument",
            "Action that stays readable",
            "Stakes that aren't just 'the world'",
            "Costume and set design done with care",
            "A third act that goes somewhere",
        ],
        "whys": [
            "{title} is superhero storytelling with a brain — spectacle on top, character underneath.",
            "It's big, but it's not empty. {title} gives you something to think about after the credits.",
        ],
        "taglines": ["Power has a price.", "Cape not required.", "Big, but not empty."],
    },
    "Thriller": {
        "hooks": [
            "{title} is a slow tightening — every scene takes one more option away.",
            "One bad decision, then another, then another: {title} is a masterclass in escalation.",
            "{title} understands that tension is just information, carefully rationed.",
        ],
        "expects": [
            "Tension that builds instead of spikes",
            "Twists that reframe what you just watched",
            "Cat-and-mouse scenes with real logic",
            "A lead performance under pressure",
            "A final act that doesn't chicken out",
        ],
        "whys": [
            "{title} is genuinely tense — not because things keep exploding, but because you never quite know who's safe.",
            "Tight, mean and smartly constructed, {title} is the thriller to clear an evening for.",
        ],
        "taglines": ["Don't start it at midnight.", "Tension you can feel.", "Trust nobody."],
    },
    "War": {
        "hooks": [
            "{title} is about the waiting as much as the fighting, and it's all the stronger for it.",
            "Strategy, luck and terrible arithmetic — {title} is honest about the cost.",
            "{title} doesn't glorify anything; it just refuses to look away.",
        ],
        "expects": [
            "Battle sequences with real geography",
            "Attention to the people, not just the plan",
            "Detail that clearly took research",
            "Camaraderie that makes the losses land",
            "An anti-war argument underneath it all",
        ],
        "whys": [
            "{title} is war storytelling with integrity — technical, human and completely unglamorous.",
            "It's grim, it's meticulous, and it's one of the more honest things you'll watch this year.",
        ],
        "taglines": ["Honest, unflinching, necessary.", "The cost, shown plainly.", "No glory. Just truth."],
    },
    "Western": {
        "hooks": [
            "{title} uses the frontier the way the best westerns do: as a moral test.",
            "Law is a rumour out here, and {title} is about who decides what happens next.",
            "Wide shots, long silences and one very tired gunman — {title} knows the genre.",
        ],
        "expects": [
            "Landscape that does the heavy lifting",
            "Standoffs that earn their length",
            "A moral argument, not just a shootout",
            "Great faces, minimal dialogue",
            "A revisionist edge",
        ],
        "whys": [
            "{title} is a western with something to say — and it says it in silences as much as gunfire.",
            "Even if you think you don't like westerns, {title} has the craft to change your mind.",
        ],
        "taglines": ["Law is a rumour.", "Wide open, tightly wound.", "Old genre, new teeth."],
    },
}

GENERIC = {
    "hooks": [
        "{title} is the kind of watch that starts as background noise and ends with your full attention.",
        "Hard to categorise, easy to recommend — {title} is confidently its own thing.",
        "{title} sneaks up on you. Give it one episode and you'll be rearranging your evening.",
    ],
    "expects": [
        "A premise that hooks quickly",
        "Characters worth sticking with",
        "Craft that shows in the details",
        "Pacing that never drags",
        "An ending that sticks the landing",
    ],
    "whys": [
        "{title} is one of those titles that's easy to hand to anyone — it works whatever mood you're in.",
        "Confident, well-made and quietly addictive, {title} is exactly what a free evening needs.",
    ],
    "taglines": ["Easy to start. Hard to stop.", "Genuinely worth your evening.", "One more, always."],
}

# Non-playbook genres borrow from a close relative.
PLAYBOOK_FALLBACKS = {
    "Biography": "Drama", "Musical": "Music", "Family": "Family",
    "Crime": "Crime", "Noir": "Thriller", "Mystery": "Mystery",
}


def playbook_for(genres: List[str]) -> Dict[str, List[str]]:
    for g in genres:
        if g in PLAYBOOKS:
            return PLAYBOOKS[g]
    for g in genres:
        if g in PLAYBOOK_FALLBACKS and PLAYBOOK_FALLBACKS[g] in PLAYBOOKS:
            return PLAYBOOKS[PLAYBOOK_FALLBACKS[g]]
    return GENERIC


# ---------------------------------------------------------------------------
# Deterministic selection
# ---------------------------------------------------------------------------
def _rng(title: Title, variant: int, salt: str = "") -> random.Random:
    seed = hashlib.sha256(f"{title.name}|{title.year}|{variant}|{salt}".encode("utf-8")).hexdigest()
    return random.Random(seed)


def _pick(rng: random.Random, options: List[str], count: int) -> List[str]:
    options = list(options)
    rng.shuffle(options)
    return options[:count]


def _fill(template: str, title: Title) -> str:
    return template.format(
        title=title.name,
        year=title.year or "",
        genres=" / ".join(title.genres) if title.genres else "drama",
        seasons=title.seasons or 1,
        episodes=title.episodes or 1,
        runtime=title.runtime_min or 100,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def library_bullets(title: Title) -> List[str]:
    """Bullets derived from the files you actually have — the sales pitch."""
    out = []
    if title.is_series:
        if title.seasons > 1:
            out.append(f"All {title.seasons} seasons, complete — nothing missing")
        else:
            out.append("Complete season, no missing episodes")
        if title.episodes:
            out.append(f"{title.episodes} episodes at roughly {title.runtime_min} minutes each")
        out.append("Perfect weeknight binging — episodes that end cleanly")
    else:
        if title.runtime_min:
            out.append(f"A tight {title.runtime_min}-minute ride, no dead air")
        out.append("One file, one film — no splitting, no hunting")
    if title.resolutions:
        res = " / ".join(title.resolutions)
        out.append(f"Clean {res} copies sized for flash or phone")
    if title.subtitle_languages:
        langs = ", ".join(title.subtitle_languages[:2])
        out.append(f"Subtitles available ({langs})")
    return out


def make_hook(title: Title, variant: int = 0) -> str:
    """One-paragraph hook, used when TMDB hasn't supplied a synopsis."""
    if title.overview:
        return condense_overview(title.overview, max_sentences=2)
    book = playbook_for(title.genres)
    rng = _rng(title, variant, "hook")
    return _fill(book["hooks"][rng.randrange(len(book["hooks"]))], title)


def make_expect_bullets(title: Title, variant: int = 0, count: int = 4) -> List[str]:
    book = playbook_for(title.genres)
    rng = _rng(title, variant, "expect")
    picks = _pick(rng, book["expects"], max(count - 1, 1))
    lib = library_bullets(title)
    # Always keep one concrete, factual bullet about the actual files.
    if lib:
        picks.append(lib[rng.randrange(len(lib))])
    return picks[:count]


def make_why(title: Title, variant: int = 0) -> str:
    book = playbook_for(title.genres)
    rng = _rng(title, variant, "why")
    base = _fill(book["whys"][rng.randrange(len(book["whys"]))], title)
    if title.is_series and title.seasons > 1:
        base += f" With {title.seasons} seasons on the drive, it's a weekend solved."
    return base


def make_tagline(title: Title, variant: int = 0) -> str:
    if title.tagline:
        return title.tagline.strip()
    book = playbook_for(title.genres)
    rng = _rng(title, variant, "tagline")
    return book["taglines"][rng.randrange(len(book["taglines"]))]


_STOPWORDS = {"the", "a", "an", "of", "in", "on", "and", "or", "to", "at", "for",
              "my", "is", "it", "part", "season", "seasons", "episode", "vol",
              "chapter", "movie", "film"}


def dm_keyword(title: Title) -> str:
    """'Malcolm in the Middle' -> 'MALCOLM'; '2 Fast 2 Furious' -> 'FAST'."""
    if title.dm_keyword:
        return title.dm_keyword.strip().upper()
    words = re.findall(r"[A-Za-z0-9']+", title.name or "")
    candidates = [w for w in words if w.lower() not in _STOPWORDS and not w.isdigit()]
    if not candidates:
        candidates = words or ["VIDEO"]
    word = candidates[0]
    return re.sub(r"[^A-Z0-9]", "", word.upper()) or "VIDEO"


def condense_overview(text: str, max_sentences: int = 2, max_chars: int = 240) -> str:
    """Trim a TMDB overview down to a punchy caption-length paragraph."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(sentences[:max_sentences]).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return out
<<<<<<< HEAD
=======

>>>>>>> origin/master
