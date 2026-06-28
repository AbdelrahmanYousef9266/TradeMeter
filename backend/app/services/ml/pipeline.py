# ML pipeline orchestrator — MODEL_REGISTRY dict mapping model names to instances,
# predict_all(features, user_id) calls all 10 models and returns predictions,
# learn_all(features, label, user_id) updates all model weights and XP:
#   - awards XP based on prediction correctness, P&L delta, bars learned, streak
#   - checks for level-up after each bar
#   - if level-up detected: publishes LevelUpEvent to Redis pub/sub "live:{user_id}"
#   - persists updated level/xp/streak to model_levels table in TimescaleDB
# snapshot_all() saves River model weights to MLflow every MODEL_SNAPSHOT_INTERVAL bars
