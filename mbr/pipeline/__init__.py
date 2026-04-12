from flask import Blueprint
pipeline_bp = Blueprint("pipeline", __name__)
from mbr.pipeline import routes  # noqa: F401, E402
from mbr.pipeline import lab_routes  # noqa: F401, E402
