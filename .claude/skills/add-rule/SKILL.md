---
name: add-rule
description: Add a new .claude/rules/*.md file. Use when capturing a newly learned pattern, convention, FastAPI route, LangGraph node, SQLAlchemy model, React component convention, or gotcha worth recording in rules files.
---

# Add a New Rule File

Rule files live in `.claude/rules/*.md` and auto-load when the session works on files matching their `paths:` frontmatter. Nothing loads at startup except root `CLAUDE.md` (if present), so broken paths mean silent failure.

## 1. Choose the right directory

| Scope | Location | `.claude/` parent (base for glob matching) |
|---|---|---|
| Cross-cutting (repo-wide workflow, docker/CI, conventions across both stacks) | `.claude/rules/` | repo root |
| Backend (Python / FastAPI) only | `backend/.claude/rules/` | `backend/` |
| Frontend (React / TypeScript) only | `frontend/.claude/rules/` | `frontend/` |

**Prefer nested over root.** Only put rules at the root if they genuinely apply across both stacks. A rule about FastAPI route handlers belongs in `backend/.claude/rules/`, not at the root. A rule about React component structure belongs in `frontend/.claude/rules/`.

## 2. Write `paths:` relative to the `.claude/` parent — NOT the repo root

This is the #1 mistake. Globs are matched relative to the directory that contains the `.claude/` folder.

**Correct:**

```yaml
# In backend/.claude/rules/routes.md — base is backend/
paths:
  - "app/api/routes/**"
  - "app/api/deps.py"
```

```yaml
# In frontend/.claude/rules/components.md — base is frontend/
paths:
  - "src/components/**"
  - "src/hooks/**"
```

```yaml
# In .claude/rules/ci.md (repo root) — base is the repo root
paths:
  - "backend/**"
  - "frontend/**"
  - ".github/workflows/**"
```

**Wrong (silently never matches):**

```yaml
# In backend/.claude/rules/routes.md — base is backend/, NOT the repo root
paths:
  - "backend/app/api/routes/**"   # ❌ paths from backend/ never start with "backend/"
```

If you catch yourself writing `backend/` or `frontend/` as the first segment inside a nested `.claude/rules/` file, strip it.

## 2b. Anchor paths concretely — no leading `**/` floating globs

Write each path so its **first segment is a real top-level folder under the base**. For `backend/` that is
`app/` (and within it `app/agents/`, `app/api/`, `app/core/`, `app/db/`, `app/services/`, `app/tasks/`).
For `frontend/` that is `src/` (and within it `src/components/`, `src/hooks/`, `src/services/`, `src/types/`).
A trailing `/**` ("everything under this folder") is fine and encouraged.

- **AVOID a leading `**/`** (e.g. `**/routes/**`, `**/agents/**`). It is imprecise, matches unrelated
  trees, and hides real-directory-name mismatches. Use the concrete anchored path instead:
  `app/api/routes/**`, `app/agents/**`.
- **Preserve coverage.** If a concept lives in several places, list each anchored path — don't collapse
  them back to one floating glob. e.g. the LangGraph agent spans `app/agents/graph.py`,
  `app/agents/nodes.py`, `app/agents/state.py`, `app/agents/tools.py` — list `app/agents/**`.
- **The only acceptable leading `**/`** is a genuine *type-glob* that really does apply to every file
  of a kind: `**/*.py`, `**/*.tsx`, `**/*.ts`. These stay as-is.

## 3. Filename and structure

- **Filename:** kebab-case, describes the topic (`routes.md`, `langgraph-agent.md`, `db-models.md`, `components.md`). No `.rules` suffix.
- **Frontmatter:** `paths:` is mandatory. No other fields.
- **Title:** one `# Heading` matching the topic.
- **Body:** short, declarative, rule-first. Use bold for mandates: `- **ALWAYS use X** — reason.` / `- **NEVER do Y** — reason.`
- **Examples:** include a minimal code snippet only when the rule is non-obvious from the prose.
- **No duplication:** before writing, grep existing rules for the topic — update in place rather than creating a near-duplicate.

### Template

```markdown
---
paths:
  - "<glob-relative-to-.claude-parent>"
---

# <Topic>

## <Subsection>

- **ALWAYS/NEVER ...** — <reason>.
- <Concrete guidance with file:line references when useful>.

\`\`\`<lang>
# short example only if the rule is not self-evident
\`\`\`
```

## 4. Verify before finishing

1. **Confirm every path matches real files.** For each anchored path, check its literal (pre-wildcard) prefix exists:
   ```bash
   # Example for a rule in backend/.claude/rules/ with paths: ["app/api/routes/**"]
   ls -d backend/app/api/routes | head
   ```
   If the directory/file does not exist, the path is wrong — `find backend -type d -name 'routes'` to locate the real one(s).

2. **Compare to sibling rules in the same directory.** If neighbors use anchored paths like `app/db/**` but yours uses `backend/**` or a leading `**/`, yours is wrong.

3. **Do not add the file to any index.** Individual rule files are auto-discovered; you don't register them anywhere.

## 5. When to update vs create

- **Same feature area already has a rule file** → add a new subsection to it.
- **New feature area, no existing file** → create a new rule file with `paths:` scoped to that area.
- **Rule applies to every `.py`/`.tsx` file** → add to an existing broad rule rather than creating `*-everywhere.md`.

## Common mistakes

- Prefixing paths with `backend/` or `frontend/` when the rule already lives in that stack's `.claude/` (see §2).
- Using `description:` or `name:` in frontmatter — rule files only take `paths:`. (Skill files need both `name:` and `description:`; rule files take neither.)
- Writing WHAT the code does rather than WHY the rule exists. Rules encode judgment, not documentation.
- Creating a rule for a one-off fix. Rules are for recurring patterns — if it only happens once, it belongs in a commit message.
