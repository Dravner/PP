"""MCP-сервер песочницы: рабочая копия репозитория и тесты внутри контейнера без сети.

Клиент запускает контейнер сам, разговор идёт по stdio:
    docker run -i --rm --network none ... romashka-sandbox:1
В /work/repo лежит рабочая копия, в /work/orig исходный снимок только для чтения, в /work/acceptance
приёмочные тесты, которые обвязка кладёт туда после работы агента.
"""
import difflib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from mcp.server import MCPServer

REPO, ORIG, ACCEPT = Path("/work/repo"), Path("/work/orig"), Path("/work/acceptance")
TEXT = {".py", ".md", ".txt", ".toml", ".cfg", ".json", ".yml", ".yaml"}
mcp = MCPServer("sandbox", instructions="Working copy of a Python repository. Tests run inside an isolated container.")


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts)


def inside(path):
    p = (REPO / path).resolve()
    if REPO.resolve() not in p.parents:
        raise ValueError(f"path outside the repository: {path}")
    return p


def numbered(lines, start):
    return "\n".join(f"{i:4d}  {line}" for i, line in enumerate(lines, start))


def python(args, cwd, root, timeout=60):
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-2500:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout} s"


@mcp.tool()
def list_files() -> str:
    """List all files of the repository."""
    return "\n".join(files(REPO))


@mcp.tool()
def read_file(path: str, start: int = 1, end: int = 0) -> str:
    """Read a file with line numbers. Optional start and end lines (end=0 means to the end of the file)."""
    p = inside(path)
    if not p.is_file():
        return f"no such file: {path}. Call list_files to see the files."
    lines = p.read_text(encoding="utf-8").splitlines()
    end = len(lines) if end <= 0 else min(end, len(lines))
    return numbered(lines[start - 1:end], start) or "(empty file)"


@mcp.tool()
def search(pattern: str) -> str:
    """Search the repository with a regular expression. Returns path:line: text, at most 40 hits."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"bad regular expression: {e}"
    hits = []
    for name in files(REPO):
        if Path(name).suffix in TEXT:
            for i, line in enumerate((REPO / name).read_text(encoding="utf-8").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{name}:{i}: {line.strip()}")
    return "\n".join(hits[:40]) + (f"\n... {len(hits) - 40} more" if len(hits) > 40 else "") if hits else "no matches"


@mcp.tool()
def replace_in_file(path: str, old: str, new: str) -> str:
    """Replace an exact fragment of a file with new text. The fragment must occur exactly once.
    Existing test files cannot be changed."""
    if path.startswith("tests/") and (ORIG / path).exists():
        return "refused: existing tests describe the expected behaviour and must not be changed. Fix the code, or add a new test file with write_file."
    p = inside(path)
    if not p.is_file():
        return f"no such file: {path}. Call list_files to see the files."
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    if n == 0:
        return "refused: the old text was not found. Read the file again: it may have changed after your previous edit, and whitespace must match exactly."
    if n > 1:
        lines = sorted({text[:m.start()].count("\n") + 1 for m in re.finditer(re.escape(old), text)})
        return f"refused: the old text occurs {n} times, at lines {', '.join(map(str, lines))}. Include a neighbouring line to make it unique."
    text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")
    first = text[:text.index(new)].count("\n") + 1 if new else 1
    lines = text.splitlines()
    lo, hi = max(1, first - 3), min(len(lines), first + new.count("\n") + 3)
    return f"ok, {path} now reads:\n" + numbered(lines[lo - 1:hi], lo)


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create a new test file in tests/, for example tests/test_issue_12.py. Existing files cannot be overwritten:
    use replace_in_file to change code."""
    if not re.fullmatch(r"tests/test_[a-z0-9_]+\.py", path):
        return "refused: write_file only creates new test files like tests/test_issue_12.py. Use replace_in_file to change code."
    if (ORIG / path).exists():
        return "refused: this test file already exists in the repository and must not be changed."
    inside(path).write_text(content, encoding="utf-8")
    return f"ok, created {path} ({content.count(chr(10)) + 1} lines)"


@mcp.tool()
def run_tests() -> str:
    """Run the whole test suite of the repository and return the exit code and the output."""
    code, out = python(["-m", "unittest", "discover", "-s", "tests"], REPO, REPO)
    return f"exit code {code}\n{out}"


@mcp.tool()
def diff() -> str:
    """Unified diff of the working copy against the original snapshot."""
    chunks = []
    for name in sorted(set(files(REPO)) | set(files(ORIG))):
        a = (ORIG / name).read_text(encoding="utf-8").splitlines(True) if (ORIG / name).exists() else []
        b = (REPO / name).read_text(encoding="utf-8").splitlines(True) if (REPO / name).exists() else []
        chunks += difflib.unified_diff(a, b, f"a/{name}", f"b/{name}")
    return "".join(chunks) or "no changes"


@mcp.tool()
def changed_files() -> str:
    """JSON object {path: new content} with every file that differs from the original snapshot."""
    out = {}
    for name in files(REPO):
        new = (REPO / name).read_text(encoding="utf-8")
        if not (ORIG / name).exists() or (ORIG / name).read_text(encoding="utf-8") != new:
            out[name] = new
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def new_tests_on_original() -> str:
    """Run the test files added by the agent against the original code. A good regression test fails here."""
    added = [n for n in files(REPO) if n.startswith("tests/") and not (ORIG / n).exists()]
    if not added:
        return "exit code 5\nno new test files"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        shutil.copytree(ORIG, root)
        for name in added:
            shutil.copy(REPO / name, root / name)
        code, out = python(["-m", "unittest", *[n[:-3].replace("/", ".") for n in added]], root, root)
    return f"exit code {code}\n{out}"


@mcp.tool()
def run_acceptance(name: str) -> str:
    """Run a hidden acceptance test from /work/acceptance against the working copy."""
    test = ACCEPT / f"{name}.py"
    if not test.is_file():
        return f"no acceptance test {name}"
    code, out = python([str(test)], REPO, REPO)
    return f"exit code {code}\n{out}"


if __name__ == "__main__":
    mcp.run()
