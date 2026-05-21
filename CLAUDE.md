<!-- BEGIN COWORKER DELEGATION -->

## Coworker Delegation Tools

Delegation tools route bulk I/O tasks to a cheap worker model, preserving expensive-model tokens for reasoning. Use these tools whenever the task is large, repetitive, or read-heavy — not when it requires judgment, debugging, or architecture decisions.

---

### `ask-kimi` — Read-heavy analysis and Q&A

**When to use:** files >400 lines OR 3+ files at once. Any bulk read task where you would otherwise spend many tokens just ingesting content.

**Usage:**

```
use the Bash tool to run ask-kimi <file1> <file2> ... --question "<question>"
```

**Examples:**
- Summarise a large module: use the Bash tool to run `ask-kimi src/core.py --question "What does this module do and what are its public interfaces?"`
- Cross-file audit: use the Bash tool to run `ask-kimi src/ tests/ --question "List every place error handling is missing"`

`ask-kimi` accepts files and directories. Directories are expanded recursively while skipping common noisy paths such as `.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, and `build`. Generated content prints to stdout; usage, finish reason, token counts, file count, and byte count print to stderr. Use `--dry-run` to inspect the resolved file set before calling the API.

---

### `kimi-write` — Boilerplate, tests, docs, and repetitive patterns

**When to use:** generating new files that follow a clear pattern (unit tests, docstrings, configuration stubs, changelog entries, repetitive transformations). The task must have a well-defined output format and a reference file the worker can imitate.

**Usage:**

```
use the Bash tool to run kimi-write --spec "<what to write>" --context <ref_file> --target <output_path>
```

**Examples:**
- Generate unit tests: use the Bash tool to run `kimi-write --spec "pytest unit tests for all public functions" --context src/parser.py --target tests/test_parser.py`
- Write a changelog entry: use the Bash tool to run `kimi-write --spec "CHANGELOG entry for v1.2.0 based on recent commits" --context CHANGELOG.md --target docs/changelog-entry.md`

---

### `extract-chat` — Strip JSONL transcripts to readable text

**When to use:** before passing session context to `ask-kimi` or `kimi-write` for documentation updates. Do not read raw JSONL transcripts yourself; extract them first.

**Usage:**

```
use the Bash tool to run extract-chat <transcript.jsonl> [--output <readable.txt>]
```

**Example:**
- Extract a session transcript to readable text: use the Bash tool to run `extract-chat ~/.claude/projects/my-project/session.jsonl --output /tmp/session.txt`

---

### Doc-update pipeline (MANDATORY)

**Never write documentation directly token-by-token.** Always use the extract → delegate → apply pipeline:

1. **Extract:** use the Bash tool to run `extract-chat <session.jsonl> --output context.txt` to get clean conversation text
2. **Delegate:** use the Bash tool to run `ask-kimi context.txt existing-doc.md --question "Produce the updated doc as a unified diff"` (or use `kimi-write` if generating from scratch)
3. **Apply:** apply the diff or write the output to the target file

This pipeline keeps doc-writing token costs near zero and ensures the output is grounded in the actual session transcript rather than your reconstruction of it.

---

### When NOT to delegate

Do not use delegation tools for:

- **Tasks estimable at fewer than ~2000 tokens** — the overhead of spawning a worker exceeds the savings. Just do it inline.
- **Debugging sessions** — requires tight read-modify-verify loops that the worker cannot do. Stay in-context.
- **Architecture and design decisions** — judgment about trade-offs belongs to you, not the worker.
- **Safety-critical code** — security logic, auth, cryptography, data integrity. Never delegate these writes.
- **Anything requiring exact line numbers** — the worker may paraphrase or reformat output. Use your own read for precise locations.
- **Tasks where the prompt itself requires more context than the answer** — if constructing the `--question` flag takes more work than answering it, skip the delegation.

<!-- END COWORKER DELEGATION -->
