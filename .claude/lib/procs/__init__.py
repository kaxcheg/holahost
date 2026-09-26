"""Shared code of the Claude Code procedures: guards, deterministic sub-procedures, validation tooling.

Only code used by a hook or by two or more procedures lives here; a script with a single consumer stays
next to its skill. Nothing in this package may import a third-party module: guards run as `python3 -I -S`.
"""
