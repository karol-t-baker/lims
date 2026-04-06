"""
decorators.py — Auth decorators for MBR/EBR webapp.
"""

import functools

from flask import redirect, url_for, session


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """Decorator requiring one of the given roles. Usage: @role_required('admin') or @role_required('laborant_kj', 'laborant')."""
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if session["user"]["rola"] not in roles:
                return "Brak uprawnień", 403
            return f(*args, **kwargs)
        return wrapper
    return decorator
