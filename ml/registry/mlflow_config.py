# MLflow tracking configuration — sets tracking URI from env, defines experiment names per model,
# snapshot() function called every MODEL_SNAPSHOT_INTERVAL bars to log:
#   - model weights (River model serialized with pickle)
#   - rolling accuracy (last 50 bars)
#   - model params (from ModelSettings)
#   - user_id tag (snapshots are per-user for personal models)
# Rollback: mlflow.load_model(run_id) restores any previous snapshot
