# Vulture per-symbol allowlist for symbols that are dynamically used (FastAPI
# dependency injection, SQLAlchemy ORM attributes, signal handlers, etc).
#
# How to add an entry:
#   uv run vulture --make-whitelist >> .vulture_whitelist.py
# then prune the noise and commit the rest.
#
# Each entry must be reachable from the same package layout as the original
# symbol so vulture's analysis treats it as used.

# Placeholder — populated by maintainers as false positives accumulate.
