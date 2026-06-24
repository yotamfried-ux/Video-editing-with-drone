"""Pipeline package helpers."""


def enable_surf_editor_policy() -> None:
    """Enable the conservative surf-specific editor policy for pipeline runs."""
    from pipeline.stages import surf_editor as _surf_editor

    _surf_editor.install_surf_editor_patches()
