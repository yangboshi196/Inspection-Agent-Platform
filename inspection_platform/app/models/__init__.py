"""SQLAlchemy ORM 实体（MySQL security_risk 库）。"""

from inspection_platform.app.models.algorithm import Algorithm
from inspection_platform.app.models.auth import AuthRole, AuthSession, AuthUser
from inspection_platform.app.models.base import Base
from inspection_platform.app.models.document import Document
from inspection_platform.app.models.equipment import Equipment, SensorReading
from inspection_platform.app.models.inspection_event import InspectionEvent
from inspection_platform.app.models.inspection_work import InspectionWork
from inspection_platform.app.models.inspection_work_tracking import InspectionWorkTracking
from inspection_platform.app.models.region import Region
from inspection_platform.app.models.report import (
    InspectionReport,
    ReportPlan,
    ReportTemplate,
    UserReportPushSubscription,
    WorkReportTemplateBinding,
)
from inspection_platform.app.models.specification import SpecRule

__all__ = [
    "Base",
    "AuthUser",
    "AuthRole",
    "AuthSession",
    "Document",
    "Region",
    "Equipment",
    "SensorReading",
    "Algorithm",
    "InspectionWork",
    "InspectionWorkTracking",
    "InspectionEvent",
    "SpecRule",
    "ReportTemplate",
    "ReportPlan",
    "InspectionReport",
    "WorkReportTemplateBinding",
    "UserReportPushSubscription",
]
