"""llmcat CLI - format any codebase for AI assistants."""

import os
import sys
import fnmatch
import argparse
import subprocess
from pathlib import Path

# Token estimation: ~4 chars per token (rough GPT/Claude average)
CHARS_PER_TOKEN = 4

# File extensions we care about (text/code files)
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rb", ".rs", ".php", ".swift", ".kt", ".scala", ".r",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env.example",
    ".md", ".mdx", ".rst", ".txt", ".xml", ".svg",
    ".sql", ".graphql", ".proto",
    ".dockerfile", ".dockercompose",
    ".tf", ".tfvars",
    ".vue", ".svelte", ".astro",
    ".lua", ".ex", ".exs", ".erl", ".clj", ".hs", ".ml",
}

# Always-include filenames regardless of extension
ALWAYS_INCLUDE = {
    "dockerfile", "makefile", "rakefile", "gemfile", "procfile",
    "readme", "license", "contributing", "changelog", ".env.example",
    "package.json", "pyproject.toml", "cargo.toml", "go.mod", "go.sum",
    "requirements.txt", "setup.py", "setup.cfg",
}

# Default ignore patterns (like .gitignore defaults)
DEFAULT_IGNORE = [
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    "venv", ".venv", "env", ".env",
    "dist", "build", "out", ".next", ".nuxt",
    "*.pyc", "*.pyo", "*.pyd", "*.so", "*.dylib", "*.dll",
    "*.class", "*.jar",
    "*.min.js", "*.min.css", "*.map",
    ".DS_Store", "Thumbs.db",
    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.ico", "*.svg",
    "*.mp3", "*.mp4", "*.avi", "*.mov",
    "*.zip", "*.tar", "*.gz", "*.rar",
    "*.pdf", "*.doc", "*.docx",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "*.lock", "*.log",
    "coverage", ".coverage", "htmlcov",
    ".idea", ".vscode", "*.iml",
]

MAX_FILE_SIZE_KB = 500  # Skip files larger than this


def load_gitignore_patterns(root: Path) -> list:
    """Load patterns from .gitignore if it exists."""
    patterns = []
    gitignore = root / ".gitignore"
    if gitignore.exists():
        for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def should_ignore(path: Path, root: Path, ignore_patterns: list) -> bool:
    """Check if a path should be ignored based on patterns."""
    rel = path.relative_to(root)
    parts = rel.parts

    for pattern in ignore_patterns:
        # Match against each path component
        for part in parts:
            if fnmatch.fnmatch(part.lower(), pattern.lower()):
                return True
            if fnmatch.fnmatch(part, pattern):
                return True
        # Match against full relative path
        if fnmatch.fnmatch(str(rel), pattern):
            return True
        if fnmatch.fnmatch(str(rel).replace("\\", "/"), pattern):
            return True

    return False


def is_text_file(path: Path) -> bool:
    """Check if file is a text/code file we should include."""
    name_lower = path.name.lower()
    stem_lower = path.stem.lower()

    # Check always-include names
    if name_lower in ALWAYS_INCLUDE or stem_lower in ALWAYS_INCLUDE:
        return True

    # Check extension
    suffix = path.suffix.lower()
    if suffix in CODE_EXTENSIONS:
        return True

    # No extension = might be a script (check first line)
    if not suffix:
        try:
            with open(path, "rb") as f:
                first_bytes = f.read(512)
            if b"\x00" in first_bytes:
                return False  # Binary
            first_line = first_bytes.split(b"\n")[0].decode("utf-8", errors="ignore")
            if first_line.startswith("#!"):
                return True  # Shebang script
        except Exception:
            pass

    return False


def read_file_safe(path: Path) -> str | None:
    """Read a file, returning None if it can't be read as text."""
    try:
        size_kb = path.stat().st_size / 1024
        if size_kb > MAX_FILE_SIZE_KB:
            return f"[File too large: {size_kb:.0f}KB — skipped]"
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return None


def collect_files(root: Path, extra_ignore: list = None, include_hidden: bool = False) -> list[Path]:
    """Collect all relevant files from root directory."""
    ignore_patterns = DEFAULT_IGNORE.copy()
    ignore_patterns += load_gitignore_patterns(root)
    if extra_ignore:
        ignore_patterns += extra_ignore

    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        # Skip hidden files/dirs unless requested
        parts = path.relative_to(root).parts
        if not include_hidden and any(p.startswith(".") and p not in {".env.example"} for p in parts):
            continue

        if should_ignore(path, root, ignore_patterns):
            continue

        if is_text_file(path):
            files.append(path)

    return files


