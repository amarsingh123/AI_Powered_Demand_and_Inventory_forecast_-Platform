"""
Model layer for SalesIQ.

Loads the two shipped artifacts (rf_model.pkl -> RandomForestRegressor,
xgb_model.pkl -> XGBRegressor) which both expect the same 28-column
engineered feature schema. A Ridge Regression option is trained live
(it's cheap and keeps the "3 models" picker in the Sales Forecasting
screen working without a third artifact).

Because the original label/target encoders for store_enc/category_enc/
product_enc were not shipped with the .pkl files, this module defines
its own consistent encoding scheme and documents that these are
reconstructed proxies, not the exact training-time encoders.
"""
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

BASE_DIR = Path(__file__).parent

FEATURE_ORDER = [
    "year", "month", "day", "day_of_week", "week_of_year", "quarter",
    "is_weekend", "is_month_start", "is_month_end", "day_of_year",
    "lag_1d", "lag_7d", "lag_14d", "lag_30d",
    "rolling_mean_7d", "rolling_mean_14d", "rolling_mean_30d",
    "rolling_std_7d", "rolling_std_14d", "expanding_mean",
    "is_promotion", "promo_x_weekend", "promo_lag1",
    "unit_price", "discount_pct", "store_enc", "category_enc", "product_enc",
]

_RF = None
_XGB = None


def _load_models():
    global _RF, _XGB
    if _RF is None:
        _RF = joblib.load(BASE_DIR  / "models" / "rf_model.pkl")
    if _XGB is None:
        import pickle
        with open(BASE_DIR  / "models" / "xgb_model.pkl", "rb") as f:
            _XGB = pickle.load(f)
    return _RF, _XGB


def build_features(series: pd.Series, dates: pd.DatetimeIndex, unit_price: float,
                    discount_pct: float, store_enc: int, category_enc: int,
                    product_enc: int, promo_flags: pd.Series) -> pd.DataFrame:
    """series: historical target values indexed by date (same index as `dates`, ascending)."""
    df = pd.DataFrame({"date": dates, "y": series.values, "promo": promo_flags.values.astype(int)})
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["day"] = df["date"].dt.day
    df["day_of_week"] = df["date"].dt.dayofweek
    df["week_of_year"] = df["date"].dt.isocalendar().week.astype(int)
    df["quarter"] = df["date"].dt.quarter
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["is_month_start"] = df["date"].dt.is_month_start.astype(int)
    df["is_month_end"] = df["date"].dt.is_month_end.astype(int)
    df["day_of_year"] = df["date"].dt.dayofyear
    df["lag_1d"] = df["y"].shift(1)
    df["lag_7d"] = df["y"].shift(7)
    df["lag_14d"] = df["y"].shift(14)
    df["lag_30d"] = df["y"].shift(30)
    df["rolling_mean_7d"] = df["y"].shift(1).rolling(7).mean()
    df["rolling_mean_14d"] = df["y"].shift(1).rolling(14).mean()
    df["rolling_mean_30d"] = df["y"].shift(1).rolling(30).mean()
    df["rolling_std_7d"] = df["y"].shift(1).rolling(7).std()
    df["rolling_std_14d"] = df["y"].shift(1).rolling(14).std()
    df["expanding_mean"] = df["y"].shift(1).expanding().mean()
    df["is_promotion"] = df["promo"]
    df["promo_x_weekend"] = df["promo"] * df["is_weekend"]
    df["promo_lag1"] = df["promo"].shift(1).fillna(0).astype(int)
    df["unit_price"] = unit_price
    df["discount_pct"] = discount_pct
    df["store_enc"] = store_enc
    df["category_enc"] = category_enc
    df["product_enc"] = product_enc
    df = df.bfill().fillna(0)
    return df


def _raw_predict(model_name: str, X: pd.DataFrame, ridge_model=None, ridge_scaler=None):
    if model_name == "rf":
        rf, _ = _load_models()
        return rf.predict(X[FEATURE_ORDER])
    if model_name == "xgb":
        _, xgb = _load_models()
        return xgb.predict(X[FEATURE_ORDER])
    if model_name == "ridge":
        Xs = ridge_scaler.transform(X[FEATURE_ORDER])
        return ridge_model.predict(Xs)
    raise ValueError(f"unknown model {model_name}")


def calibrate(feat_df: pd.DataFrame, model_name: str, ridge_model=None, ridge_scaler=None):
    """
    rf_model.pkl / xgb_model.pkl were shipped without their original
    store/category/product label encoders, so their raw output can land on
    a different scale/offset than this app's revenue series. We fit a
    simple affine correction (actual ~= a * raw_pred + b) over the known
    history so the shipped model's *learned temporal pattern* still drives
    the forecast, just rescaled onto the right units. Ridge is trained
    natively on our data, so it needs no correction (a=1, b=0).
    """
    if model_name == "ridge":
        return 1.0, 0.0
    raw = _raw_predict(model_name, feat_df, ridge_model, ridge_scaler)
    actual = feat_df["y"].values
    if np.std(raw) < 1e-6:
        a, b = 1.0, float(np.mean(actual) - np.mean(raw))
    else:
        a, b = np.polyfit(raw, actual, 1)
    return float(a), float(b)


def _predict_one(model_name: str, X_row: pd.DataFrame, ridge_model=None, ridge_scaler=None,
                  calib: tuple = (1.0, 0.0)):
    raw = _raw_predict(model_name, X_row, ridge_model, ridge_scaler)[0]
    a, b = calib
    return float(a * raw + b)


