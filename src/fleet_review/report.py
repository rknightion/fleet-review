"""Markdown report and stdout summary."""

from __future__ import annotations

from fleet_review.model import ATTENTION, SKIPPED, CheckResult
from fleet_review.review import Review


def stdout_summary(rev: Review) -> str:
    return "\n".join(r.summary_line() for r in rev.results)


def markdown(rev: Review) -> str:
    out: list[str] = ["# fleet-review", ""]
    n = rev.files_in_scope
    out.append(
        f"Base `{rev.base_ref}` (merge-base `{rev.merge_base[:12]}`), "
        f"{n} changed source file{'s' if n != 1 else ''} in scope."
    )
    out.append("")
    out.append("Advisory only: this reports what the change introduced, it does not gate anything.")
    out.append("")
    for r in rev.results:
        out += _section(r, rev)
    return "\n".join(out).rstrip() + "\n"


def _section(r: CheckResult, rev: Review) -> list[str]:
    title = r.name.capitalize()
    if r.status == SKIPPED:
        return [f"## {title}: skipped", "", f"Reason: {r.reason}", ""]
    if r.status != ATTENTION:
        extra = f" ({r.detail})" if r.detail else ""
        return [f"## {title}: ok{extra}", ""]
    out = [f"## {title}: attention ({len(r.findings)})", ""]
    if r.name == "duplication":
        out += _duplication(r)
    else:
        out += _complexity(r, rev)
    return out


def _duplication(r: CheckResult) -> list[str]:
    out: list[str] = []
    for group, heading in (
        ("within_change", "Within this change"),
        ("repeats_existing", "Repeats existing code"),
    ):
        items = [f for f in r.findings if f["group"] == group]
        if not items:
            continue
        out += [f"### {heading}", ""]
        for f in items:
            where = f" in `{f['function']}`" if f["function"] else ""
            partner = f"`{f['partner']['function']}`" if f["partner"]["function"] else ""
            via = f" (partner {partner})" if partner else ""
            out.append(f"- `{f['message']}`{where}{via}")
            for a in f["also"]:
                p = a["partner"]
                out.append(
                    f"  - also `{a['file']}:{a['start']}-{a['end']}` repeats "
                    f"`{p['file']}:{p['start']}-{p['end']}` ({a['lines']} lines)"
                )
        out.append("")
    return out


def _complexity(r: CheckResult, rev: Review) -> list[str]:
    out: list[str] = []
    grown = [f for f in r.findings if f["kind"] == "grown"]
    new = [f for f in r.findings if f["kind"] == "new_over_threshold"]
    if grown:
        out += ["### Existing functions that got more complex", ""]
        for f in grown:
            out.append(
                f"- `{f['file']}:{f['line']}` `{f['function']}`: "
                f"CCN {f['base_ccn']} -> {f['head_ccn']} (+{f['head_ccn'] - f['base_ccn']})"
            )
        out.append("")
    if new:
        out += [f"### New functions over CCN {rev.cfg.new_function_ccn}", ""]
        for f in new:
            out.append(f"- `{f['file']}:{f['line']}` `{f['function']}`: CCN {f['head_ccn']}")
        out.append("")
    return out
