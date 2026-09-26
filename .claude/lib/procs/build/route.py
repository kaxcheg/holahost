"""`/build-start` steps 1–3 as a computation: parse the arguments, pick Path A or B, find the spec, plan the load.

What the procedure leaves to judgement stays out of here: whether a backlog group IS the requested layer, which
user stories a ticket without a US id relates to, and any stage whose heading could not be told apart.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path

from procs.build import session, spec
from procs.build.model import BUILD_STATE_DIR, SESSION_FILE, TICKET_FILES, Layer
from procs.core import mdsections

RERUN_HINT = "/build-start <ticket-id> [<ticket-id>...] <layer>"


class RouteKind(StrEnum):
    PATH_A = auto()
    PATH_B = auto()
    STOP = auto()
    ASK = auto()


LAYERS = " | ".join(layer.value for layer in Layer)


@dataclass(frozen=True, slots=True)
class Args:
    spec_paths: tuple[str, ...]
    ticket_ids: tuple[str, ...]
    layer: Layer | None
    not_a_layer: str | None = None  # a final token that is neither a layer nor shaped like a ticket id

    @property
    def ticket_id(self) -> str | None:
        """Several ticket ids are one combined id for every state file and command: `B-06 B-07` → `B-06-B-07`."""
        return "-".join(self.ticket_ids) if self.ticket_ids else None


def parse_args(line: str) -> Args:
    """A token with a `/` or ending in `.md` is the spec path — ticket ids and layers never look like that.
    Of the rest, a final token naming a layer is the layer; everything before it is ticket ids. A final token after
    a ticket id that carries no digit is a mistyped layer (`T-05 domian`), not one more ticket."""
    tokens = line.split()
    specs = tuple(t for t in tokens if "/" in t or t.endswith(".md"))
    rest = [t for t in tokens if t not in specs]
    layer = Layer.parse(rest[-1]) if rest else None
    if layer is not None:
        rest = rest[:-1]
    elif len(rest) > 1 and not any(ch.isdigit() for ch in rest[-1]):
        return Args(specs, tuple(rest[:-1]), None, rest[-1])
    return Args(specs, tuple(rest), layer)


@dataclass(frozen=True, slots=True)
class Route:
    kind: RouteKind
    ticket_id: str | None = None
    ticket_ids: tuple[str, ...] = ()
    layer: Layer | None = None
    layer_source: str | None = None  # argument | session.md
    spec: str | None = None
    spec_source: str | None = None  # argument | docs/
    message: str | None = None
    in_progress: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())


def decide(project: Path, line: str) -> Route:
    args = parse_args(line)
    if len(args.spec_paths) > 1:
        return Route(RouteKind.ASK, message=f"Several spec-path tokens: {', '.join(args.spec_paths)}. Ask which one is the spec.")
    spec_path = args.spec_paths[0] if args.spec_paths else None
    if spec_path is not None and not (project / spec_path).is_file():
        return Route(RouteKind.STOP, message=f"Spec path `{spec_path}` not found.")
    if args.not_a_layer is not None:
        return Route(
            RouteKind.ASK,
            message=f"`{args.not_a_layer}` is not a layer ({LAYERS}). Ask which layer is meant, then re-run `{RERUN_HINT}`.",
        )
    active = tuple(session.ticket_of(s) for s in session.in_progress_sessions(project))
    notes: list[str] = []
    layer: Layer | None
    layer_source: str | None

    if args.ticket_id is not None:
        ticket, ids, layer, layer_source = args.ticket_id, args.ticket_ids, args.layer, "argument"
        path = project / BUILD_STATE_DIR / ticket / SESSION_FILE
        if not path.is_file():
            if layer is None:
                return Route(
                    RouteKind.ASK, ticket, ids, in_progress=active,
                    message=f"Ticket `{ticket}` has no session yet (Path A) and no layer was given. Ask for the layer.",
                )
            kind = RouteKind.PATH_A
        elif not session.mentions_in_progress(session.read_text(path)):
            return Route(RouteKind.STOP, ticket, ids, in_progress=active, message=f"Ticket `{ticket}` is not in_progress")
        else:
            kind = RouteKind.PATH_B
            stored = session.parse(path).layer
            if stored is not None:
                # «Path B … (layer from session.md)»: the procedure takes it without a word, so this is no NOTE —
                # a NOTE is something to settle with the user, and nothing here is open.
                ignored = f"; the argument `{layer.value}` is ignored on Path B" if layer is not None and layer is not stored else ""
                layer, layer_source = stored, f"session.md{ignored}"
            elif layer is None:
                layer_source = None
    else:
        if args.layer is not None:
            notes.append(f"layer `{args.layer.value}` was given without a ticket id")
        if not active:
            return Route(RouteKind.ASK, message="No in_progress ticket (Path A): ask the user for ticket ID(s) and layer before proceeding.")
        if len(active) > 1:
            return Route(
                RouteKind.STOP, in_progress=active,
                message=f"Several tickets are in_progress: {', '.join(active)}. Re-run with `{RERUN_HINT}`.",
            )
        ticket, ids, kind = active[0], (active[0],), RouteKind.PATH_B
        stored = session.parse(project / BUILD_STATE_DIR / ticket / SESSION_FILE).layer
        layer, layer_source = (stored, "session.md") if stored is not None else (args.layer, "argument" if args.layer else None)

    spec_source = "argument"
    if spec_path is None:
        located = spec.locate(project)
        if located.path is None:
            return Route(RouteKind.STOP, ticket, ids, layer, layer_source, message=located.message, in_progress=active)
        spec_path, spec_source = located.path, "docs/"

    # The backlog settles three things that need no judgement: the ids behind a combined ticket id, the layer of a
    # session written before session.md had a Layer field, and a ticket filed under another layer's group.
    text = session.read_text(project / spec_path)
    backlog = spec.match_stages(text)[spec.Stage.BACKLOG].best
    hits: list[spec.BacklogHit] = []
    if backlog is not None:
        ids = tuple(piece for one in ids for piece in spec.split_combined(one, text, backlog.section))
        hits = spec.backlog_hits(text, backlog.section, ids)
    # Per ticket: the layers its backlog group can stand for, when every entry of the ticket agrees; else nothing.
    filed: dict[str, frozenset[Layer]] = {}
    for one in ids:
        options = {spec.group_layers(h.group) for h in hits if h.ticket == one}
        filed[one] = next(iter(options)) if len(options) == 1 else frozenset()
    if layer is None:
        settled = set(filed.values())
        only = next(iter(settled)) if len(settled) == 1 else frozenset()
        if len(only) == 1:
            layer = next(iter(only))
            layer_source = f"backlog group of {', '.join(ids)}; session.md carries no Layer field"
        else:
            return Route(
                RouteKind.ASK, ticket, ids, spec=spec_path, spec_source=spec_source, in_progress=active,
                message=f"session.md of `{ticket}` carries no Layer field and the backlog groups do not settle it. "
                f"Ask the user for the layer, then re-run `/build-start {ticket} <layer>`.",
            )
    assert layer is not None
    for one, stands_for in filed.items():
        # Only a group that names exactly one layer contradicts the request beyond doubt.
        if len(stands_for) == 1 and layer not in stands_for:
            actual = next(iter(stands_for))
            message = f"Ticket `{one}` is in layer `{actual.value}`, not `{layer.value}`. Re-run with matching IDs."
            return Route(RouteKind.STOP, ticket, ids, layer, layer_source, spec_path, spec_source, message, active)
    return Route(kind, ticket, ids, layer, layer_source, spec_path, spec_source, None, active, tuple(notes))


def render(project: Path, route: Route) -> str:
    """The block injected into the /build-start skill. Plain text, stable for a given state of the project."""
    out = [f"ROUTE: {route.kind.value.upper()}"]
    if route.message:
        out.append(f"MESSAGE: {route.message}")
    if route.ticket_id:
        ids = f" (ids: {', '.join(route.ticket_ids)})" if len(route.ticket_ids) > 1 else ""
        out.append(f"TICKET: {route.ticket_id}{ids}")
    if route.in_progress:
        out.append(f"IN_PROGRESS: {', '.join(route.in_progress)}")
    if route.kind in (RouteKind.STOP, RouteKind.ASK):
        return "\n".join(out) + "\n"
    out.append(f"LAYER: {route.layer.value if route.layer else 'UNKNOWN'}" + (f" (from {route.layer_source})" if route.layer_source else ""))
    out.append(f"SPEC: {route.spec} (from {route.spec_source})")
    out.extend(f"NOTE: {note}" for note in route.notes)
    assert route.spec is not None and route.layer is not None
    text = session.read_text(project / route.spec)
    matches = spec.match_stages(text)
    backlog = matches[spec.Stage.BACKLOG]
    hits = spec.backlog_hits(text, backlog.best.section, route.ticket_ids) if backlog.best is not None else []
    unsettled = False  # a stage the keywords could not pin down: the model needs the heading list to do it

    def where(section: mdsections.Section) -> str:
        return f"{route.spec}:{section.start}-{section.end}"

    out.append("SECTIONS TO READ IN FULL (path:first-last — stage — heading):")
    for stage in spec.required_stages(route.layer):
        match = matches[stage]
        label = f"{stage.value} {spec.STAGE_TITLES[stage]}"
        if match.best is None:
            unsettled = True
            keys = ", ".join(spec.STAGE_KEYWORDS[stage])
            out.append(f"  UNMATCHED — {label} — no heading has the keywords ({keys}): look in HEADINGS for an analogous one")
        elif match.ambiguous:
            unsettled = True
            for i, cand in enumerate((match.best, *match.ties)):
                out.append(f"  {'or ' if i else ''}AMBIGUOUS — {where(cand.section)} — {label} — {cand.section.heading.title}")
        elif stage is spec.Stage.BACKLOG:
            continue  # one entry per ticket is read, not the section: BACKLOG ENTRIES below
        elif stage is spec.Stage.USER_STORIES:
            out.extend(_story_lines(text, match.best.section, label, route, hits, where))
        else:
            out.append(f"  {where(match.best.section)} — {label} — {match.best.section.heading.title}")
    if backlog.best is not None and not backlog.ambiguous:
        out.append("BACKLOG ENTRIES (one line per ticket; verify each sits under the requested layer's group):")
        for ticket in route.ticket_ids:
            mine = [h for h in hits if h.ticket == ticket]
            if not mine:
                out.append(f"  {ticket}: NOT FOUND by id — read {where(backlog.best.section)} and find the entry")
            for hit in mine:
                stories = f" — stories: {', '.join(hit.story_ids)}" if hit.story_ids else ""
                out.append(f"  {ticket}: {route.spec}:{hit.line} under «{hit.group or '—'}»{stories} — {hit.text}")
    if route.kind is RouteKind.PATH_B:
        out.append("TICKET FILES (read those that exist):")
        for name in TICKET_FILES:
            rel = os.path.join(BUILD_STATE_DIR, route.ticket_id or "", name)
            out.append(f"  {rel} — {'exists' if (project / rel).is_file() else 'absent'}")
    if unsettled:
        out.append("HEADINGS (line:heading — for the UNMATCHED and AMBIGUOUS stages above):")
        out.extend(f"  {line}" for line in headings_listing(project, route.spec).splitlines())
    return "\n".join(out) + "\n"


def _story_lines(
    text: str, stories: mdsections.Section, label: str, route: Route, hits: list[spec.BacklogHit], where: Callable[[mdsections.Section], str]
) -> list[str]:
    """User Stories are loaded per ticket, not as a section: the stories the backlog entries name, each with all its
    AC; for an entry that names none, the model picks them by the ticket's name and scope."""
    named = tuple(dict.fromkeys(story for hit in hits for story in hit.story_ids))
    unnamed = [t for t in route.ticket_ids if not any(h.story_ids for h in hits if h.ticket == t)]
    out: list[str] = []
    for found in spec.story_sections(text, stories, named):
        if found.section is not None:
            out.append(f"  {where(found.section)} — {label} — story {found.story_id} — {found.section.heading.title}")
        else:
            out.append(f"  STORY {found.story_id} — {label} — no heading of its own: find it inside {where(stories)} and load it with all AC")
    if unnamed:
        out.append(
            f"  STORIES BY SCOPE — {where(stories)} — {label} — {', '.join(unnamed)}: the backlog entry names no US-ID; "
            "load the stories matching the ticket's name/scope, with all AC"
        )
    return out


def headings_listing(project: Path, spec_path: str) -> str:
    """`grep -nE '^#{1,4} ' <SPEC>` minus the `#` comment lines of fenced code, which grep would have listed."""
    text = session.read_text(project / spec_path)
    return "".join(f"{h.line}:{'#' * h.level} {h.title}\n" for h in mdsections.headings(text, max_level=4))
