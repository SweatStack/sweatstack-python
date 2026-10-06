import os

from IPython import start_ipython


def run_ipython():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    startup_script = os.path.join(script_dir, "ipython_init.py")

    ipython_args = [f"--InteractiveShellApp.exec_files={startup_script}"]

    start_ipython(argv=ipython_args)
