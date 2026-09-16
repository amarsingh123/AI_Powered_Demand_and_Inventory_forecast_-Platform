from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics.pairwise import cosine_similarity
from Backend.data import get_dataset
import Backend.ml as ml

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR.parent / "static"

app = FastAPI(title="SalesIQ API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------------------------------------------------------- in-memory admin store
USERS = [
    {"username": "admin", "role": "Admin", "created_at": "2026-06-22 10:51:59"},
    {"username": "manager", "role": "Manager", "created_at": "2026-06-22 10:52:00"},
]
ALERTS_LOG = []  # populated by /api/alerts/run


class NewUser(BaseModel):
    username: str
    password: str
    role: str = "Manager"


class ForecastRequest(BaseModel):
    model: str = "rf"          # rf | xgb | ridge
    horizon: int = 30
    history_days: int = 365


class ProductForecastRequest(BaseModel):
    product_id: int
    days: int = 14
    model: str = "rf"


# ================================================================== DASHBOARD
@app.get("/api/dashboard")
def dashboard(period: int = Query(30, ge=7, le=180)):
    ds = get_dataset()
    rev = ds.daily_revenue_series()
    window = rev.tail(period)
    prev_window = rev.iloc[max(0, len(rev) - 2 * period): len(rev) - period]

    orders_window = ds.orders[ds.orders["date"] >= window["date"].min()]
    prev_orders = ds.orders[(ds.orders["date"] >= prev_window["date"].min()) &
                             (ds.orders["date"] < window["date"].min())] if len(prev_window) else pd.DataFrame()

    revenue = float(window["revenue"].sum())
    prev_revenue = float(prev_window["revenue"].sum()) if len(prev_window) else revenue
    orders_count = orders_window["order_id"].nunique()
    prev_orders_count = prev_orders["order_id"].nunique() if len(prev_orders) else orders_count
    customers_count = orders_window["customer_id"].nunique()
    aov = revenue / orders_count if orders_count else 0

    def pct_change(cur, prev):
        if not prev:
            return 0.0
        return round((cur - prev) / prev * 100, 1)

    cat_rev = orders_window.groupby("category")["revenue"].sum().sort_values(ascending=False)
    daily_trend = window.copy()
    daily_trend["ma7"] = rev["revenue"].rolling(7).mean().reindex(daily_trend.index)

    return {
        "kpis": {
            "revenue": round(revenue, 2), "revenue_change_pct": pct_change(revenue, prev_revenue),
            "orders": int(orders_count), "orders_change_pct": pct_change(orders_count, prev_orders_count),
            "customers": int(customers_count),
            "aov": round(aov, 2),
        },
        "daily_trend": [
            {"date": d.strftime("%Y-%m-%d"), "revenue": round(r, 2), "ma7": (None if pd.isna(m) else round(m, 2))}
            for d, r, m in zip(daily_trend["date"], daily_trend["revenue"], daily_trend["ma7"])
        ],
        "revenue_by_category": [{"category": c, "revenue": round(v, 2)} for c, v in cat_rev.items()],
    }


# ================================================================== SALES FORECASTING
@app.get("/api/forecast/history")
def forecast_history(history_days: int = 365):
    ds = get_dataset()
    rev = ds.daily_revenue_series()
    tail = rev.tail(min(history_days, len(rev)))
    return {"dates": [d.strftime("%Y-%m-%d") for d in tail["date"]],
            "revenue": [round(v, 2) for v in tail["revenue"]]}


@app.post("/api/forecast/run")
def run_forecast(req: ForecastRequest):
    if req.model not in ("rf", "xgb", "ridge"):
        raise HTTPException(400, "model must be rf, xgb, or ridge")
    ds = get_dataset()
    rev = ds.daily_revenue_series()
    tail = rev.tail(min(req.history_days, len(rev))).reset_index(drop=True)

    avg_price = float(ds.products["unit_price"].mean())
    feat_df = ml.build_features(
        series=tail["revenue"], dates=pd.DatetimeIndex(tail["date"]),
        unit_price=avg_price, discount_pct=5.0, store_enc=0, category_enc=0, product_enc=0,
        promo_flags=tail["is_promotion"],
    )
    feat_df["promo"] = tail["is_promotion"].astype(int).values

    metrics = ml.backtest(feat_df, req.model)
    fc = ml.forecast(feat_df, req.model, req.horizon)
    importance = ml.feature_importance(req.model, feat_df)

    hist_tail = tail.tail(60)
    return {
        "model": req.model,
        "metrics": metrics,
        "history": [{"date": d.strftime("%Y-%m-%d"), "revenue": round(v, 2)}
                    for d, v in zip(hist_tail["date"], hist_tail["revenue"])],
        "forecast": fc,
        "feature_importance": importance,
    }


# ================================================================== CUSTOMER SEGMENTATION
_SEGMENT_LABELS_BY_RANK = ["Lost Customers", "At Risk", "Loyal Customers", "Champions"]
_EXTRA_LABELS = ["New Customers", "Occasional Buyers"]


def _label_for_rank(rank: int, k: int) -> str:
    if k == 4:
        return _SEGMENT_LABELS_BY_RANK[rank]
    base = _SEGMENT_LABELS_BY_RANK
    pool = base + _EXTRA_LABELS
    # spread ranks evenly across however many labels we have available
    idx = int(rank / max(1, k - 1) * (len(pool) - 1)) if k > 1 else 0
    return pool[idx]


@app.get("/api/segments")
def segments(k: int = Query(4, ge=2, le=6)):
    ds = get_dataset()
    orders = ds.orders
    today = ds.today
    rfm = orders.groupby("customer_id").agg(
        last_order=("date", "max"), frequency=("order_id", "nunique"), monetary=("revenue", "sum"),
    ).reset_index()
    rfm["recency"] = (today - rfm["last_order"]).dt.days
    rfm = rfm.merge(ds.customers, on="customer_id", how="left")

    X = rfm[["recency", "frequency", "monetary"]].values
    Xs = StandardScaler().fit_transform(X)
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    rfm["cluster"] = km.fit_predict(Xs)

    cluster_stats = rfm.groupby("cluster").agg(
        avg_recency=("recency", "mean"), avg_frequency=("frequency", "mean"),
        avg_monetary=("monetary", "mean"), n=("customer_id", "count"),
    ).reset_index()
    # rank clusters worst -> best using a simple RFM score (low recency & high F/M is best)
    cluster_stats["score"] = (-cluster_stats["avg_recency"].rank() +
                               cluster_stats["avg_frequency"].rank() +
                               cluster_stats["avg_monetary"].rank())
    cluster_stats = cluster_stats.sort_values("score").reset_index(drop=True)
    cluster_stats["rank"] = range(len(cluster_stats))
    cluster_stats["label"] = cluster_stats["rank"].apply(lambda r: _label_for_rank(r, k))
    label_map = dict(zip(cluster_stats["cluster"], cluster_stats["label"]))
    rfm["segment"] = rfm["cluster"].map(label_map)

    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(Xs)
    rfm["pc1"], rfm["pc2"] = coords[:, 0], coords[:, 1]

    overview = []
    for _, row in cluster_stats.iterrows():
        overview.append({
            "segment": row["label"], "customers": int(row["n"]),
            "avg_recency": round(row["avg_recency"], 0),
            "avg_frequency": round(row["avg_frequency"], 1),
            "avg_monetary": round(row["avg_monetary"], 0),
        })

    revenue_by_segment = rfm.groupby("segment")["monetary"].sum().sort_values(ascending=False)
    scatter_sample = rfm.sample(min(300, len(rfm)), random_state=1)

    return {
        "overview": overview,
        "revenue_by_segment": [{"segment": s, "revenue": round(v, 2)} for s, v in revenue_by_segment.items()],
        "cluster_map": [{"segment": r["segment"], "pc1": round(r["pc1"], 3), "pc2": round(r["pc2"], 3)}
                         for _, r in scatter_sample.iterrows()],
    }


# ================================================================== RECOMMENDATIONS
@app.get("/api/customers")
def list_customers():
    ds = get_dataset()
    ordered = ds.orders["customer_id"].unique()
    df = ds.customers[ds.customers["customer_id"].isin(ordered)]
    counts = ds.orders.groupby("customer_id")["product_id"].nunique()
    out = []
    for _, row in df.iterrows():
        out.append({"customer_id": int(row["customer_id"]), "name": row["name"],
                     "unique_products": int(counts.get(row["customer_id"], 0))})
    return sorted(out, key=lambda r: r["customer_id"])


@app.get("/api/products")
def list_products():
    ds = get_dataset()
    return ds.products.to_dict(orient="records")


def _purchase_matrix(ds):
    mat = ds.orders.pivot_table(index="customer_id", columns="product_id", values="qty",
                                 aggfunc="sum", fill_value=0)
    return mat


@app.get("/api/recommendations/customer")
def recommend_for_customer(customer_id: int, n: int = Query(5, ge=1, le=10)):
    ds = get_dataset()
    mat = _purchase_matrix(ds)
    if customer_id not in mat.index:
        raise HTTPException(404, "customer has no purchase history")
    item_sim = cosine_similarity(mat.T.values)
    item_sim_df = pd.DataFrame(item_sim, index=mat.columns, columns=mat.columns)

    cust_vector = mat.loc[customer_id]
    purchased = cust_vector[cust_vector > 0].index.tolist()
    scores = item_sim_df[purchased].mul(cust_vector[purchased], axis=1).sum(axis=1)
    scores = scores.drop(index=purchased, errors="ignore")
    scores = scores[scores > 0].sort_values(ascending=False).head(n)

    prod_info = ds.products.set_index("product_id")
    results = []
    for pid, score in scores.items():
        p = prod_info.loc[pid]
        results.append({"product_id": int(pid), "name": p["name"], "category": p["category"],
                         "price": round(float(p["unit_price"]), 2), "match_score": round(float(score), 4)})
    return {"customer_id": customer_id, "unique_purchased": len(purchased), "recommendations": results}


@app.get("/api/recommendations/similar")
def similar_products(product_id: int, n: int = Query(5, ge=1, le=10)):
    ds = get_dataset()
    mat = _purchase_matrix(ds)
    if product_id not in mat.columns:
        raise HTTPException(404, "unknown product")
    item_sim = cosine_similarity(mat.T.values)
    item_sim_df = pd.DataFrame(item_sim, index=mat.columns, columns=mat.columns)
    scores = item_sim_df[product_id].drop(index=product_id).sort_values(ascending=False).head(n)
    prod_info = ds.products.set_index("product_id")
    results = []
    for pid, score in scores.items():
        p = prod_info.loc[pid]
        results.append({"product_id": int(pid), "name": p["name"], "category": p["category"],
                         "price": round(float(p["unit_price"]), 2), "match_score": round(float(score), 4)})
    return {"product_id": product_id, "recommendations": results}


# ================================================================== INVENTORY & DEMAND
@app.get("/api/inventory/overview")
def inventory_overview():
    ds = get_dataset()
    products = ds.products
    total_products = len(products)
    inventory_value = float((products["unit_price"] * products["stock"]).sum())
    low_stock = products[(products["stock"] < 10) & (products["stock"] > 0)].sort_values("stock")
    out_of_stock = products[products["stock"] == 0]

    cat_value = (products.assign(value=products["unit_price"] * products["stock"])
                 .groupby("category")["value"].sum().sort_values(ascending=False))

    return {
        "total_products": total_products,
        "inventory_value": round(inventory_value, 2),
        "low_stock_count": int(len(low_stock)),
        "out_of_stock_count": int(len(out_of_stock)),
        "low_stock_products": [{"name": r["name"], "stock": int(r["stock"]), "category": r["category"]}
                                for _, r in low_stock.iterrows()],
        "stock_by_category": [{"category": c, "value": round(v, 2)} for c, v in cat_value.items()],
    }


@app.post("/api/inventory/forecast")
def inventory_forecast(req: ProductForecastRequest):
    ds = get_dataset()
    prod_row = ds.products[ds.products["product_id"] == req.product_id]
    if prod_row.empty:
        raise HTTPException(404, "unknown product")
    prod_row = prod_row.iloc[0]
    cat_idx = {c: i for i, c in enumerate(sorted(ds.products["category"].unique()))}

    prod_orders = ds.orders[ds.orders["product_id"] == req.product_id]
    daily_qty = prod_orders.groupby("date")["qty"].sum().reindex(ds.dates, fill_value=0)
    promo = pd.Series(ds.promo_mask, index=ds.dates)

    feat_df = ml.build_features(
        series=daily_qty, dates=pd.DatetimeIndex(ds.dates), unit_price=float(prod_row["unit_price"]),
        discount_pct=5.0, store_enc=0, category_enc=cat_idx[prod_row["category"]],
        product_enc=int(req.product_id), promo_flags=promo,
    )
    feat_df["promo"] = promo.astype(int).values

    fc = ml.forecast(feat_df, req.model, req.days)
    predicted_demand = sum(f["forecast"] for f in fc)
    current_stock = int(prod_row["stock"])
    avg_daily = predicted_demand / req.days if req.days else 0
    coverage_days = round(current_stock / avg_daily, 1) if avg_daily > 0.01 else 999
    mae_metrics = ml.backtest(feat_df, req.model, holdout=14)

    hist_tail = daily_qty.tail(45)
    return {
        "product": {"name": prod_row["name"], "category": prod_row["category"]},
        "current_stock": current_stock,
        "predicted_demand": round(predicted_demand, 1),
        "coverage_days": coverage_days,
        "sufficient": coverage_days >= req.days,
        "model_mae": mae_metrics["mae"],
        "history": [{"date": d.strftime("%Y-%m-%d"), "qty": int(v)} for d, v in hist_tail.items()],
        "forecast": [{"date": f["date"], "qty": round(f["forecast"], 1)} for f in fc],
        "est_remaining_stock": _remaining_stock_curve(current_stock, fc),
    }


def _remaining_stock_curve(current_stock, fc):
    remaining = current_stock
    curve = []
    for f in fc:
        remaining -= f["forecast"]
        curve.append({"date": f["date"], "remaining": round(max(remaining, 0), 1)})
    return curve


# ================================================================== KPI ALERTS
@app.get("/api/alerts")
def get_alerts(days: int = Query(7, ge=1, le=90), show_resolved: bool = False):
    ds = get_dataset()
    rev = ds.daily_revenue_series()
    window = rev.tail(days + 1)

    alerts = []
    # revenue-drop alerts: day-over-day drop vs trailing 7d mean beyond 25%
    full = rev.set_index("date")["revenue"]
    ma7 = full.rolling(7).mean()
    for d in window["date"]:
        if d not in ma7.index or pd.isna(ma7.loc[d]) or ma7.loc[d] == 0:
            continue
        actual = full.loc[d]
        drop_pct = (actual - ma7.loc[d]) / ma7.loc[d] * 100
        if drop_pct <= -25:
            alerts.append({
                "type": "Revenue Drop", "severity": "critical" if drop_pct <= -40 else "warning",
                "date": d.strftime("%Y-%m-%d"),
                "message": f"Revenue {abs(round(drop_pct))}% below 7-day average",
                "resolved": False,
            })

    # low stock alerts
    low_stock = ds.products[(ds.products["stock"] < 10)]
    for _, p in low_stock.iterrows():
        severity = "critical" if p["stock"] <= 5 else "warning"
        alerts.append({
            "type": "Low Stock", "severity": severity,
            "date": ds.today.strftime("%Y-%m-%d"),
            "message": f"{p['name']} has only {int(p['stock'])} units left",
            "resolved": False,
        })

    if not show_resolved:
        alerts = [a for a in alerts if not a["resolved"]]

    total = len(alerts)
    critical = sum(1 for a in alerts if a["severity"] == "critical")
    warnings = sum(1 for a in alerts if a["severity"] == "warning")
    resolved = 0

    trend_days = pd.date_range(end=ds.today, periods=days)
    trend_counts = {d.strftime("%Y-%m-%d"): 0 for d in trend_days}
    for a in alerts:
        if a["date"] in trend_counts:
            trend_counts[a["date"]] += 1

    type_dist = {}
    for a in alerts:
        type_dist[a["type"]] = type_dist.get(a["type"], 0) + 1

    return {
        "summary": {"total": total, "critical": critical, "warnings": warnings, "resolved": resolved},
        "alerts": alerts,
        "trend": [{"date": d, "count": c} for d, c in trend_counts.items()],
        "type_distribution": [{"type": t, "count": c} for t, c in type_dist.items()],
    }


# ================================================================== ADMIN
@app.get("/api/admin/users")
def admin_list_users():
    return USERS


@app.post("/api/admin/users")
def admin_create_user(u: NewUser):
    if any(existing["username"] == u.username for existing in USERS):
        raise HTTPException(400, "username already exists")
    if not u.username or not u.password:
        raise HTTPException(400, "username and password are required")
    USERS.append({"username": u.username, "role": u.role,
                  "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")})
    return {"ok": True, "users": USERS}


@app.get("/api/admin/stats")
def admin_stats():
    ds = get_dataset()
    return {
        "users": len(USERS),
        "customers": len(ds.customers),
        "products": len(ds.products),
        "orders": len(ds.orders),
        "days_of_history": len(ds.dates),
        "total_revenue": round(float(ds.orders["revenue"].sum()), 2),
    }


# ================================================================== STATIC FRONTEND
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
