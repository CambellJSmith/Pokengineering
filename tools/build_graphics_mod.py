#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class GraphicsBuildError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def load_registry(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != "pokengineering-confirmed-graphics-assets-v1":
        raise GraphicsBuildError(f"unsupported graphics asset registry format: {path}")
    assets = data.get("assets")
    if not isinstance(assets, dict):
        raise GraphicsBuildError("graphics asset registry has no assets object")
    return data


def load_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    assets = registry["assets"]
    asset = assets.get(asset_id)
    if not isinstance(asset, dict):
        known = ", ".join(sorted(assets)) or "none"
        raise GraphicsBuildError(f"unknown graphics asset {asset_id!r}; known assets: {known}")
    return asset


def find_indexed_entry(filelist_path: Path, index: int) -> str:
    data = json.loads(filelist_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise GraphicsBuildError(f"ACF file list is not an object: {filelist_path}")
    prefix = f"{index:04d}"
    matches = [name for name in data if str(name).split(".", 1)[0] == prefix]
    if len(matches) != 1:
        raise GraphicsBuildError(
            f"expected exactly one ACF entry {prefix} in {filelist_path}, found {matches}"
        )
    return matches[0]


def require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing {description}: {path}")


def require_dir(path: Path, description: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"missing {description}: {path}")


def resolve_repo_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def validate_asset_config(asset_id: str, asset: dict[str, Any]) -> None:
    required = (
        "preview_id",
        "top_level_acf_index",
        "parent_logical_path",
        "nclr",
        "ncgr",
        "ncer",
        "ncer_bank",
        "workspace",
        "default_output_rom",
    )
    missing = [key for key in required if key not in asset]
    if missing:
        raise GraphicsBuildError(f"asset {asset_id} is missing registry fields: {', '.join(missing)}")
    top = int(asset["top_level_acf_index"])
    if asset["parent_logical_path"] != f"acf:{top:04d}":
        raise GraphicsBuildError(f"asset {asset_id} parent logical path does not match its ACF index")
    for kind in ("nclr", "ncgr", "ncer"):
        row = asset[kind]
        if not isinstance(row, dict):
            raise GraphicsBuildError(f"asset {asset_id} {kind} record is not an object")
        for key in ("logical_path", "child_index", "payload_path"):
            if key not in row:
                raise GraphicsBuildError(f"asset {asset_id} {kind} record is missing {key}")
        expected_prefix = f"acf:{top:04d}/acf:{int(row['child_index']):04d}"
        if row["logical_path"] != expected_prefix:
            raise GraphicsBuildError(
                f"asset {asset_id} {kind} logical path does not match parent/child indices"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build an in-game Guardian Signs graphics mod from an edited source-piece workspace. "
            "The asset topology is read from docs/confirmed_graphics_assets.json."
        )
    )
    parser.add_argument("asset_id", help="confirmed asset ID, for example G00583")
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="alternate confirmed-asset registry",
    )
    parser.add_argument("--workspace", type=Path, default=None, help="override edited sprite workspace")
    parser.add_argument("--stage-dir", type=Path, default=None, help="override temporary repack directory")
    parser.add_argument("--output-rom", type=Path, default=None, help="override output .nds path")
    parser.add_argument("--skip-rom", action="store_true", help="stop after rebuilding data_game_us.acf")
    parser.add_argument("--full-rom", action="store_true", help="keep full cartridge padding instead of trimmed output")
    parser.add_argument("--validate-config", action="store_true", help="validate registry/source paths without building")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    registry_path = args.registry or root / "docs/confirmed_graphics_assets.json"
    registry = load_registry(registry_path)
    asset = load_asset(registry, args.asset_id)
    validate_asset_config(args.asset_id, asset)

    acftool = root / "tools/bin/acftool"
    sprite_editor = root / "tools/edit_ncer_sprite.py"
    nds_builder = root / "tools/rebuild_nds.py"
    nds_validator = root / "tools/validate_nds.py"
    archive_dir = root / "work/game_acf/archive"

    workspace = args.workspace or resolve_repo_path(root, str(asset["workspace"]))
    stage = args.stage_dir or workspace / "repack"
    output_rom = args.output_rom or resolve_repo_path(root, str(asset["default_output_rom"]))

    nclr = resolve_repo_path(root, str(asset["nclr"]["payload_path"]))
    ncgr = resolve_repo_path(root, str(asset["ncgr"]["payload_path"]))
    ncer = resolve_repo_path(root, str(asset["ncer"]["payload_path"]))
    parent_index = int(asset["top_level_acf_index"])
    ncgr_child_index = int(asset["ncgr"]["child_index"])
    bank_index = int(asset["ncer_bank"])
    parent_acf = archive_dir / f"{parent_index:04d}.acf"

    for path, description in (
        (nclr, "NCLR payload"),
        (ncgr, "NCGR payload"),
        (ncer, "NCER payload"),
        (parent_acf, "parent nested ACF"),
        (sprite_editor, "sprite editor"),
    ):
        require_file(path, description)
    require_dir(archive_dir, "extracted data_game_us.acf archive directory")
    require_file(archive_dir / "filelist.json", "top-level ACF file list")

    if args.validate_config:
        print(f"graphics asset configuration valid: {args.asset_id}")
        print(f"preview: {asset['preview_id']}")
        print(f"parent: {asset['parent_logical_path']}")
        print(f"NCGR: {asset['ncgr']['logical_path']}")
        return 0

    require_file(acftool, "acftool executable")
    require_dir(workspace, "edited sprite workspace")
    require_file(workspace / "manifest.json", "sprite edit manifest")
    require_dir(workspace / "pieces", "edited sprite pieces")

    modified_ncgr = workspace / f"{ncgr.stem}.modified.ncgr"
    run(
        [
            sys.executable,
            str(sprite_editor),
            "import",
            str(ncgr),
            str(nclr),
            str(ncer),
            str(workspace),
            str(modified_ncgr),
        ]
    )

    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    nested_input = stage / f"nested_{parent_index:04d}.acf"
    shutil.copy2(parent_acf, nested_input)
    run([str(acftool), "--extract", str(nested_input)])
    nested_dir = nested_input.with_suffix("")
    nested_filelist = nested_dir / "filelist.json"
    require_file(nested_filelist, "nested ACF file list")
    ncgr_entry = find_indexed_entry(nested_filelist, ncgr_child_index)
    shutil.copy2(modified_ncgr, nested_dir / ncgr_entry)

    nested_input.unlink()
    run([str(acftool), "--build", str(nested_dir)])
    rebuilt_nested = nested_dir.with_suffix(".acf")
    require_file(rebuilt_nested, "rebuilt nested ACF")

    verify_root = stage / "verify_nested"
    verify_root.mkdir()
    verify_acf = verify_root / f"nested_{parent_index:04d}.acf"
    shutil.copy2(rebuilt_nested, verify_acf)
    run([str(acftool), "--extract", str(verify_acf)])
    verify_dir = verify_acf.with_suffix("")
    verify_entry = find_indexed_entry(verify_dir / "filelist.json", ncgr_child_index)
    verified_ncgr = verify_dir / verify_entry
    if modified_ncgr.read_bytes() != verified_ncgr.read_bytes():
        raise GraphicsBuildError("rebuilt nested ACF does not contain the exact modified NCGR bytes")
    print(f"nested NCGR replacement verified: {asset['ncgr']['logical_path']}")

    game_archive = stage / "game_archive"
    shutil.copytree(archive_dir, game_archive)
    top_entry = find_indexed_entry(game_archive / "filelist.json", parent_index)
    shutil.copy2(rebuilt_nested, game_archive / top_entry)
    run([str(acftool), "--build", str(game_archive)])
    rebuilt_game_acf = game_archive.with_suffix(".acf")
    require_file(rebuilt_game_acf, "rebuilt data_game_us.acf")
    if rebuilt_game_acf.read_bytes()[:4] != b"acf\0":
        raise GraphicsBuildError("rebuilt data_game_us.acf does not begin with acf\\0")

    summary: dict[str, Any] = {
        "format": "pokengineering-graphics-build-summary-v1",
        "asset_id": args.asset_id,
        "preview_id": asset["preview_id"],
        "modified_ncgr": str(modified_ncgr.relative_to(root)),
        "modified_ncgr_sha256": sha256_file(modified_ncgr),
        "rebuilt_nested_acf": str(rebuilt_nested.relative_to(root)),
        "rebuilt_nested_acf_sha256": sha256_file(rebuilt_nested),
        "rebuilt_game_acf": str(rebuilt_game_acf.relative_to(root)),
        "rebuilt_game_acf_sha256": sha256_file(rebuilt_game_acf),
        "rom_built": False,
    }

    if not args.skip_rom:
        require_file(nds_builder, "NDS rebuilder")
        require_file(nds_validator, "NDS validator")
        output_rom.parent.mkdir(parents=True, exist_ok=True)
        build_command = [
            sys.executable,
            str(nds_builder),
            "--components",
            str(root),
            "--output",
            str(output_rom),
            "--replace",
            f"data/data_game_us.acf={rebuilt_game_acf}",
        ]
        if not args.full_rom:
            build_command.append("--trim")
        run(build_command)
        run(
            [
                sys.executable,
                str(nds_validator),
                str(output_rom),
                "--components",
                str(root),
                "--expect",
                f"data/data_game_us.acf={rebuilt_game_acf}",
            ]
        )
        summary["rom_built"] = True
        summary["output_rom"] = str(output_rom.relative_to(root)) if output_rom.is_relative_to(root) else str(output_rom)
        summary["output_rom_sha256"] = sha256_file(output_rom)

    summary_path = workspace / "build_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"graphics mod built: {args.asset_id}")
    print(f"modified NCGR: {modified_ncgr}")
    print(f"rebuilt data_game_us.acf: {rebuilt_game_acf}")
    if summary["rom_built"]:
        print(f"validated ROM: {output_rom}")
    print(f"build summary: {summary_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError, GraphicsBuildError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"error: {exc}") from exc
