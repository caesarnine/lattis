from __future__ import annotations


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceProtectedError(ValueError):
    pass


class ThreadNotFoundError(LookupError):
    pass


class ThreadAlreadyExistsError(ValueError):
    pass


class ThreadBusyError(RuntimeError):
    pass


class RunNotFoundError(LookupError):
    pass


class ApprovalNotFoundError(LookupError):
    pass


class PluginNotFoundError(LookupError):
    pass
