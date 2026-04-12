#!/usr/bin/env python3
"""Train the Ruby Score model from labeled database readings.

Queries ruby_score_log for caregiver-labeled samples,
trains a regression model, and saves it for on-device inference.

Run on the robot:
  python3 train_ruby_score.py

Or locally with a copy of people.db:
  python3 train_ruby_score.py --db people.db
"""

import argparse
import sqlite3
import pickle
from pathlib import Path

import numpy as np

DB_PATH = "/home/jetson1/emotion_tracker/people.db"
MODEL_PATH = Path(__file__).parent / "ruby_score_model.pkl"


def query_training_data(db_path):
    """Pull all labeled samples from ruby_score_log."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """SELECT eye_contact, volume, response_latency, label
           FROM ruby_score_log
           WHERE label IS NOT NULL
           ORDER BY timestamp"""
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def train(rows):
    """Train a linear regression model (runs on Jetson CPU, no GPU needed).

    Uses numpy least-squares — no scikit-learn dependency required.
    Falls back to Ridge-style regularization for small datasets.
    """
    X = np.array([[r["eye_contact"], r["volume"], r["response_latency"]] for r in rows])
    y = np.array([r["label"] for r in rows], dtype=np.float64)

    print(f"Training on {len(rows)} labeled samples")
    print(f"  eye_contact  range: [{X[:,0].min():.3f}, {X[:,0].max():.3f}]")
    print(f"  volume       range: [{X[:,1].min():.3f}, {X[:,1].max():.3f}]")
    print(f"  resp_latency range: [{X[:,2].min():.3f}, {X[:,2].max():.3f}]")
    print(f"  label        range: [{y.min():.0f}, {y.max():.0f}]")

    # add bias column
    X_b = np.column_stack([X, np.ones(len(X))])

    # ridge regression (lambda=1.0 for stability with small N)
    lam = 1.0
    I = np.eye(X_b.shape[1])
    I[-1, -1] = 0  # don't regularize bias
    weights = np.linalg.solve(X_b.T @ X_b + lam * I, X_b.T @ y)

    # evaluate on training data
    y_pred = X_b @ weights
    y_pred = np.clip(y_pred, 0, 100)
    mae = np.mean(np.abs(y - y_pred))
    rmse = np.sqrt(np.mean((y - y_pred) ** 2))

    print(f"\nModel weights:")
    print(f"  eye_contact:      {weights[0]:+.2f}")
    print(f"  volume:           {weights[1]:+.2f}")
    print(f"  response_latency: {weights[2]:+.2f}")
    print(f"  bias:             {weights[3]:+.2f}")
    print(f"\nTraining MAE:  {mae:.1f}")
    print(f"Training RMSE: {rmse:.1f}")

    return weights


class RubyScoreModel:
    """Minimal model wrapper — pickle-friendly, no sklearn dependency."""

    def __init__(self, weights):
        self.weights = weights

    def predict(self, X):
        X = np.asarray(X)
        X_b = np.column_stack([X, np.ones(X.shape[0])])
        y = X_b @ self.weights
        return np.clip(y, 0, 100)


def main():
    parser = argparse.ArgumentParser(description="Train Ruby Score model")
    parser.add_argument("--db", default=DB_PATH, help="Path to people.db")
    parser.add_argument("--output", default=str(MODEL_PATH), help="Output model path")
    parser.add_argument("--dry-run", action="store_true", help="Query and show stats only")
    args = parser.parse_args()

    rows = query_training_data(args.db)
    if not rows:
        print("No labeled training data found in ruby_score_log.")
        print("Have a caregiver label some readings first.")
        return

    if args.dry_run:
        print(f"Found {len(rows)} labeled samples:")
        for r in rows[:5]:
            print(f"  eye={r['eye_contact']:.3f} vol={r['volume']:.3f} "
                  f"lat={r['response_latency']:.1f}s → label={r['label']}")
        if len(rows) > 5:
            print(f"  ... and {len(rows) - 5} more")
        return

    weights = train(rows)

    model = RubyScoreModel(weights)
    with open(args.output, "wb") as f:
        pickle.dump(model, f)

    print(f"\nModel saved to {args.output}")
    print("RubyScoreEngine will auto-load it on next start.")


if __name__ == "__main__":
    main()
