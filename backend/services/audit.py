"""
Audit logging service.
Gebruik: from services.audit import audit_log
         audit_log('user.create', 'user', target_id=str(user.id), detail={'email': email})
"""
import json
from datetime import datetime
from flask import request
from flask_login import current_user
from app import db


def audit_log(action: str, category: str, *,
              target_type: str = None, target_id: str = None,
              detail: dict = None, school_id: int = None,
              user_id: int = None):
    """
    Schrijf een audit entry naar de database.

    action:      korte actienaam, bv. 'user.create', 'school.delete', 'login.success'
    category:    auth | user | school | class | assessment | doelen | system
    target_type: wat er veranderd is, bv. 'user', 'school', 'class'
    target_id:   identifier van het object (als string)
    detail:      dict met extra context, wordt als JSON opgeslagen
    school_id:   override school_id (standaard current_user.school_id)
    user_id:     override user_id (standaard current_user.id)
    """
    from models import AuditLog

    try:
        uid = user_id
        sid = school_id

        if uid is None:
            try:
                uid = current_user.id if current_user.is_authenticated else None
            except Exception:
                uid = None

        if sid is None:
            try:
                sid = current_user.school_id if current_user.is_authenticated else None
            except Exception:
                sid = None

        ip = None
        try:
            ip = request.remote_addr
        except Exception:
            pass

        entry = AuditLog(
            timestamp   = datetime.utcnow(),
            user_id     = uid,
            school_id   = sid,
            action      = action,
            category    = category,
            target_type = target_type,
            target_id   = str(target_id) if target_id is not None else None,
            detail      = json.dumps(detail, ensure_ascii=False) if detail else None,
            ip_address  = ip,
        )
        db.session.add(entry)
        # Geen commit hier — de aanroeper commit zelf (of we flushen mee)
        db.session.flush()
    except Exception as e:
        # Audit failures mogen de hoofdflow nooit blokkeren
        import logging
        logging.getLogger(__name__).warning(f"Audit log failed: {e}")
