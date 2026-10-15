"""Mode dispatch never silently chooses or promotes a representation."""
from .prompt import guard, v017, v019

MODES = ("v017-structured", "v018-guarded", "v019-independent")


def render_input(context: dict, *, mode: str) -> dict:
    if mode == "v017-structured":
        return {
            "representation": v017.CONTRACT,
            "messages": v017.render_messages(v017.map_input(context)),
        }
    if mode == "v018-guarded":
        return {
            "representation": v017.CONTRACT,
            "messages": guard.render_input(context),
        }
    if mode == "v019-independent":
        return v019.render_independent_candidate(context)
    raise ValueError(f"Unknown mode {mode!r}; choose one of {MODES}")
