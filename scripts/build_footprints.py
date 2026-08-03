#!/usr/bin/env python3
"""Build lightweight NIRCam and MIRI footprint assets for the dashboard."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import numpy as np
from PIL import Image
import pysiaf
from pysiaf.utils import rotations


PROGRAM_ID = "10678"
APT_URL = f"https://www.stsci.edu/jwst-program-info/download/jwst/apt/{PROGRAM_ID}/"
USER_AGENT = "jwst-gc-dashboard/1.0 (https://github.com/ashleythomasbarnes/jwst_gc_dashboard)"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FITS = Path(
    "/Users/abarnes/Library/CloudStorage/Dropbox/Data/Galactic/Spitzer/GLIMPSE/cmz/"
    "GLM_00000+0000_mosaic_I4-8micron_beam_36-11.5.fits"
)
DEFAULT_GEOMETRY = ROOT / "data" / "footprints.json"
DEFAULT_BACKGROUND = ROOT / "assets" / "spitzer-irac4.webp"
APT_NAMESPACE = "http://www.stsci.edu/JWST/APT"
NS = {"apt": APT_NAMESPACE}


def fetch_apt() -> bytes:
    request = Request(APT_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read()


def read_apt_xml(apt_data: bytes) -> ET.Element:
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(apt_data)) as archive:
        xml_names = [name for name in archive.namelist() if name.endswith(".xml")]
        if len(xml_names) != 1:
            raise ValueError(f"Expected one XML file in the APT archive, found {len(xml_names)}")
        return ET.fromstring(archive.read(xml_names[0]))


def degrees(value: str) -> float:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if not match:
        raise ValueError(f"Could not parse angle from {value!r}")
    return float(match.group())


def parse_program(root: ET.Element) -> tuple[list[dict[str, object]], tuple[float, float]]:
    if root.tag != f"{{{APT_NAMESPACE}}}JwstProposal":
        raise ValueError(f"Unexpected APT root element: {root.tag!r}")

    proposal_id = root.findtext("apt:ProposalInformation/apt:ProposalID", namespaces=NS)
    if proposal_id != PROGRAM_ID:
        raise ValueError(f"Expected program {PROGRAM_ID}, received {proposal_id!r}")

    targets: dict[str, SkyCoord] = {}
    for target in root.findall("apt:Targets/apt:Target", NS):
        name = target.findtext("apt:TargetName", namespaces=NS)
        coordinates = target.find("apt:EquatorialCoordinates", NS)
        if not name or coordinates is None or not coordinates.get("Value"):
            raise ValueError("An APT target is missing its name or coordinates")
        targets[name] = SkyCoord(coordinates.get("Value"), unit=(u.hourangle, u.deg), frame="icrs")

    fields: list[dict[str, object]] = []
    orient_ranges: set[tuple[float, float]] = set()
    for observation in root.findall("apt:DataRequests//apt:Observation", NS):
        number = observation.findtext("apt:Number", namespaces=NS)
        target_reference = observation.findtext("apt:TargetID", namespaces=NS)
        orient = observation.find("apt:SpecialRequirements/apt:OrientRange", NS)
        if not number or not target_reference or orient is None:
            raise ValueError("An APT observation is missing its number, target, or orientation")

        target_name = target_reference.split(" ", 1)[-1]
        if target_name not in targets:
            raise ValueError(f"Observation {number} references unknown target {target_name!r}")

        orient_ranges.add((degrees(orient.get("OrientMin", "")), degrees(orient.get("OrientMax", ""))))
        fields.append({"observation": number, "target": target_name, "coordinate": targets[target_name]})

    if not fields:
        raise ValueError("The APT file contains no observations")
    if len(orient_ranges) != 1:
        raise ValueError(f"Expected one shared orientation range, found {sorted(orient_ranges)}")

    return fields, orient_ranges.pop()


def siaf_for_prd(instrument: str, prd_version: str) -> pysiaf.Siaf:
    basepath = Path(pysiaf.__file__).resolve().parent / "prd_data" / "JWST" / prd_version / "SIAFXML" / "SIAFXML"
    if not basepath.exists():
        raise RuntimeError(f"Installed pysiaf does not include the APT reference data {prd_version}")
    return pysiaf.Siaf(instrument, basepath=str(basepath))


def convex_hull(points: np.ndarray) -> np.ndarray:
    mean_dec = np.deg2rad(points[:, 1].mean())
    ordered = sorted((float(ra * np.cos(mean_dec)), float(dec), float(ra), float(dec)) for ra, dec in points)

    def cross(origin: tuple[float, ...], a: tuple[float, ...], b: tuple[float, ...]) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: list[tuple[float, ...]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, ...]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return np.asarray([(point[2], point[3]) for point in lower[:-1] + upper[:-1]])


def sky_corners(attitude: np.ndarray, aperture: object) -> np.ndarray:
    v2, v3 = aperture.corners("tel")
    ra, dec = rotations.tel_to_sky(attitude, v2, v3)
    return np.column_stack((ra.to_value(u.deg), dec.to_value(u.deg)))


def module_outline(attitude: np.ndarray, siaf: pysiaf.Siaf, names: list[str]) -> np.ndarray:
    corners = np.vstack([sky_corners(attitude, siaf[name]) for name in names])
    return convex_hull(corners)


def normalized_polygon(wcs: WCS, sky: np.ndarray, bounds: tuple[int, int, int, int]) -> list[list[float]]:
    x_min, x_max, y_min, y_max = bounds
    coordinates = SkyCoord(ra=sky[:, 0] * u.deg, dec=sky[:, 1] * u.deg, frame="icrs")
    x, y = wcs.world_to_pixel(coordinates)
    return [
        [round(float((pixel_x - x_min) / (x_max - x_min)), 6), round(float(1 - (pixel_y - y_min) / (y_max - y_min)), 6)]
        for pixel_x, pixel_y in zip(x, y)
    ]


def image_bounds(wcs: WCS, longitude: tuple[float, float], latitude: tuple[float, float]) -> tuple[int, int, int, int]:
    corners = SkyCoord(
        l=[longitude[0], longitude[1], longitude[0], longitude[1]] * u.deg,
        b=[latitude[0], latitude[0], latitude[1], latitude[1]] * u.deg,
        frame="galactic",
    )
    x, y = wcs.world_to_pixel(corners)
    return int(np.floor(x.min())), int(np.ceil(x.max())), int(np.floor(y.min())), int(np.ceil(y.max()))


def write_background(data: np.ndarray, bounds: tuple[int, int, int, int], output: Path, width: int) -> tuple[int, int]:
    x_min, x_max, y_min, y_max = bounds
    crop = np.flipud(np.asarray(data[y_min : y_max + 1, x_min : x_max + 1], dtype=float))
    scaled = np.clip((crop - 8.0) / (420.0 - 8.0), 0, 1)
    scaled = np.arcsinh(scaled / 0.04) / np.arcsinh(1 / 0.04)
    pixels = np.nan_to_num(scaled, nan=0.0) * 255

    height = round(width * crop.shape[0] / crop.shape[1])
    image = Image.fromarray(pixels.astype(np.uint8)).resize((width, height), Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "WEBP", quality=78, method=6)
    return image.size


def build(args: argparse.Namespace) -> None:
    apt_data = args.apt_file.read_bytes() if args.apt_file else fetch_apt()
    root = read_apt_xml(apt_data)
    fields, orient_range = parse_program(root)
    nominal_v3pa = sum(orient_range) / 2
    v3pa = args.v3pa if args.v3pa is not None else nominal_v3pa
    prd_version = root.get("PRDVersion")
    if not prd_version:
        raise ValueError("The APT file does not declare its PRD version")

    nircam = siaf_for_prd("NIRCam", prd_version)
    miri = siaf_for_prd("MIRI", prd_version)
    reference_v2, reference_v3 = nircam["NRCALL_FULL"].reference_point("tel")
    modules = [
        [f"NRCA{detector}_FULL" for detector in range(1, 6)],
        [f"NRCB{detector}_FULL" for detector in range(1, 6)],
    ]

    with fits.open(args.background_fits, memmap=True) as hdus:
        image_data = hdus[0].data
        wcs = WCS(hdus[0].header)
        bounds = image_bounds(wcs, args.longitude, args.latitude)
        background_size = write_background(image_data, bounds, args.background_output, args.background_width)

    output_fields = []
    for field in fields:
        coordinate = field["coordinate"]
        attitude = rotations.attitude_matrix(reference_v2, reference_v3, coordinate.ra.deg, coordinate.dec.deg, v3pa)
        nircam_polygons = [normalized_polygon(wcs, module_outline(attitude, nircam, names), bounds) for names in modules]
        miri_polygons = [normalized_polygon(wcs, sky_corners(attitude, miri["MIRIM_FULL"]), bounds)]
        output_fields.append(
            {
                "observation": field["observation"],
                "target": field["target"],
                "nircam": nircam_polygons,
                "miri": miri_polygons,
            }
        )

    payload = {
        "program_id": PROGRAM_ID,
        "source_url": APT_URL,
        "apt_sha256": hashlib.sha256(apt_data).hexdigest(),
        "apt_version": root.get("APTVersion"),
        "apt_prd_version": prd_version,
        "nominal_v3pa_degrees": v3pa,
        "approved_v3pa_range_degrees": list(orient_range),
        "view": {
            "frame": "galactic",
            "longitude_degrees": list(args.longitude),
            "latitude_degrees": list(args.latitude),
            "background_size": list(background_size),
        },
        "fields": output_fields,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(output_fields)} fields to {args.output}")
    print(f"Wrote {background_size[0]} x {background_size[1]} background to {args.background_output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apt-file", type=Path, help="Read a local .aptx file instead of downloading Program 10678")
    parser.add_argument("--background-fits", type=Path, default=DEFAULT_FITS, help="Spitzer/IRAC 8 micron FITS mosaic")
    parser.add_argument("--output", type=Path, default=DEFAULT_GEOMETRY, help="Footprint JSON output path")
    parser.add_argument("--background-output", type=Path, default=DEFAULT_BACKGROUND, help="WebP background output path")
    parser.add_argument("--background-width", type=int, default=1600, help="WebP width in pixels")
    parser.add_argument("--longitude", type=float, nargs=2, default=(-1.05, 1.25), metavar=("MIN", "MAX"))
    parser.add_argument("--latitude", type=float, nargs=2, default=(-0.30, 0.75), metavar=("MIN", "MAX"))
    parser.add_argument("--v3pa", type=float, help="Override the midpoint of the common APT V3PA range")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
