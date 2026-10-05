"""Export Implementation Baseline as concise, agent-consumable Markdown context."""

from codealign.models.baseline import ImplementationBaseline


def export_agent_context(baseline: ImplementationBaseline) -> str:
    """Format an Implementation Baseline into a prompt-ready Markdown context.

    This function is purely a transport/presentation transform:
    - It does NOT perform analysis or inference.
    - It does NOT invent implementation advice or decisions.
    - It preserves developer intent, repository identity, expectations, evidence,
      unresolved references, and constraints faithfully.
    """
    lines: list[str] = []

    # Title
    title = baseline.intent.title or "Implementation Task"
    lines.append(f"# CodeAlign Implementation Context: {title}")
    lines.append("")

    # 1. Intent
    lines.append("## Intent")
    lines.append("")
    if baseline.intent.goal:
        lines.append("### Goal")
        lines.append(baseline.intent.goal)
        lines.append("")

    lines.append("### Implementation Steps")
    if baseline.intent.steps:
        for idx, step in enumerate(baseline.intent.steps, 1):
            lines.append(f"{idx}. {step}")
    else:
        lines.append("*(No sequential steps specified in plan)*")
    lines.append("")

    # 2. Repository Identity
    lines.append("## Repository")
    lines.append("")
    lines.append(f"- **Name:** {baseline.repository.name or 'Unknown'}")
    lines.append(f"- **Branch:** {baseline.repository.branch or 'Unknown'}")
    lines.append(f"- **Baseline Commit:** `{baseline.repository.commit or 'HEAD'}`")
    lines.append("")

    # 3. Expected Changes
    lines.append("## Expected Changes")
    lines.append("")
    if baseline.expectations.expected_files:
        lines.append("| File | Action | Status | Reason |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for f in baseline.expectations.expected_files:
            reason = f.reason.replace("|", "/")
            lines.append(f"| `{f.path}` | {f.action} | {f.status} | {reason} |")
    else:
        lines.append("*(No specific files identified in baseline expectations)*")
    lines.append("")

    # 4. Expected Symbols
    lines.append("## Expected Symbols")
    lines.append("")
    if baseline.expectations.expected_symbols:
        for s in baseline.expectations.expected_symbols:
            loc = (
                f" (`{s.file_path}:{s.line}`)"
                if s.file_path and s.line
                else (f" (`{s.file_path}`)" if s.file_path else "")
            )
            lines.append(f"- `{s.name}` [{s.kind}, status: {s.status}]{loc}")
    else:
        lines.append("*(No specific symbols identified in baseline expectations)*")
    lines.append("")

    # 5. Expected Tests
    if baseline.expectations.expected_tests:
        lines.append("## Expected Tests")
        lines.append("")
        for t in baseline.expectations.expected_tests:
            lines.append(f"- `{t.path}` ({t.reason})")
        lines.append("")

    # 6. Repository Evidence
    lines.append("## Repository Evidence")
    lines.append("")

    # Resolved References
    lines.append("### Resolved References")
    lines.append("")
    if baseline.evidence.resolved:
        for r in baseline.evidence.resolved:
            loc = f":{r.line}" if r.line is not None else ""
            lines.append(f"#### `{r.reference}`")
            lines.append(f"- **Target:** `{r.file_path}{loc}` ({r.kind}: `{r.symbol}`)")

            if r.callers:
                lines.append("- **Callers:**")
                for c in r.callers:
                    c_loc = f":{c.get('line')}" if c.get("line") else ""
                    lines.append(f"  - `{c.get('file_path')}{c_loc}` (`{c.get('symbol')}`)")

            if r.callees:
                lines.append("- **Callees:**")
                for c in r.callees:
                    c_loc = f":{c.get('line')}" if c.get("line") else ""
                    lines.append(f"  - `{c.get('file_path')}{c_loc}` (`{c.get('symbol')}`)")

            if r.relationships:
                lines.append("- **Relationships:**")
                for rel in r.relationships:
                    rel_type = rel.get("relation", "related")
                    src = rel.get("source_symbol", "")
                    tgt = rel.get("target_symbol", "")
                    direction = rel.get("direction", "")
                    if direction == "incoming":
                        lines.append(f"  - `{src}` -[{rel_type}]-> `{tgt}` (incoming)")
                    else:
                        lines.append(f"  - `{src}` -[{rel_type}]-> `{tgt}`")

            lines.append("")
    else:
        lines.append("*(No resolved repository references)*")
        lines.append("")

    # Unresolved References
    lines.append("### Unresolved References")
    lines.append("")
    if baseline.evidence.unresolved:
        for u in baseline.evidence.unresolved:
            lines.append(f"- **`{u.reference}`** ({u.kind}): {u.reason}")
        lines.append("")
    else:
        lines.append("*(None)*")
        lines.append("")

    # 7. Constraints
    lines.append("## Constraints")
    lines.append("")
    if baseline.constraints:
        for c in baseline.constraints:
            lines.append(f"- {c}")
    else:
        lines.append("*(No architectural constraints specified)*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"
