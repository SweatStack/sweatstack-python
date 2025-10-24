import os
import sys

# So autodoc can import your package
sys.path.insert(0, os.path.abspath(".."))  # adjust if needed

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",        # if you use Google/NumPy docstrings
    "sphinx_markdown_builder",    # <-- this is the important one
    "myst_parser",                # optional, for .md sources
]

autosummary_generate = True

# Autodoc configuration
autodoc_default_options = {
    'private-members': False,  # Don't document private members (starting with _)
    'special-members': False,  # Don't document special members (like __init__ unless specified)
}

# Optional nice-to-haves for markdown builder:
markdown_anchor_sections = True   # add anchors to each section/function/class
markdown_anchor_signatures = True # add anchors to signatures
markdown_bullet = "*"
