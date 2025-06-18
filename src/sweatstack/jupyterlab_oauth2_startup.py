import argparse
import os
import shutil
from pathlib import Path

import sweatstack as ss
from jupyterlab.labapp import LabApp


def start_jupyterlab_with_oauth():
    parser = argparse.ArgumentParser(
        description="Start an authenticated instance of JupyterLab. Any additional arguments will be passed to the JupyterLab server. Run `jupyterlab --help` to see the available options.",
    )
    parser.add_argument("--no-examples", action="store_true", help="Do not place the example notebooks in the current working directory.")
    args, remaining_args = parser.parse_known_args()

    if not args.no_examples:
        current_dir = Path(__file__).parent
        examples_dir = current_dir / "Sweat Stack examples"
        target_dir = Path.cwd() / "Sweat Stack examples"

        # Only copy the examples if the target directory does not exist
        if not target_dir.exists():
            shutil.copytree(examples_dir, target_dir)

    ss.authenticate()


    return LabApp.launch_instance(argv=remaining_args)