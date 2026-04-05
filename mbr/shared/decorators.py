"""
decorators.py — Auth decorators for MBR/EBR webapp.
"""

import functools

from flask import redirect, url_for, session


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(rola):
    """Decorator requiring a specific role (e.g. 'technolog')."""
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if session["user"]["rola"] != rola:
                return "Brak uprawnień", 403
            return f(*args, **kwargs)
        return wrapper
    return decorator
