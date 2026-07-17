"""Overture cloud download helpers (counterpart of osm2gmns.downloadOSMData)."""

from __future__ import annotations

import inspect
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _geodataframe_callable():
    try:
        from overturemaps import geodataframe
    except ImportError as exc:
        raise ImportError(
            "Cloud download requires 'pip install overture2gmns[download]'."
        ) from exc
    return geodataframe


def download_overture_geodataframes(
    bbox: Sequence[float],
    *,
    feature_types: Sequence[str] = ("segment", "connector"),
    release: str | None = None,
    stac: bool = False,
) -> dict[str, Any]:
    """Fetch Overture feature types for a (west, south, east, north) bbox.

    Uses the official ``overturemaps`` client. ``release`` and ``stac`` are
    forwarded only when the installed client supports them; otherwise a
    warning is emitted and the latest release is used.
    """
    if len(bbox) != 4:
        raise ValueError("bbox must be (west, south, east, north)")
    geodataframe = _geodataframe_callable()
    bbox_tuple = tuple(float(value) for value in bbox)

    supported = set(inspect.signature(geodataframe).parameters)
    extra_kwargs: dict[str, Any] = {}
    for key, value, default in (("release", release, None), ("stac", stac, False)):
        if value == default:
            continue
        if key in supported:
            extra_kwargs[key] = value
        else:
            warnings.warn(
                f"Installed 'overturemaps' client does not support '{key}='; "
                "falling back to its default behavior (latest release).",
                stacklevel=2,
            )

    return {
        feature_type: geodataframe(feature_type, bbox=bbox_tuple, **extra_kwargs)
        for feature_type in feature_types
    }


def download_overture_data(
    bbox: Sequence[float],
    output_folder: str | Path = "",
    *,
    feature_types: Sequence[str] = ("segment", "connector"),
    release: str | None = None,
    stac: bool = False,
    file_format: str = "geoparquet",
) -> dict[str, Path]:
    """Download Overture features for a bbox and save them locally.

    The saved files can then be fed to :func:`overture2gmns.getNetFromFile`,
    mirroring the osm2gmns download-then-parse workflow.

    GeoParquet is the default because GeoJSON round-trips flatten Overture's
    nested struct columns (connectors, speed_limits, ...) into repr strings;
    the converter can usually recover them, but parquet is lossless.
    """
    if file_format not in {"geojson", "geoparquet"}:
        raise ValueError("file_format must be 'geojson' or 'geoparquet'")
    output_path = Path(output_folder) if str(output_folder) else Path.cwd()
    output_path.mkdir(parents=True, exist_ok=True)

    if file_format == "geoparquet":
        return _stream_to_parquet(
            bbox, output_path, feature_types=feature_types, release=release, stac=stac
        )

    frames = download_overture_geodataframes(
        bbox, feature_types=feature_types, release=release, stac=stac
    )
    written: dict[str, Path] = {}
    for feature_type, gdf in frames.items():
        target = output_path / f"{feature_type}.geojson"
        gdf.to_file(target, driver="GeoJSON")
        written[feature_type] = target
    return written


def _stream_to_parquet(
    bbox: Sequence[float],
    output_path: Path,
    *,
    feature_types: Sequence[str],
    release: str | None,
    stac: bool,
) -> dict[str, Path]:
    """Stream Arrow record batches straight to parquet, never holding the
    full extract in memory — required for metro-scale bboxes."""
    try:
        import pyarrow.parquet as pq
        from overturemaps.core import record_batch_reader
    except ImportError as exc:
        raise ImportError(
            "Cloud download requires 'pip install overture2gmns[download]'."
        ) from exc

    bbox_tuple = tuple(float(value) for value in bbox)
    extra: dict[str, Any] = {}
    if release is not None:
        extra["release"] = release
    if stac:
        extra["stac"] = stac

    written: dict[str, Path] = {}
    for feature_type in feature_types:
        target = output_path / f"{feature_type}.parquet"
        partial = output_path / f"{feature_type}.parquet.tmp"
        reader = record_batch_reader(feature_type, bbox=bbox_tuple, **extra)
        if reader is None:
            raise RuntimeError(f"No Overture data reader for type '{feature_type}'")
        with pq.ParquetWriter(partial, reader.schema) as writer:
            for batch in reader:
                if batch.num_rows:
                    writer.write_batch(batch)
        # Atomic-ish finalize so an interrupted download never looks cached.
        partial.replace(target)
        written[feature_type] = target
    return written


# Compatibility alias patterned after osm2gmns.downloadOSMData.
downloadOvertureData = download_overture_data
