from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from lattice.settings.storage import StorageConfig
from lattice.server.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OpenAPI JSON for the Lattice server.")
    parser.add_argument("--out", required=True, help="Output path for openapi.json")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lattice-openapi-") as tmpdir:
        tmp = Path(tmpdir)
        data_dir = tmp / "data"
        workspace_dir = tmp / "workspace"
        data_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir.mkdir(parents=True, exist_ok=True)

        config = StorageConfig(
            data_dir=data_dir,
            db_path=data_dir / "lattice.db",
            session_id_path=data_dir / "session_id",
            workspace_dir=workspace_dir,
            project_root=Path.cwd(),
            workspace_mode="local",
        )
        app = create_app(config=config)
        schema = app.openapi()

    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
