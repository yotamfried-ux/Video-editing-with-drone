"""Pipeline package bootstrap."""

from pipeline.stages import surf_editor as _surf_editor

_surf_editor.install_surf_editor_patches()
