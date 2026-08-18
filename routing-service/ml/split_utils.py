"""
Splitting and validation utilities for leak-proof model evaluation.
Guarantees that rows from the same trip_id never cross train and validation splits.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit, StratifiedGroupKFold


def split_by_trip_group(
    df: pd.DataFrame,
    *,
    group_col: str = "trip_id",
    test_size: float = 0.20,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Performs a leak-free split where all rows sharing a trip_id stay together.
    """
    if group_col not in df.columns:
        raise ValueError(f"Required group column '{group_col}' not found in DataFrame.")
    
    unique_trips = df[group_col].nunique()
    if unique_trips < 5:
        raise ValueError(f"At least 5 distinct trips are required for a group split. Found: {unique_trips}")
    
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(df, groups=df[group_col]))
    
    train_df = df.iloc[train_idx].copy()
    test_df = df.iloc[test_idx].copy()
    
    # Assert zero leakage
    train_trips = set(train_df[group_col].unique())
    test_trips = set(test_df[group_col].unique())
    overlap = train_trips.intersection(test_trips)
    if overlap:
        raise RuntimeError(f"Data leakage detected! {len(overlap)} trips exist in both train and test splits.")
    
    return train_df, test_df


def stratified_group_kfold_split(
    df: pd.DataFrame,
    *,
    group_col: str = "trip_id",
    target_col: str = "label",
    n_splits: int = 5,
    random_state: int = 42,
):
    """
    Yields (train_df, val_df) folds using StratifiedGroupKFold to preserve class balance across trips.
    """
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    for fold, (train_idx, val_idx) in enumerate(sgkf.split(df, df[target_col], groups=df[group_col])):
        train_fold = df.iloc[train_idx].copy()
        val_fold = df.iloc[val_idx].copy()
        
        # Verify zero leakage
        assert len(set(train_fold[group_col]).intersection(set(val_fold[group_col]))) == 0
        yield fold, train_fold, val_fold


def summarize_split(train_df: pd.DataFrame, test_df: pd.DataFrame, group_col: str = "trip_id") -> dict[str, Any]:
    """Generates verification metrics for the train/test split."""
    return {
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "train_trips": int(train_df[group_col].nunique()),
        "test_trips": int(test_df[group_col].nunique()),
        "leakage_count": len(set(train_df[group_col]).intersection(set(test_df[group_col]))),
        "split_ratio": round(len(test_df) / (len(train_df) + len(test_df)), 4),
    }
