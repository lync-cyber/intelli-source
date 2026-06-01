"""Project-root and env-file path resolution — single anchoring point.

Call sites that need the repository root (config dirs, the ``docker/.env``
file, compose file location) resolve it here instead of relying on the
current working directory. A ``cataforge``-style global helper keeps the
``parents[N]`` index in one place so moving a consumer file never silently
breaks anchoring.
"""

from __future__ import annotations

import os
import pathlib

# This file lives at src/intellisource/core/paths.py:
#   parents[0] = .../src/intellisource/core
#   parents[1] = .../src/intellisource
#   parents[2] = .../src
#   parents[3] = repository root
_REPO_ROOT_DEPTH = 3


def project_root() -> pathlib.Path:
    """Return the repository root as an absolute path.

    ``IS_PROJECT_ROOT`` overrides the ``__file__``-based anchor for installs
    where the source tree no longer sits under the repo (e.g. site-packages).
    """
    override = os.environ.get("IS_PROJECT_ROOT")
    if override:
        return pathlib.Path(override).resolve()
    return pathlib.Path(__file__).resolve().parents[_REPO_ROOT_DEPTH]


def resolve_env_file() -> pathlib.Path | None:
    """Return the ``.env`` file Settings/bootstrap should load.

    ``IS_ENV_FILE`` overrides the default ``<root>/docker/.env``. The path is
    returned even when the file is absent — pydantic-settings and
    ``dotenv_values`` both tolerate a missing file by yielding nothing.

    Test isolation (not reading a developer's real, gitignored ``docker/.env``)
    is the test ``conftest``'s job, which stubs the ``settings`` module's
    reference to this function. Production resolution stays pure here.
    """
    override = os.environ.get("IS_ENV_FILE")
    if override:
        return pathlib.Path(override)
    return project_root() / "docker" / ".env"
