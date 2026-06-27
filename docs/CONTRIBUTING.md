# Contributing

## Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Production-ready code only. Direct pushes are blocked. |
| `dev` | Integration branch. All feature branches merge here first. |
| `feature/<name>` | New functionality (e.g. `feature/drift-alerts`) |
| `fix/<name>` | Bug fixes (e.g. `fix/token-hash-collision`) |

Create branches from `dev`, not from `main`.

---

## PR Workflow

1. Create a branch from `dev`
2. Make changes and push
3. Open a PR targeting `dev`
4. CI must pass (backend tests + frontend build)
5. At least one review approval required
6. Squash merge into `dev`
7. Periodically `dev` is merged to `main` for a release

---

## Conventional Commits

All commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>
```

**Types:**

| Type | When to use |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change with no behavior change |
| `test` | Adding or fixing tests |
| `chore` | Build, CI, dependency updates |
| `perf` | Performance improvement |

**Examples:**

```
feat(ml): add ADWIN drift detector to direction model
fix(auth): handle expired Google token on callback
docs(api): add WebSocket message format to API.md
refactor(ingestion): extract feature computation to features.py
test(auth): add tests for token rotation endpoint
chore(deps): bump river to 0.21.0
```

---

## Running Tests

**Backend:**
```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

**Frontend:**
```bash
cd frontend
npm run lint
npm run build  # catches type and import errors
```

---

## Code Style

**Python** — enforced by `ruff` (linting) and `black` (formatting):
```bash
cd backend
ruff check app/
black app/
```

CI will fail if either tool reports violations.

**JavaScript/JSX** — enforced by ESLint:
```bash
cd frontend
npm run lint
```

Configure your editor to run formatters on save:
- Python: Black formatter
- JS/JSX: Prettier (add to devDependencies if needed)
