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
feat(ml): add ADWIN drift detector to all 10 models
fix(auth): handle expired Google token on callback
docs(api): add WebSocket message format to API.md
refactor(ingestion): extract feature computation to features.py
test(models): add tests for personal model blend weight computation
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
npm run build
```

---

## Code Style

**Python** — enforced by `ruff` (linting) and `black` (formatting):
```bash
cd backend
ruff check app/
black app/
```

**JavaScript/JSX** — enforced by ESLint:
```bash
cd frontend
npm run lint
```

---

## Adding a New Model Personality

To add an 11th (or any additional) model personality:

1. Create `backend/app/services/ml/models/your_model.py`
   - Implement the `BaseModel` interface: `predict_one(x)`, `learn_one(x, y)`, `reset()`, `get_settings()`, `update_settings(settings_dict)`
   - Choose a River algorithm appropriate for the personality
2. Register it in `backend/app/services/ml/pipeline.py` `MODEL_REGISTRY` dict with a unique string key
3. Add its default settings schema to `backend/app/models/model_settings.py`
4. Add the model's personality description to `docs/ML.md`
5. The model will automatically appear in the dashboard model grid on next backend restart — no frontend changes needed
