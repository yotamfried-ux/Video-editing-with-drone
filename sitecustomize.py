"""Repository interpreter startup hook.

Product behavior is installed explicitly and fail-fast by ``pipeline.bootstrap`` in
every real entrypoint. Keep automatic interpreter startup free of product patches.
"""
