"""Local filesystem discovery and validation for user template overrides.

Scans ``config/templates/`` for ``*.{fmt}.j2`` override files, validates them
with the sandboxed Jinja environment, and renders preview output using a sample
:class:`DigestBundle`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import jinja2

from intellisource.distributor.templates import BUILTIN_TEMPLATE_NAMES, get_template
from intellisource.distributor.templates import render as _render_module
from intellisource.distributor.templates.render import render_jinja
from intellisource.distributor.templates.schemas import (
    DigestBundle,
    DigestItem,
    DigestSection,
)


@dataclass
class OverrideIssue:
    """A single issue found while validating a template override file."""

    severity: str  # "error" | "warning"
    template: str
    fmt: str
    message: str


def list_file_overrides(
    user_dir: Path = _render_module._USER_DIR,
) -> dict[str, list[str]]:
    """Return mapping of template name → sorted list of override formats.

    Scans *user_dir* for ``{name}.{fmt}.j2`` files.  Non-existent directory
    returns an empty dict.
    """
    if not user_dir.exists():
        return {}

    result: dict[str, list[str]] = {}
    for j2_file in user_dir.glob("*.j2"):
        # Expect exactly two dots-separated suffixes: .{fmt}.j2
        suffixes = j2_file.suffixes
        if len(suffixes) < 2:
            continue
        # The last suffix must be .j2
        if suffixes[-1] != ".j2":
            continue
        fmt = suffixes[-2].lstrip(".")
        # Template name = everything before the .{fmt}.j2 suffixes
        stem = j2_file.name[: -(len(fmt) + len(".j2") + 1)]  # strip .{fmt}.j2
        if not stem or not fmt:
            continue
        if stem not in result:
            result[stem] = []
        if fmt not in result[stem]:
            result[stem].append(fmt)

    for name in result:
        result[name] = sorted(result[name])

    return result


def sample_bundle() -> DigestBundle:
    """Return a representative :class:`DigestBundle` for preview and validation."""
    pick1 = DigestItem(
        title="Sample Article: AI Advances in 2025",
        summary="A brief overview of recent developments in artificial intelligence.",
        key_points=["LLM efficiency improved", "Multimodal models proliferated"],
        why_it_matters="Affects how we build software today.",
        tags=["AI", "Technology"],
        source_name="Tech Weekly",
        source_url="https://example.com/article-1",
    )
    pick2 = DigestItem(
        title="Open Source Ecosystem Report",
        summary="Open source contributions reached a new high.",
        key_points=["Record GitHub contributions"],
        tags=["OpenSource"],
        source_name="Dev Digest",
        source_url="https://example.com/article-2",
    )
    section = DigestSection(
        heading="Technology",
        items=[pick1, pick2],
    )
    return DigestBundle(
        title="Sample Daily Digest",
        period_label="2025-01-01",
        intro="Welcome to today's curated digest.",
        top_picks=[pick1, pick2],
        sections=[section],
        timeline=[{"date": "2025-01-01", "event": "Sample event milestone"}],
        outro="See you tomorrow!",
    )


def _make_validation_env(user_dir: Path) -> jinja2.sandbox.SandboxedEnvironment:
    """Build a sandboxed Jinja environment scoped to *user_dir* for validation."""
    from jinja2.sandbox import SandboxedEnvironment

    def _autoescape(template_name: str | None) -> bool:
        return template_name is not None and template_name.endswith(".html.j2")

    return SandboxedEnvironment(
        loader=jinja2.FileSystemLoader(
            [str(user_dir), str(_render_module._BUILTIN_DIR)]
        ),
        autoescape=_autoescape,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def validate_overrides(
    user_dir: Path = _render_module._USER_DIR,
    only: str | None = None,
) -> list[OverrideIssue]:
    """Validate override files in *user_dir*.

    When *only* is given, restrict validation to that template name; otherwise
    validate every override. For each ``{name}.{fmt}.j2`` file:

    - Attempts a trial render with :func:`sample_bundle`; captures Jinja errors
      as ``error``-severity issues.
    - If the template name is not in :data:`BUILTIN_TEMPLATE_NAMES`, emits a
      ``warning``-severity issue (silent-ignore at render time).
    """
    overrides = list_file_overrides(user_dir=user_dir)
    if only is not None:
        overrides = {n: fmts for n, fmts in overrides.items() if n == only}
    issues: list[OverrideIssue] = []
    bundle = sample_bundle()
    env = _make_validation_env(user_dir)

    for name, formats in overrides.items():
        for fmt in formats:
            # Check name against built-ins first (warning, always)
            if name not in BUILTIN_TEMPLATE_NAMES:
                issues.append(
                    OverrideIssue(
                        severity="warning",
                        template=name,
                        fmt=fmt,
                        message=(
                            f"'{name}' 未匹配任何内置模板名，"
                            "疑似 kebab/snake 拼写错误，渲染时会被静默忽略"
                        ),
                    )
                )

            # Trial render to catch syntax / security errors
            template_file = f"{name}.{fmt}.j2"
            try:
                tmpl = env.get_template(template_file)
                tmpl.render(bundle=bundle)
            except jinja2.TemplateSyntaxError as exc:
                issues.append(
                    OverrideIssue(
                        severity="error",
                        template=name,
                        fmt=fmt,
                        message=str(exc),
                    )
                )
            except jinja2.exceptions.SecurityError as exc:
                issues.append(
                    OverrideIssue(
                        severity="error",
                        template=name,
                        fmt=fmt,
                        message=str(exc),
                    )
                )
            except jinja2.TemplateError as exc:
                issues.append(
                    OverrideIssue(
                        severity="error",
                        template=name,
                        fmt=fmt,
                        message=str(exc),
                    )
                )

    return issues


def render_preview(name: str, fmt: str | None) -> str:
    """Render a preview of *name* template in *fmt* using :func:`sample_bundle`.

    Resolves *fmt* using the template's ``default_format`` when *fmt* is
    ``None`` or not in ``template.formats``.  Raises :class:`ValueError` for
    unknown template names.
    """
    template = get_template(name)  # raises ValueError if unknown

    if fmt is None or fmt not in template.formats:
        chosen_fmt = template.default_format
    else:
        chosen_fmt = fmt

    bundle = sample_bundle()
    return render_jinja(name, chosen_fmt, bundle)
