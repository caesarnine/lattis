from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from lattis.server.app import create_app
from lattis.settings.storage import load_daemon_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OpenAPI JSON for the Lattis daemon.")
    parser.add_argument("--out", required=True, help="Output path for openapi.json")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lattis-openapi-") as tmpdir:
        config = load_daemon_config(home_dir=Path(tmpdir), auth_disabled=True)
        app = create_app(config=config)
        schema = app.openapi()

    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