def build_tree(root: Path, files: list[Path]) -> str:
    """Build a simple directory tree string from collected files."""
    lines = [f"{root.name}/"]
    rel_paths = sorted(f.relative_to(root) for f in files)

    seen_dirs = set()
    for rel in rel_paths:
        parts = rel.parts
        for i, part in enumerate(parts[:-1]):
            dir_key = parts[:i+1]
            if dir_key not in seen_dirs:
                seen_dirs.add(dir_key)
                indent = "  " * (i + 1)
                lines.append(f"{indent}{part}/")
        indent = "  " * len(parts)
        lines.append(f"{indent}{parts[-1]}")

    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def format_output(root: Path, files: list[Path], show_tree: bool = True) -> str:
    """Build the full formatted output string."""
    sections = []

    # Header
    sections.append(f"# Codebase: {root.name}")
    sections.append(f"# Generated by llmcat | {len(files)} files\n")

    # Tree
    if show_tree and files:
        sections.append("## File Structure\n```")
        sections.append(build_tree(root, files))
        sections.append("```\n")

    # Files
    sections.append("## Files\n")
    for fpath in files:
        rel = fpath.relative_to(root)
        content = read_file_safe(fpath)
        if content is None:
            continue

        ext = fpath.suffix.lstrip(".") or "text"
        sections.append(f"### {rel}\n```{ext}")
        sections.append(content.rstrip())
        sections.append("```\n")

    return "\n".join(sections)


def copy_to_clipboard(text: str) -> bool:
    """Try to copy text to clipboard. Returns True on success."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        elif sys.platform == "linux":
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["wl-copy"]]:
                try:
                    subprocess.run(cmd, input=text.encode(), check=True, capture_output=True)
                    return True
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode(), check=True, shell=True)
            return True
    except Exception:
        pass
    return False


def print_summary(files: list[Path], output: str, root: Path, copied: bool):
    """Print a nice summary to stderr."""
    tokens = estimate_tokens(output)
    chars = len(output)

    print(f"\n✓ llmcat — {root.name}", file=sys.stderr)
    print(f"  Files   : {len(files)}", file=sys.stderr)
    print(f"  Chars   : {chars:,}", file=sys.stderr)
    print(f"  ~Tokens : {tokens:,}", file=sys.stderr)

    if tokens > 200_000:
        print(f"  ⚠ Warning: May exceed some model context windows (200K tokens)", file=sys.stderr)
    elif tokens > 100_000:
        print(f"  ⚠ Note: Large context — consider using --max-files or --ignore", file=sys.stderr)

    if copied:
        print(f"  Copied  : ✓ to clipboard", file=sys.stderr)
    print("", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        prog="llmcat",
        description="Dump any codebase into perfect AI context.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  llmcat .                        # current directory → stdout
  llmcat ./my-project -c          # copy to clipboard
  llmcat . -o context.md          # save to file
  llmcat . --ignore tests docs    # skip folders
  llmcat . --max-files 30         # limit file count
  llmcat README.md src/main.py    # specific files only
        """
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to include (default: current directory)"
    )
    parser.add_argument(
        "-c", "--copy",
        action="store_true",
        help="Copy output to clipboard"
    )
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Save output to a file instead of stdout"
    )
    parser.add_argument(
        "--ignore",
        nargs="+",
        metavar="PATTERN",
        default=[],
        help="Additional patterns to ignore (e.g. tests docs *.test.js)"
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        metavar="N",
        help="Limit to N files (sorted by path)"
    )
    parser.add_argument(
        "--no-tree",
        action="store_true",
        help="Skip the file structure tree"
    )
    parser.add_argument(
        "--hidden",
        action="store_true",
        help="Include hidden files and directories"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="llmcat 0.1.0"
    )

    args = parser.parse_args()

    # Resolve paths
    input_paths = [Path(p).resolve() for p in args.paths]

    # Collect files
    all_files = []
    root = None

    for p in input_paths:
        if p.is_file():
            if root is None:
                root = p.parent
            all_files.append(p)
        elif p.is_dir():
            if root is None:
                root = p
            collected = collect_files(p, extra_ignore=args.ignore, include_hidden=args.hidden)
            all_files.extend(collected)
        else:
            print(f"⚠ Path not found: {p}", file=sys.stderr)

    if not all_files:
        print("No files found.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate & sort
    all_files = sorted(set(all_files))

    # Apply max-files limit
    if args.max_files and len(all_files) > args.max_files:
        print(f"⚠ Limiting to {args.max_files} files (from {len(all_files)} found)", file=sys.stderr)
        all_files = all_files[:args.max_files]

    if root is None:
        root = all_files[0].parent

    # Build output
    output = format_output(root, all_files, show_tree=not args.no_tree)

    # Handle output destination
    copied = False
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(output, encoding="utf-8")
        print(f"✓ Saved to {out_path}", file=sys.stderr)
    else:
        if args.copy:
            copied = copy_to_clipboard(output)
            if not copied:
                print("⚠ Clipboard copy failed — printing to stdout instead", file=sys.stderr)
                print(output)
        else:
            print(output)

    if args.copy and copied:
        pass  # Don't print to stdout if we copied
    
    print_summary(all_files, output, root, copied)