def train_ridge(feat_df: pd.DataFrame):
    X = feat_df[FEATURE_ORDER]
    y = feat_df["y"]
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = Ridge(alpha=5.0, random_state=42)
    model.fit(Xs, y)
    return model, scaler


def backtest(feat_df: pd.DataFrame, model_name: str, holdout: int = 14):
    """Rolling one-step backtest over the last `holdout` days for MAE/RMSE/R2."""
    if len(feat_df) <= holdout + 30:
        holdout = max(5, len(feat_df) - 35)
    train = feat_df.iloc[:-holdout]
    test = feat_df.iloc[-holdout:]

    ridge_model = ridge_scaler = None
    if model_name == "ridge":
        ridge_model, ridge_scaler = train_ridge(train)
    calib = calibrate(train, model_name, ridge_model, ridge_scaler)

    preds = []
    for _, row in test.iterrows():
        row_df = pd.DataFrame([row])
        preds.append(_predict_one(model_name, row_df, ridge_model, ridge_scaler, calib))
    preds = np.array(preds)
    actual = test["y"].values
    mae = float(np.mean(np.abs(preds - actual)))
    rmse = float(np.sqrt(np.mean((preds - actual) ** 2)))
    ss_res = float(np.sum((actual - preds) ** 2))
    ss_tot = float(np.sum((actual - actual.mean()) ** 2)) or 1e-9
    r2 = 1 - ss_res / ss_tot
    return {"mae": round(mae, 2), "rmse": round(rmse, 2), "r2": round(r2, 4)}


def feature_importance(model_name: str, feat_df: pd.DataFrame, top_n=15):
    if model_name == "rf":
        rf, _ = _load_models()
        imp = rf.feature_importances_
    elif model_name == "xgb":
        _, xgb = _load_models()
        imp = xgb.feature_importances_
    else:
        ridge_model, ridge_scaler = train_ridge(feat_df)
        imp = np.abs(ridge_model.coef_)
    pairs = sorted(zip(FEATURE_ORDER, imp), key=lambda x: -x[1])[:top_n]
    return [{"feature": f, "importance": round(float(v), 4)} for f, v in pairs]


def forecast(feat_df: pd.DataFrame, model_name: str, horizon: int, promo_rate: float = 0.12):
    """Recursively forecast `horizon` future days from the tail of feat_df's series."""
    ridge_model = ridge_scaler = None
    if model_name == "ridge":
        ridge_model, ridge_scaler = train_ridge(feat_df)
    calib = calibrate(feat_df, model_name, ridge_model, ridge_scaler)

    hist_dates = list(feat_df["date"])
    hist_y = list(feat_df["y"])
    hist_promo = list(feat_df["promo"])
    unit_price = float(feat_df["unit_price"].iloc[-1])
    discount_pct = float(feat_df["discount_pct"].iloc[-1])
    store_enc = int(feat_df["store_enc"].iloc[-1])
    category_enc = int(feat_df["category_enc"].iloc[-1])
    product_enc = int(feat_df["product_enc"].iloc[-1])

    rng = np.random.default_rng(7)
    results = []
    cur_date = hist_dates[-1]
    for _ in range(horizon):
        cur_date = cur_date + pd.Timedelta(days=1)
        promo_flag = int(rng.random() < promo_rate)
        ext_dates = pd.DatetimeIndex(hist_dates + [cur_date])
        ext_y = pd.Series(hist_y + [hist_y[-1]])  # placeholder, overwritten by lag logic below
        ext_promo = pd.Series(hist_promo + [promo_flag])
        built = build_features(pd.Series(hist_y + [np.nan]), ext_dates, unit_price, discount_pct,
                                store_enc, category_enc, product_enc, ext_promo)
        row = built.iloc[[-1]].copy()
        # lag/rolling features must come from real history only (exclude the NaN placeholder)
        hist_series = pd.Series(hist_y)
        row["lag_1d"] = hist_series.iloc[-1]
        row["lag_7d"] = hist_series.iloc[-7] if len(hist_series) >= 7 else hist_series.iloc[0]
        row["lag_14d"] = hist_series.iloc[-14] if len(hist_series) >= 14 else hist_series.iloc[0]
        row["lag_30d"] = hist_series.iloc[-30] if len(hist_series) >= 30 else hist_series.iloc[0]
        row["rolling_mean_7d"] = hist_series.tail(7).mean()
        row["rolling_mean_14d"] = hist_series.tail(14).mean()
        row["rolling_mean_30d"] = hist_series.tail(30).mean()
        row["rolling_std_7d"] = hist_series.tail(7).std() or 0
        row["rolling_std_14d"] = hist_series.tail(14).std() or 0
        row["expanding_mean"] = hist_series.mean()
        row["is_promotion"] = promo_flag
        row["promo_x_weekend"] = promo_flag * row["is_weekend"].iloc[0]
        row["promo_lag1"] = hist_promo[-1]
        row = row.fillna(0)

        pred = _predict_one(model_name, row, ridge_model, ridge_scaler, calib)
        pred = max(0.0, pred)
        results.append({"date": cur_date.strftime("%Y-%m-%d"), "forecast": round(pred, 2)})
        hist_dates.append(cur_date)
        hist_y.append(pred)
        hist_promo.append(promo_flag)

    return results
