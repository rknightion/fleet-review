"""Source snippets used across tests."""

from __future__ import annotations


def branchy(name: str, branches: int, receiver: str = "") -> str:
    """A Go function whose CCN is `branches + 1`."""
    body = "\n".join(f"\tif x > {i} {{\n\t\ttotal += {i}\n\t}}" for i in range(branches))
    return f"func {receiver}{name}(x int) int {{\n\ttotal := 0\n{body}\n\treturn total\n}}\n"


def clone_func(name: str) -> str:
    """A 14 line function that jscpd treats as a clone of any other `clone_func`."""
    return f"""func {name}(items []string) int {{
	total := 0
	for i, it := range items {{
		if it == "" {{
			continue
		}}
		total += len(it) * i
		fmt.Println("item", it, total)
	}}
	if total > 10 {{
		return total - 10
	}}
	return total
}}
"""


def go_file(*funcs: str, imports: str = "") -> str:
    return "package internal\n" + imports + "\n" + "\n".join(funcs)
