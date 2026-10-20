"""E12 deployment metadata and runtime mounts; client settings come from Servers."""
from pathlib import Path
import json


def read_deployment(compose):
    """Read the generated role counts without depending on another CLI script."""
    return json.loads(Path(compose).resolve().with_name("deployment.json").read_text())


def prepare_output(output, config):
    """Finalize Docker deployment without rewriting any client command or keys."""
    from tools.blockchain.lib.runtime_mounts import patch_output

    output = Path(output)
    patch_output(output, output / "docker-compose.yml", "/seedemu-node", 524288, False, False)
    (output / "deployment.json").write_text(json.dumps(config, indent=2) + "\n")
