"""
独立推理工作进程（_forecast_worker.py）
=======================================
由 forecast_service.py 通过 subprocess 调用，
运行在 .venv-forecast 环境中，避免主后端与 ML 库产生依赖冲突。

协议（stdin -> stdout，均为 JSON）：

  模式 metadata：
    stdin  → { "pkl_path": "...", "mode": "metadata" }
    stdout → { "model_name": "...", "feature_cols": [...],
               "target_cols": [...], "horizons_h": [...], "target_kpis": [...] }

  模式 predict：
    stdin  → { "pkl_path": "...", "mode": "predict",
               "feature_cols": [...],
               "features": [[v1, v2, ...]] }
    stdout → { "predictions": [[pred_6h, pred_12h, ...]] }

  错误：
    stdout → { "error": "..." }   (exit code 1)
"""
import json
import sys


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception as exc:
        print(json.dumps({"error": f"stdin parse failed: {exc}"}))
        sys.exit(1)

    pkl_path = payload.get("pkl_path")
    mode = payload.get("mode", "predict")

    try:
        import warnings
        import joblib

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            artifact = joblib.load(pkl_path)

    except Exception as exc:
        print(json.dumps({"error": f"model load failed: {exc}"}))
        sys.exit(1)

    if mode == "metadata":
        print(json.dumps({
            "model_name":  artifact.get("model_name", "unknown"),
            "feature_cols": list(artifact.get("feature_cols", [])),
            "target_cols":  list(artifact.get("target_cols", [])),
            "horizons_h":   list(artifact.get("horizons_h", [])),
            "target_kpis":  list(artifact.get("target_kpis", [])),
        }))
        return

    # mode == "predict"
    try:
        import pandas as pd

        model = artifact.get("pipeline") or artifact.get("model")
        if model is None:
            print(json.dumps({"error": "artifact has no 'pipeline' or 'model' key"}))
            sys.exit(1)

        feature_cols = payload.get("feature_cols") or list(artifact["feature_cols"])
        # 用 DataFrame 保留列名，sklearn Pipeline 需要列名
        X = pd.DataFrame(payload["features"], columns=feature_cols)
        preds = model.predict(X).tolist()

        print(json.dumps({
            "predictions": preds,
            "target_cols": list(artifact.get("target_cols", [])),
        }))
    except Exception as exc:
        print(json.dumps({"error": f"predict failed: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
