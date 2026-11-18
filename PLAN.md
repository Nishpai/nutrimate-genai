# NutriMate implementation plan

This is the working plan for the NutriMate build. It was written after looking at the
existing prototype and the raw data, before writing the new code.

## What already exists

- A separate earlier prototype (Streamlit, then Next.js) with a working constraint
  engine, a rule-based request parser and an offline evaluation. Its keyword lists and
  data cleaning rules are reused here. Its code is not copied as a whole.
- Raw data, about 1.1 GB in total:
  - Food.com recipes and reviews (DuckDB file, 522,517 recipes and 1,401,982 reviews,
    per-serving nutrition in grams).
  - Indian Nutrient Databank (INDB 2024.11, 1,014 foods, xlsx).
  - USDA FoodData Central SR Legacy (7,793 foods, CSV).

## Architecture

Two separate intelligence systems that meet in the API:

1. Traditional ML (recommendations)
   - Content model: scikit-learn TF-IDF over name, tags and ingredients plus scaled
     nutrient features, cosine similarity to a user profile vector.
   - Collaborative model: LightFM (WARP loss, matrix factorisation) trained on ratings.
   - Hybrid: weighted sum of normalised content, LightFM and popularity scores.
     Weights tuned with Optuna on a validation split.
   - Reranker: XGBoost learning-to-rank (rank:ndcg) over the hybrid's top candidates,
     using score and nutrition-fit features. It is only switched on in the app if it
     beats the plain hybrid order on a holdout of validation users. In the final run it
     did not, so the app serves the hybrid order (see "Status" below).
   - Neural CF baseline in PyTorch, used in the offline comparison.
   - Dietary constraint engine runs before ranking, so a recipe that breaks a hard rule
     never gets a score at all.
2. GenAI with RAG (assistant and plan narratives)
   - Sentence Transformers (all-MiniLM-L6-v2) embeds food and recipe descriptions.
   - FAISS finds candidate records. It stores ids and text only, no nutrition numbers.
   - MySQL is the source of truth for nutrition. Values are fetched by id after retrieval.
   - A LangGraph flow: parse intent, retrieve, fetch from MySQL, calculate and validate
     in Python, then Gemini writes the explanation (through LangChain).
   - Any number in Gemini's reply that is not in the computed facts causes the reply to
     be rejected and replaced by a deterministic template answer.
   - Without a GEMINI_API_KEY the assistant still works and is labelled as fallback mode.

## Stack decisions

- Frontend: Vite, React, TypeScript, Tailwind CSS, shadcn/ui style components, Recharts.
- Backend: FastAPI, Pydantic, JWT (PyJWT) with bcrypt password hashes.
- Database: MySQL 8 through mysql-connector-python, plain parameterised SQL, no ORM.
- Data: DuckDB and Polars (lazy scans, streaming sinks) to Parquet, Pandas where small.
- MLOps: MLflow (local), DVC pipeline (dvc.yaml), Optuna, Joblib.
- Monitoring: prometheus-client at /metrics, a prometheus.yml and a Grafana dashboard.
- CI: GitHub Actions running ruff, pytest (with a MySQL service) and the frontend build.
- No Docker, Kubernetes or cloud services.
- Python 3.11 is the supported version, because LightFM has no wheels and builds most
  reliably there.

## Phases

1. Foundation: project layout, settings, MySQL schema and init script, FastAPI app with
   auth, Vite app shell with sidebar and login.
2. Data pipeline: ingest raw files to Parquet, clean and normalise (unknown nutrients
   stay NULL), temporal split, load the catalogue into MySQL. Generic ingest for any
   CSV, JSON or Parquet file, tested on a file larger than 1 GB.
3. ML: content, LightFM, PyTorch NCF, hybrid, XGBoost reranker, Optuna tuning, offline
   evaluation (precision, recall, NDCG at 10, coverage) logged to MLflow.
4. RAG: embeddings, FAISS index, LangGraph assistant, Gemini with validation and fallback.
5. Product features: onboarding, recommendations, explorer, planner, tracker, dashboard,
   history, admin (datasets, background jobs, model performance).
6. Monitoring, CI, README, tests, Playwright click-through and screenshots.

## Honest limits planned from the start

- Food.com ratings are mostly 5 stars and sparse, so ranking metrics will be low in
  absolute terms. They are reported as measured, against baselines.
- App users are not in the training data. Their LightFM vector is folded in from the
  items they like. The offline evaluation also measures this fold-in path.
- Allergen checks are text matching on recipe text (a synonym map with negation and
  false friend handling), not a food safety guarantee.

## Status (end of build)

All six phases are done. Points where the result differs from the plan:

- The XGBoost reranker is trained and evaluated on every run, but the validation check
  chose to leave it off (holdout NDCG@10 0.0253 against 0.0279 for the hybrid order).
  On the test split it scored a little higher than the hybrid (0.0337 against 0.0328).
  That gap is within noise, and the test split was not used to decide.
- CI runs on the MySQL that is preinstalled on the GitHub Ubuntu runner, not a service
  container, to keep Docker out of the project entirely. Tests that need the trained
  models are skipped in CI because the artifacts are not in git.
- Polars 2 removed its batched CSV reader, so large CSV files are streamed with the
  Arrow CSV reader in 4 MB blocks, grouped into batches of about 64 MB. The rest of
  the ingest path is unchanged.
- Added after the first review: planner breakfasts are filtered by a breakfast rule
  set with a labelled fallback, and allergen matching uses a synonym map with Indian
  names, negations and false friends.
